"""One-command release pipeline for DsOS. Enforces the house rules.

     python release.py            # build + verify only (safe)
     python release.py --flash    # build + verify + guard + write USB + readback

Refuses to continue if any gate fails. Order matters:
  1. build image
  2. run the acceptance harness; require "RESULT: PASS"
  3. (optional) flash with disk guards, then verify by reading back
"""
import hashlib, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
IMAGE = os.path.join(HERE, "dsos-x86_64-shell.img")
FLASHER = os.path.join(os.path.dirname(HERE), "_flash_usb.py")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def run(label, args, must_contain=None):
    print(f"\n=== {label} ===")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([PY] + args, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    tail = [l for l in out.splitlines() if l.strip()][-12:]
    for l in tail:
        print("   " + l)
    if r.returncode != 0:
        sys.exit(f"\nGATE FAILED: {label} exited {r.returncode}")
    if must_contain and must_contain not in out:
        sys.exit(f"\nGATE FAILED: {label} did not print {must_contain!r}")
    print(f"   -> gate OK")


def main():
    flash = "--flash" in sys.argv

    run("build image", ["build_image.py"], must_contain="wrote ")
    if not os.path.exists(IMAGE):
        sys.exit("GATE FAILED: no image produced")

    run("acceptance harness (unicorn)", ["verify_shell.py"], must_contain="RESULT: PASS")

    digest = sha(IMAGE)
    size = os.path.getsize(IMAGE)
    print(f"\n=== artifact ===")
    print(f"   {os.path.basename(IMAGE)}  {size} bytes  sha256={digest}")

    if not flash:
        print("\nnot flashing (pass --flash to write the USB).")
        print("RELEASE READY")
        return

    if not os.path.exists(FLASHER):
        sys.exit(f"\nGATE FAILED: flasher not found at {FLASHER}\n"
                 "the USB writer is deliberately kept outside the repo; "
                 "point FLASHER at your own guarded writer.")
    run("flash USB (guards + readback)", [FLASHER, IMAGE], must_contain="VERIFIED")
    print(f"\nRELEASE FLASHED  sha256={digest}")


if __name__ == "__main__":
    main()
