"""compiler/verify_mcc2.py — ⑤ 第四圈：Ds 编译器发出完整指令序列（含变量）。

源码从 0x7000 读入（宿主导入），因此可以跑多个用例而不必重编译 mcc2.ds。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
SRC = (HERE / "mcc2.ds").read_text(encoding="utf-8")
code = compile_source(SRC)
print(f"mcc2.ds 编译: {len(code)} bytes")

CASES = [
    ("7 + 8", 15),
    ("let a = 5 a + 3", 8),
    ("let x = 10 x - 3", 7),
    ("let n = 6 n * 7", 42),
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
        uc.emu_start(0x1000, 0, count=3000000)
    except UcError as e:
        err = e
    n = int.from_bytes(bytes(uc.mem_read(0x3008, 4)), "little")
    gen = bytes(uc.mem_read(0x6000, min(n, 80)))
    got = st.get("exit")
    ok = got == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {src!r:26} want={want:<4} got={got}  gen={n}B {gen.hex(' ')[:70]}")
    if err:
        print(f"          stopped: {err}")

print("\nRESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
