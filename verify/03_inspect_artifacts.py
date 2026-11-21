import os, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
OUTDIR = pathlib.Path(os.environ.get("VERIFY_OUT", str(REPO / "_verify_out")))
OUTDIR.mkdir(parents=True, exist_ok=True)
import struct, io, os, sys

BASE = str(REPO)

def read(p):
    with open(p, "rb") as f:
        return f.read()

def elf_info(p, label):
    b = read(p)
    out = [f"### {label}  ({len(b)} bytes)"]
    if b[:4] != b"\x7fELF":
        out.append(f"  NOT ELF (first 4 = {b[:4]!r})")
        return out
    cls, data, ver, osabi = b[4], b[5], b[6], b[7]
    out.append(f"  class={'ELF32' if cls==1 else 'ELF64'} endian={'LE' if data==1 else 'BE'} osabi={osabi}")
    if cls == 1:
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags, e_ehsize, e_phentsize, e_phnum = \
            struct.unpack_from("<HHIIIIIHHH", b, 16)
    else:
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags, e_ehsize, e_phentsize, e_phnum = \
            struct.unpack_from("<HHIQQQIHHH", b, 16)
    mach = {3: "x86", 62: "x86_64", 183: "aarch64", 40: "arm"}.get(e_machine, str(e_machine))
    out.append(f"  type={e_type} machine={mach} entry=0x{e_entry:x} phoff={e_phoff} phnum={e_phnum}")
    for i in range(e_phnum):
        if cls == 1:
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
                struct.unpack_from("<IIIIIIII", b, e_phoff + i * e_phentsize)
        else:
            p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = \
                struct.unpack_from("<IIQQQQQQ", b, e_phoff + i * e_phentsize)
        kind = {0: "NULL", 1: "LOAD", 2: "DYNAMIC", 3: "INTERP", 4: "NOTE"}.get(p_type, str(p_type))
        out.append(f"    ph{i}: {kind} off=0x{p_offset:x} vaddr=0x{p_vaddr:x} paddr=0x{p_paddr:x} "
                   f"filesz=0x{p_filesz:x} memsz=0x{p_memsz:x} flags={p_flags}")
    return out, b

def multiboot_scan(b, label):
    out = [f"### Multiboot header scan — {label}"]
    found = False
    for off in range(0, min(len(b) - 12, 8192), 4):
        if struct.unpack_from("<I", b, off)[0] == 0x1BADB002:
            flags, checksum = struct.unpack_from("<II", b, off + 4)
            ok = (0x1BADB002 + flags + checksum) & 0xFFFFFFFF == 0
            out.append(f"  magic @0x{off:x} flags=0x{flags:x} checksum_ok={ok}")
            found = True
    if not found:
        out.append("  ** NO 0x1BADB002 magic in first 8 KiB **")
    return out

def boot_sector(p, label):
    b = read(p)
    out = [f"### {label}  ({len(b)} bytes = {len(b)/1024:.0f} KiB)"]
    if len(b) >= 512:
        sig = b[510:512]
        out.append(f"  boot sig @510 = {sig!r} ({'valid 0xAA55' if sig == b'\\x55\\xaa' else 'INVALID'})")
        out.append(f"  first bytes: {b[:16].hex(' ')}")
    # search for strings
    for s in (b"DsOS", b"alive", b"tick"):
        idx = b.find(s)
        out.append(f"  string {s!r} -> {'@0x%x' % idx if idx >= 0 else 'not found'}")
    return out

files = [
    ("phase1 kernel.bin", os.path.join(BASE, "dsos", "phase1", "kernel.bin")),
    ("step2 hello.elf", os.path.join(BASE, "dsos", "toolchain", "step2", "examples", "hello.elf")),
    ("step4 call.elf", os.path.join(BASE, "dsos", "toolchain", "step4", "examples", "call.elf")),
    ("step5 branch.elf", os.path.join(BASE, "dsos", "toolchain", "step5", "examples", "branch.elf")),
]
lines = []
for label, p in files:
    if not os.path.exists(p):
        lines.append(f"### {label}: MISSING {p}")
        continue
    r = elf_info(p, label)
    body = None
    if isinstance(r, tuple):
        lines.extend(r[0]); body = r[1]
    else:
        lines.extend(r)
    if body:
        lines.extend(multiboot_scan(body, label))
    lines.append("")

img = os.path.join(BASE, "dsos", "images", "x86_64", "dsos-x86_64.img")
if os.path.exists(img):
    lines.extend(boot_sector(img, "dsos-x86_64.img"))
bios = os.path.join(BASE, "dsos", "images", "x86_64", "dsos-bios.img")
if os.path.exists(bios):
    lines.extend(boot_sector(bios, "dsos-bios.img"))

txt = "\n".join(lines)
io.open(str(OUTDIR / "_artifact_check.txt"), "w", encoding="utf-8").write(txt)
print(txt)
