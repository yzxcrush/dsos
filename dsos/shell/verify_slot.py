"""Verify B1: stage2 really loads the DSSCRIPT slot from disk into 0x20000."""
import os, struct, sys
from unicorn import *
from unicorn.x86_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from put_script import build_slot, parse_slot, SLOT_OFF, SLOT_BYTES

SCRIPT = b'p("hello from the USB slot")\nlet x = 1 + 2\n'

img = bytearray(open(os.path.join(HERE, "dsos-x86_64-shell.img"), "rb").read())
img[SLOT_OFF:SLOT_OFF + SLOT_BYTES] = build_slot(SCRIPT)
img = bytes(img)

uc = Uc(UC_ARCH_X86, UC_MODE_16)
uc.mem_map(0, 0x200000)
uc.mem_write(0x7C00, img[:512])
uc.reg_write(UC_X86_REG_CS, 0)
uc.reg_write(UC_X86_REG_IP, 0x7C00)
uc.reg_write(UC_X86_REG_DL, 0x80)

reads = []


def chs_to_lba(cyl, head, sec):
    return ((cyl * 255) + head) * 63 + (sec - 1)


def on_intr(uc, intno, ud):
    if intno != 0x13:
        return
    eax = uc.reg_read(UC_X86_REG_EAX)
    ah, al = (eax >> 8) & 0xFF, eax & 0xFF
    if ah != 0x02:
        reads.append(("unhandled ah", ah))
        return
    cx = uc.reg_read(UC_X86_REG_ECX)
    dx = uc.reg_read(UC_X86_REG_EDX)
    cyl, sec = (cx >> 8) & 0xFF, cx & 0x3F
    head = (dx >> 8) & 0xFF
    lba = chs_to_lba(cyl, head, sec)
    buf = (uc.reg_read(UC_X86_REG_ES) << 4) + (uc.reg_read(UC_X86_REG_EBX) & 0xFFFF)
    data = img[lba * 512: lba * 512 + al * 512]
    uc.mem_write(buf, data)
    reads.append((lba, al, buf))
    uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) & ~1)


uc.hook_add(UC_HOOK_INTR, on_intr)
try:
    uc.emu_start(0x7C00, 0, count=500000)
except UcError as e:
    print("stopped:", e)

print("int13 reads:", [(f"lba={l}", f"n={n}", f"->0x{b:x}") for l, n, b in reads if isinstance(l, int)])

slot = bytes(uc.mem_read(0x20000, SLOT_BYTES))
src = parse_slot(slot)
print(f"magic at 0x20000: {slot[:4]!r}")
print(f"payload: {src!r}")
ok = src == SCRIPT
print(f"[B1] stage2 loaded the USB script slot: {'PASS' if ok else 'FAIL'}")

# stage2 must still have loaded the kernel area intact
ok_stage2 = bytes(uc.mem_read(0x8000, 32)) == img[512:544]
print(f"[B1] stage2 bytes still correct: {'PASS' if ok_stage2 else 'FAIL'}")
print("RESULT:", "PASS" if (ok and ok_stage2) else "FAIL")
