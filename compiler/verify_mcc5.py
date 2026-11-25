"""compiler/verify_mcc5.py — ⑤ 第七圈：完整词法（多字符标识符 + 关键字哈希）。"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
code = compile_source((HERE / "mcc5.ds").read_text(encoding="utf-8"))
print(f"mcc5.ds 编译: {len(code)} bytes")

CASES = [
    # 多字符变量 + while
    ("let count = 0 while count < 5 { count = count + 1 } count = count + 0", 5),
    # 多字符变量 + if
    ("let total = 7 if total < 10 { total = total + 3 } total = total + 0", 10),
    # 多字符标识符混合 + 乘法
    ("let alpha = 6 let beta = 7 alpha = alpha * beta alpha = alpha + 0", 42),
    # 三个变量 + 循环累加
    ("let idx = 0 let acc = 0 while idx < 4 { acc = acc + idx idx = idx + 1 } acc = acc + 0", 6),
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
        uc.emu_start(0x1000, 0, count=8000000)
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
