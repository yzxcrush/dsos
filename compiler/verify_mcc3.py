"""compiler/verify_mcc3.py — ⑤ 第五圈：Ds 编译器生成控制流（while 回边 + 前向回填）。"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
code = compile_source((HERE / "mcc3.ds").read_text(encoding="utf-8"))
print(f"mcc3.ds 编译: {len(code)} bytes")

CASES = [
    ("let i = 0 let s = 0 while i < 5 { s = s + i i = i + 1 } s = s + 0", 10),
    ("let n = 3 let s = 1 while n < 6 { s = s * 2 n = n + 1 } s = s + 0", 8),
    ("let a = 0 while a < 3 { a = a + 7 } a = a + 0", 7),
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
    gen = bytes(uc.mem_read(0x6000, min(max(n, 0), 96)))
    got = st.get("exit")
    ok = got == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {src[:44]!r:48} want={want:<4} got={got}")
    print(f"          gen={n}B: {gen.hex(' ')}")
    if err:
        print(f"          stopped: {err}")

print("\nRESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
