"""compiler/verify_mbr16.py — Ds 的 16 位实模式后端验收

验证 mini16.py 能产出真正在实模式运行的机器码：
  1. 段寄存器/栈设置 + int 10h 字符输出
  2. 循环 + 条件分支（16 位）
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini16 import compile_source

CASES = [
    ("int10h 输出 DsOS", """
fn _start16() {
    set_ds(0)
    set_es(0)
    set_ss(0)
    mov_sp(31744)
    bios_putc(68)
    bios_putc(115)
    bios_putc(79)
    bios_putc(83)
    halt()
}
""", "DsOS"),

    ("循环打印 AAAA", """
fn _start16() {
    set_ds(0)
    set_es(0)
    set_ss(0)
    mov_sp(31744)
    let i = 0
    while i < 4 {
        bios_putc(65)
        i = i + 1
    }
    halt()
}
""", "AAAA"),

    ("条件分支", """
fn _start16() {
    set_ds(0)
    set_es(0)
    set_ss(0)
    mov_sp(31744)
    let x = 5
    if x > 3 { bios_putc(89) } else { bios_putc(78) }
    halt()
}
""", "Y"),
]

ok_all = True
for name, src, want in CASES:
    code = compile_source(src)
    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0, 0x100000)
    uc.mem_write(0x7C00, code)
    uc.reg_write(UC_X86_REG_CS, 0)
    uc.reg_write(UC_X86_REG_IP, 0x7C00)
    outs = []

    def on_intr(u, intno, ud):
        if intno == 0x10:
            eax = u.reg_read(UC_X86_REG_EAX)
            outs.append(((eax >> 8) & 0xFF, eax & 0xFF))

    uc.hook_add(UC_HOOK_INTR, on_intr)
    err = None
    try:
        uc.emu_start(0x7C00, 0, count=200000)
    except UcError as e:
        err = e
    text = "".join(chr(al) for ah, al in outs if ah == 0x0E)
    ok = text == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:16} {len(code):>3}B  want={want!r} got={text!r}"
          + (f"  err={err}" if err else ""))

print(f"\nRESULT: {'PASS' if ok_all else 'FAIL'} ({len(CASES)} cases)")
sys.exit(0 if ok_all else 1)
