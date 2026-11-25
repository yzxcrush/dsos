"""compiler/verify_mcc4.py — ⑤ 第六圈：Ds 编译器生成 if 条件分支。"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
code = compile_source((HERE / "mcc4.ds").read_text(encoding="utf-8"))
print(f"mcc4.ds 编译: {len(code)} bytes")

CASES = [
    # if 命中
    ("let a = 5 if a < 10 { a = a + 1 } a = a + 0", 6),
    # if 不命中
    ("let a = 20 if a < 10 { a = a + 1 } a = a + 0", 20),
    # if + while 组合
    ("let i = 0 let s = 0 while i < 6 { if i < 3 { s = s + i } i = i + 1 } s = s + 0", 3),
    # 连续两个 if
    ("let a = 1 if a < 5 { a = a + 10 } if a < 20 { a = a + 100 } a = a + 0", 111),
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
        uc.emu_start(0x1000, 0, count=5000000)
    except UcError as e:
        err = e
    n = int.from_bytes(bytes(uc.mem_read(0x3008, 4)), "little")
    got = st.get("exit")
    ok = got == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {src[:48]!r:52} want={want:<4} got={got}  ({n}B)")
    if err:
        print(f"          stopped: {err}")

print("\nRESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
