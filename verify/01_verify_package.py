import os, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
OUTDIR = pathlib.Path(os.environ.get("VERIFY_OUT", str(REPO / "_verify_out")))
OUTDIR.mkdir(parents=True, exist_ok=True)
import hashlib, io, os, sys

ROOT = str(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else REPO)

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

ok = bad = missing = 0
rows = []
sums_path = os.path.join(ROOT, "SHA256SUMS")
if not os.path.exists(sums_path):
    print(f"no SHA256SUMS in {ROOT}")
    print("this script verifies a Ds handover package, not this git repo.")
    print("usage: python 01_verify_package.py /path/to/handover-root")
    sys.exit(2)
with io.open(sums_path, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        want, _, rel = line.partition("  ")
        rel = rel.strip()
        # SHA256SUMS uses forward slashes relative to package root
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.exists(p):
            missing += 1
            rows.append(("MISSING", rel))
            continue
        got = sha(p)
        if got == want:
            ok += 1
        else:
            bad += 1
            rows.append(("MISMATCH", f"{rel}\n    want {want}\n    got  {got}"))

print(f"SHA256SUMS: ok={ok} bad={bad} missing={missing}")
for k, v in rows:
    print(f"  [{k}] {v}")

# MANIFEST cross-check
import json
man = json.load(io.open(os.path.join(ROOT, "MANIFEST.json"), encoding="utf-8"))
print(f"\nMANIFEST declares: file_count={man['file_count']} total_bytes={man['total_bytes']} redacted={man['redacted']}")
listed = man["files"]
print(f"manifest entries listed: {len(listed)}")

# count actual files on disk (excluding nothing)
n = 0
total = 0
for dirpath, dirnames, filenames in os.walk(ROOT):
    for fn in filenames:
        n += 1
        total += os.path.getsize(os.path.join(dirpath, fn))
print(f"actual on disk: files={n} bytes={total}")

mis = 0
for e in listed:
    p = os.path.join(ROOT, e["path"].replace("/", os.sep))
    if not os.path.exists(p):
        continue
    if os.path.getsize(p) != e["bytes"]:
        mis += 1
        print(f"  size mismatch: {e['path']} manifest={e['bytes']} actual={os.path.getsize(p)}")
print(f"manifest size mismatches: {mis}")
