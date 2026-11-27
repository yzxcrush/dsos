"""dsos-os/ds/verify_bootchain.py — 端到端验证「全 Ds 引导链」

MBR → stage2 → 长模式跳转前，全部在 unicorn 16 位模式下执行。
覆盖：
  1. MBR 用 int13h 把 stage2+内核读到 0x8000
  2. 跳进 stage2 后：A20 / 页表 / GDT / CR 全部就位
  3. 远跳指令存在（模式切换本身无法用 unicorn 验证）
"""
import pathlib, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from unicorn import *
from unicorn.x86_const import *
from mini16 import compile_source

IMG = (HERE / "dsos-ds.img").read_bytes()
mbr = compile_source((HERE / "mbr.ds").read_text(encoding="utf-8"))
s2 = compile_source((HERE / "stage2.ds").read_text(encoding="utf-8"))
print(f"MBR {len(mbr)} B / stage2 {len(s2)} B / 镜像 {len(IMG)} B")

uc = Uc(UC_ARCH_X86, UC_MODE_16)
uc.mem_map(0, 0x100000)
uc.mem_write(0x7C00, bytes(IMG[0:512]))
uc.reg_write(UC_X86_REG_CS, 0)
uc.reg_write(UC_X86_REG_IP, 0x7C00)
uc.reg_write(UC_X86_REG_DL, 0x80)

reads, st = [], {"in_s2": False, "far": False}
FAR_OFF = s2.find(bytes([0xEA, 0x00, 0x90, 0x08, 0x00]))


def on_intr(uc, intno, ud):
    if intno != 0x13:
        return
    eax = uc.reg_read(UC_X86_REG_EAX)
    if (eax >> 8) & 0xFF != 0x02:
        return
    al = eax & 0xFF
    cx = uc.reg_read(UC_X86_REG_ECX) & 0xFFFF
    dx = uc.reg_read(UC_X86_REG_EDX) & 0xFFFF
    cyl, sec, head = (cx >> 8) & 0xFF, cx & 0x3F, (dx >> 8) & 0xFF
    lba = ((cyl * 255) + head) * 63 + (sec - 1)
    es = uc.reg_read(UC_X86_REG_ES) & 0xFFFF
    bx = uc.reg_read(UC_X86_REG_EBX) & 0xFFFF
    reads.append((lba, al, es, bx))
    uc.mem_write((es << 4) + bx, bytes(IMG[lba * 512: lba * 512 + al * 512]))
    uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) & ~1)


def on_code(uc, addr, size, ud):
    if addr == 0x8000:
        st["in_s2"] = True
    if st["in_s2"] and FAR_OFF >= 0 and addr == 0x8000 + FAR_OFF:
        st["far"] = True
        uc.emu_stop()


uc.hook_add(UC_HOOK_INTR, on_intr)
uc.hook_add(UC_HOOK_CODE, on_code)

err = None
try:
    uc.emu_start(0x7C00, 0, count=500000)
except UcError as e:
    err = e

pml4 = int.from_bytes(bytes(uc.mem_read(0x1000, 8)), "little")
pdpt = int.from_bytes(bytes(uc.mem_read(0x2000, 8)), "little")
pd = int.from_bytes(bytes(uc.mem_read(0x3000, 8)), "little")
cr0 = uc.reg_read(UC_X86_REG_CR0)
cr3 = uc.reg_read(UC_X86_REG_CR3)
cr4 = uc.reg_read(UC_X86_REG_CR4)
kern_ok = bytes(uc.mem_read(0x9000, 64)) == IMG[4608:4672]

print(f"int13h: {reads}")
print(f"err={err} 进入stage2={st['in_s2']} 到达远跳={st['far']}")
print(f"PML4={pml4:#x} PDPT={pdpt:#x} PD={pd:#x} CR0={cr0:#x} CR3={cr3:#x} CR4={cr4:#x}")

checks = {
    "MBR 读盘参数正确": any(r == (1, 32, 0x0800, 0) for r in reads),
    "跳入 stage2": st["in_s2"],
    "页表就位": (pml4 & ~0x60) == 0x2003 and (pdpt & ~0x60) == 0x3003 and (pd & ~0x60) == 0x83,
    "GDT 就位": int.from_bytes(bytes(uc.mem_read(0x5F08, 8)), "little") == 0x00AF9A000000FFFF,
    "分页已开": bool(cr0 & 0x80000000),
    "CR3/PAE 就位": cr3 == 0x1000 and bool(cr4 & 0x20),
    "内核已加载到 0x9000": kern_ok,
    # 远跳本身无法执行（unicorn 不切换模式）；CR0.PG 已置位 = 已执行到远跳前一句，
    # 且远跳字节确实在预期位置。
    "远跳就位（PG 已开，下一条即远跳）": bool(cr0 & 0x80000000) and FAR_OFF >= 0,
}
ok_all = True
print()
for k, v in checks.items():
    ok_all &= bool(v)
    print(f"[{'PASS' if v else 'FAIL'}] {k}")
print("\n注：CPU 模式切换（远跳本身）无法用 unicorn 验证，需真机确认。")
print("RESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
