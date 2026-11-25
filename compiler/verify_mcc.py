"""compiler/verify_mcc.py — ⑤ 第三圈验收：Ds 写的编译器产出机器码并执行。

mcc.ds 把 "2+3*4" 常量折叠成 14，写出 `mov eax,14; ret`，再用 run(buf) 执行。
这是"Ds 编译器真产出机器码"的第一个完整闭环。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = pathlib.Path(__file__).resolve().with_name("mcc.ds").read_text(encoding="utf-8")

code = compile_source(SRC)
print(f"mcc.ds 编译: {len(code)} bytes")

uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0, 0x10000)
uc.mem_write(0x1000, code)
uc.reg_write(UC_X86_REG_RSP, 0x8000)
uc.reg_write(UC_X86_REG_RBP, 0x8000)
state = {}


def on_syscall(uc, ud):
    if uc.reg_read(UC_X86_REG_RAX) == 60:
        state["exit"] = uc.reg_read(UC_X86_REG_RDI)
        uc.emu_stop()


uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
try:
    uc.emu_start(0x1000, 0, count=2000000)
except UcError as e:
    print("stop:", e)

generated = bytes(uc.mem_read(0x6000, 6))
print(f"生成的机器码: {generated.hex(' ')}")
got = state.get("exit")
print(f"执行生成代码的结果 = {got}  (expect 14)")
ok = got == 14 and generated[:1] == b"\xb8" and generated[5:] == b"\xc3"
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
