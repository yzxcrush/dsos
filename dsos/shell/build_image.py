import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_shell as gb
from kernel_body import build

blob, labels = build()
print(f"kernel: {len(blob)} bytes (budget 4096)  labels={len(labels)}")
if len(blob) > 4096:
    sys.exit("kernel too big")

st2 = gb.stage2(shell=True)
print(f"stage2(shell=True): {len(st2)} bytes (budget {gb.LOAD_SECTORS*512})")
if len(st2) > gb.LOAD_SECTORS * 512:
    sys.exit("stage2 too big")

img = gb.boot_sector()
img += st2 + b"\x00" * (4096 - len(st2))
img += blob + b"\x00" * (4096 - len(blob))
img += b"\x00" * (1440 * 1024 - len(img))
out = os.path.join(HERE, "dsos-x86_64-shell.img")
open(out, "wb").write(img)
import hashlib
print(f"wrote {out}  {len(img)} bytes  sha256={hashlib.sha256(img).hexdigest()}")
print(f"boot sig: {img[510:512].hex()}")
print(f"kernel @0x9000 -> image offset 4608; first kernel bytes: {img[4608:4624].hex(' ')}")
open(os.path.join(HERE, "kernel.bin"), "wb").write(blob)
