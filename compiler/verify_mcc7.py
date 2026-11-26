"""compiler/verify_mcc7.py — ⑤ 第九圈：全部比较运算符 + else。"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
code = compile_source((HERE / "mcc7.ds").read_text(encoding="utf-8"))
print(f"mcc7.ds 编译: {len(code)} bytes")

CASES = [
    # >=
    ("let a = 5 if a >= 5 { a = a + 1 } a = a + 0", 6),
    # > 命中
    ("let a = 9 if a > 5 { a = 10 } else { a = 20 } a = a + 0", 10),
    # > 不命中 -> else
    ("let a = 1 if a > 5 { a = 10 } else { a = 20 } a = a + 0", 20),
    # != 循环
    ("let i = 0 while i != 4 { i = i + 1 } i = i + 0", 4),
    # == 命中
    ("let a = 3 if a == 3 { a = 42 } a = a + 0", 42),
    # <= 循环
    ("let i = 0 let s = 0 while i <= 3 { s = s + i  i = i + 1 } s = s + 0", 6),
    # 嵌套 if/else
    ("let a = 7 if a < 5 { a = 1 } else { if a < 10 { a = 2 } else { a = 3 } } a = a + 0", 2),
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
    print(f"  [{'PASS' if ok else 'FAIL'}] {src[:52]!r:56} want={want:<4} got={got}  ({n}B)")
    if err:
        print(f"          stopped: {err}")

print("\nRESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
