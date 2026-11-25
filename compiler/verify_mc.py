"""compiler/verify_mc.py — ⑤ 第一圈验收：用 mini.py 编译 Ds 写的表达式求值器，验证结果。

mc.ds 是递归下降求值器（lexer+parser 雏形）。这是自举前的关键压力测试：
如果 mini.py 能编译并正确运行它，说明后端已能承载"编译器级"代码。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = pathlib.Path(__file__).resolve().with_name("mc.ds").read_text(encoding="utf-8")

code = compile_source(SRC)
print(f"mc.ds 编译: {len(code)} bytes")

BASE = 0x1000
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0, 0x10000)
uc.mem_write(BASE, code)
uc.reg_write(UC_X86_REG_RSP, 0x8000)
uc.reg_write(UC_X86_REG_RBP, 0x8000)

state = {}


def on_syscall(uc, ud):
    if uc.reg_read(UC_X86_REG_RAX) == 60:
        state["exit"] = uc.reg_read(UC_X86_REG_RDI)
        uc.emu_stop()


uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
try:
    uc.emu_start(BASE, 0, count=2000000)
except UcError as e:
    print("stop:", e)

got = state.get("exit")
print(f"2+3*4 = {got}  (expect 14)")
print("RESULT:", "PASS" if got == 14 else "FAIL")
sys.exit(0 if got == 14 else 1)
