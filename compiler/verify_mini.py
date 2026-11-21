"""compiler/verify_mini.py — 最小后端的验收（unicorn 执行，sys_exit 码即结果）

每个用例：Ds 源码 → mini.py 编译 → unicorn 跑 → 断言 SYS_exit 的退出码。
"""
import sys, os, pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

CASES = [
    ("while 求和 0..9", """
fn _start() {
    let i = 0
    let s = 0
    while i < 10 { s = s + i
        i = i + 1 }
    sys_exit(s)
}
""", 45),

    ("while 递减", """
fn _start() {
    let n = 10
    let s = 100
    while n > 0 { s = s - n
        n = n - 1 }
    sys_exit(s)
}
""", 45),

    ("if / else 分支", """
fn _start() {
    let x = 7
    let r = 0
    if x > 5 { r = 42 } else { r = 1 }
    sys_exit(r)
}
""", 42),

    ("v[i] 写后读回", """
fn _start() {
    let p = 12288
    p[0] = 7
    p[1] = 35
    sys_exit(p[0] + p[1])
}
""", 42),

    ("嵌套二元运算", """
fn _start() {
    let a = 3
    let b = 4
    let c = 0
    c = a * b + a - b
    sys_exit(c)
}
""", 11),
]


def run_one(src):
    code = compile_source(src)
    BASE = 0x1000
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x10000)
    uc.mem_write(BASE, code)
    uc.reg_write(UC_X86_REG_RSP, 0x8000)
    uc.reg_write(UC_X86_REG_RBP, 0x8000)
    st = {}

    def on_syscall(uc, ud):
        if uc.reg_read(UC_X86_REG_RAX) == 60:
            st["exit"] = uc.reg_read(UC_X86_REG_RDI)
            uc.emu_stop()

    uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
    try:
        uc.emu_start(BASE, 0, count=500000)
    except UcError as e:
        return None, f"{len(code)}B, {e}"
    return st.get("exit"), f"{len(code)}B"


ok_all = True
for name, src, want in CASES:
    got, info = run_one(src)
    ok = got == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:18} want={want:<4} got={got}  ({info})")

print(f"\nRESULT: {'PASS' if ok_all else 'FAIL'}  ({len(CASES)} cases)")
sys.exit(0 if ok_all else 1)
