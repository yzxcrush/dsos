import os, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
OUTDIR = pathlib.Path(os.environ.get("VERIFY_OUT", str(REPO / "_verify_out")))
OUTDIR.mkdir(parents=True, exist_ok=True)
import hashlib, os, shutil, subprocess, sys, io, tempfile

PY = sys.executable
BASE = str(REPO)
WORK = str(OUTDIR / "regen")

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

def run(cwd, script):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([PY, script], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)

results = []

# Each case: (label, source dir to copy, generator script, files to compare)
cases = [
    ("step1", os.path.join(BASE, "dsos", "toolchain", "step1"), "gen_step1.py",
     ["syscall.bin", "syscall.elf", "bare_serial.bin", "syscall.hex"]),
    ("boot-images", os.path.join(BASE, "dsos", "images", "x86_64"), "gen_boot.py",
     ["dsos-x86_64.img", "dsos-bios.img"]),
]

os.makedirs(WORK, exist_ok=True)
for label, srcdir, script, files in cases:
    dst = os.path.join(WORK, label)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(srcdir, dst)
    # remove the committed outputs so we can tell regeneration really produced them
    committed = {}
    for f in files:
        p = os.path.join(dst, f)
        if os.path.exists(p):
            committed[f] = sha(p)
            os.remove(p)
    r = run(dst, script)
    results.append(f"## {label}: python {script} -> exit {r.returncode}")
    if r.stdout.strip():
        results.append("   stdout: " + " | ".join(r.stdout.strip().splitlines()[:4]))
    if r.stderr.strip():
        results.append("   stderr: " + " | ".join(r.stderr.strip().splitlines()[:4]))
    for f in files:
        p = os.path.join(dst, f)
        if not os.path.exists(p):
            results.append(f"   {f}: REGENERATION MISSING")
            continue
        new = sha(p)
        old = committed.get(f)
        if old is None:
            results.append(f"   {f}: regenerated (no committed copy) {os.path.getsize(p)}B")
        elif old == new:
            results.append(f"   {f}: IDENTICAL  {os.path.getsize(p)}B  {new[:16]}")
        else:
            results.append(f"   {f}: DIFFERS  committed={os.path.getsize(p) if False else ''}{old[:16]} new={new[:16]}")
    results.append("")

# phase1 build
p1 = os.path.join(BASE, "dsos", "phase1")
dst = os.path.join(WORK, "phase1")
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree(p1, dst)
committed = {}
for f in ["kernel.bin"]:
    p = os.path.join(dst, f)
    if os.path.exists(p):
        committed[f] = sha(p)
        os.remove(p)
r = run(dst, "build.py")
results.append(f"## phase1: python build.py -> exit {r.returncode}")
if r.stdout.strip():
    results.append("   stdout: " + " | ".join(r.stdout.strip().splitlines()[:6]))
if r.stderr.strip():
    results.append("   stderr: " + " | ".join(r.stderr.strip().splitlines()[:6]))
for f in ["kernel.bin"]:
    p = os.path.join(dst, f)
    if not os.path.exists(p):
        results.append(f"   {f}: MISSING after build")
    else:
        new = sha(p)
        old = committed.get(f)
        results.append(f"   {f}: {'IDENTICAL' if old == new else 'DIFFERS'} size={os.path.getsize(p)} "
                       f"old={str(old)[:16]} new={new[:16]}")

txt = "\n".join(results)
io.open(str(OUTDIR / "_regen_result.txt"), "w", encoding="utf-8").write(txt)
print(txt)
