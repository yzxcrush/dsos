"""compiler/verify_mcc6.py — ⑤ 第八圈：Ds 编译器生成函数定义与调用（含前向回填）。"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
code = compile_source((HERE / "mcc6.ds").read_text(encoding="utf-8"))
print(f"mcc6.ds 编译: {len(code)} bytes")

CASES = [
    # 双参数函数（定义在前）
    ("fn add(a, b) { a = a + b } let r = 0 r = add(20, 22) r = r + 0", 42),
    # 单参数函数
    ("fn twice(x) { x = x * 2 } let r = 0 r = twice(21) r = r + 0", 42),
    # 前向调用：函数定义在使用之后
    ("let z = 0 z = later(5) z = z + 0 fn later(x) { x = x * 9 }", 45),
    # 函数 + 循环
    ("fn sumto(k) { let t = 0 let i = 0 while i < k { t = t + i i = i + 1 } t = t + 0 } let r = 0 r = sumto(6) r = r + 0", 15),
]

ok_all = True
for src, want in CASES:
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x10000)
    uc.mem_write(0x1000, code)
    uc.mem_write(0x7000, src.encode() + b"\x00")
    uc.reg_write(UC_X86_REG_RSP, 0x8000)
    uc.reg_write(UC_X86_REG_RBP, 0x8000)
    st = {}

    def on_syscall(u, ud):
        if u.reg_read(UC_X86_REG_RAX) == 60:
            st["exit"] = u.reg_read(UC_X86_REG_RDI)
            u.emu_stop()

    uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
    err = None
    try:
        uc.emu_start(0x1000, 0, count=12000000)
    except UcError as e:
        err = e
    n = int.from_bytes(bytes(uc.mem_read(0x3008, 4)), "little")
    got = st.get("exit")
    ok = got == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {src[:56]!r:60} want={want:<4} got={got}  ({n}B)")
    if err:
        print(f"          stopped: {err}")

print("\nRESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
