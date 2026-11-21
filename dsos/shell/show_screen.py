"""Render the VGA text screen (chars + attributes) so the UI can be eyeballed."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import *
from unicorn.x86_const import *
import gen_shell as gb
from kernel_body import build

blob, labels = build()
BASE = 0x9000
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0, 0x200000)
uc.mem_write(BASE, blob)
uc.mem_write(0x8000, b"\x00" * 4096)
uc.reg_write(UC_X86_REG_GDTR, (0, gb.STAGE2_ADDR + gb.GDT_OFF, 5 * 8 - 1, 0))
uc.reg_write(UC_X86_REG_RSP, 0x70000)
uc.mem_write(0x6000, b"\xf4\xeb\xfd")

keys = []


def on_in(uc, *a):
    p = a[0]
    if p == 0x3FD:
        return 0x20
    if p == 0x60:
        return keys.pop(0) if keys else 0
    return 0


def on_out(uc, *a):
    pass


uc.hook_add(UC_HOOK_INSN, on_in, None, 1, 0, UC_X86_INS_IN)
uc.hook_add(UC_HOOK_INSN, on_out, None, 1, 0, UC_X86_INS_OUT)

SCAN = {}
for i, ch in enumerate("1234567890"):
    SCAN[ch] = 0x02 + i
for i, ch in enumerate("qwertyuiop"):
    SCAN[ch] = 0x10 + i
for i, ch in enumerate("asdfghjkl"):
    SCAN[ch] = 0x1E + i
for i, ch in enumerate("zxcvbnm"):
    SCAN[ch] = 0x2C + i
SCAN[" "] = 0x39
SCAN["\n"] = 0x1C


def run(addr, n=300000):
    try:
        uc.emu_start(addr, 0, count=n)
    except UcError:
        pass


def press(ch):
    keys.append(SCAN[ch])
    sp = 0x6F000
    uc.mem_write(sp, (0x6000).to_bytes(8, "little"))
    uc.mem_write(sp + 8, (0x18).to_bytes(8, "little"))
    uc.mem_write(sp + 16, (0x202).to_bytes(8, "little"))
    uc.reg_write(UC_X86_REG_RSP, sp)
    run(0x9000 + labels["irq1"], 5000)
    uc.reg_write(UC_X86_REG_RSP, 0x70000)
    run(0x9000 + labels["main_loop"], 200000)


def screen():
    raw = bytes(uc.mem_read(0xB8000, 80 * 25 * 2))
    rows = []
    for r in range(25):
        chunk = raw[r * 160:(r + 1) * 160]
        chars = "".join(chr(chunk[i]) if 32 <= chunk[i] < 127 else " " for i in range(0, 160, 2))
        attrs = {chunk[i + 1] for i in range(0, 160, 2)}
        rows.append((chars, attrs))
    return rows


def show(title):
    print(f"\n=== {title} ===")
    rows = screen()
    for r, (chars, attrs) in enumerate(rows):
        mark = " <-- title" if r == 0 else (" <-- status" if r == 24 else "")
        print(f"{r:2d}|{chars.rstrip():<79}| attr={sorted(hex(a) for a in attrs)}{mark}")


run(BASE)
show("boot")

for _ in range(4):
    for ch in "help\n":
        press(ch)
show("after 4x help (should have scrolled, bars intact)")

for ch in "ticks\n":
    press(ch)
show("after ticks (status bar should show a counter)")


print("\n=== raw attributes ===")
raw = bytes(uc.mem_read(0xB8000, 80*25*2))
for r in (0, 1, 24):
    attrs = [raw[r*160 + i + 1] for i in range(0, 160, 2)]
    zero_at = [i for i, a in enumerate(attrs) if a == 0]
    print(f"row {r}: distinct={sorted(set(attrs))}  zero-cells={len(zero_at)} at {zero_at[:12]}")
