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

    ("p(\"hi\") 字符串", """
fn _start() {
    p("DsOS alive")
    sys_exit(0)
}
""", 0, b"DsOS alive"),

    ("as 截断 u8", """
fn _start() {
    let x = 300
    let y = x as u8
    sys_exit(y)
}
""", 44),

    ("窄 store8/load8", """
fn _start() {
    store8(12288, 65)
    let x = load8(12288)
    sys_exit(x)
}
""", 65),

    ("数组字面量 + 下标", """
fn _start() {
    let a = [10, 20, 30]
    sys_exit(a[1])
}
""", 20),

    ("字符串值（非空地址）", """
fn _start() {
    let s = "Hi"
    if s != 0 { sys_exit(1) } else { sys_exit(0) }
}
""", 1),

    ("match 字面量命中", """
fn _start() {
    let x = 3
    let r = match x { 0 => 100, 3 => 42, _ => 7 }
    sys_exit(r)
}
""", 42),

    ("match 通配兜底", """
fn _start() {
    let x = 9
    let r = match x { 0 => 100, 3 => 42, _ => 7 }
    sys_exit(r)
}
""", 7),

    ("位运算 & | ^ << >> ~", """
fn _start() {
    let a = 1 & 3
    let b = a | 4
    let c = b ^ 1
    let d = c << 2
    let e = d >> 1
    let f = ~1 & 15
    sys_exit(a + b + c + d + e + f)
}
""", 48),

    ("结构体字段读写", """
type P { x: i32, y: i32 }
fn _start() {
    let p: P
    p.x = 7
    p.y = 35
    sys_exit(p.x + p.y)
}
""", 42),

    ("用户函数调用", """
fn add(a: i32, b: i32) -> i32 {
    return a + b
}
fn _start() {
    let x = add(20, 22)
    sys_exit(x)
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

    out = bytearray()

    def on_syscall(uc, ud):
        nonlocal out
        rax = uc.reg_read(UC_X86_REG_RAX)
        if rax == 60:
            st["exit"] = uc.reg_read(UC_X86_REG_RDI)
            uc.emu_stop()
        elif rax == 1:
            buf = uc.reg_read(UC_X86_REG_RSI)
            n = uc.reg_read(UC_X86_REG_RDX)
            out += bytes(uc.mem_read(buf, n))
            uc.reg_write(UC_X86_REG_RAX, n)

    uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
    try:
        uc.emu_start(BASE, 0, count=500000)
    except UcError as e:
        return None, f"{len(code)}B, {e}"
    return st.get("exit"), f"{len(code)}B", bytes(out)


ok_all = True
for case in CASES:
    name, src, want = case[0], case[1], case[2]
    want_out = case[3] if len(case) > 3 else b""
    got, info, out = run_one(src)
    ok = (got == want) and (out == want_out)
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:18} want={want:<4} got={got}"
          f"{'  out=' + repr(out) if want_out else ''}  ({info})")

print(f"\nRESULT: {'PASS' if ok_all else 'FAIL'}  ({len(CASES)} cases)")
sys.exit(0 if ok_all else 1)
