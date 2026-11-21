"""compiler/verify_io.py — 端口 IO 内建（out8/in8/cli/hlt）的验收

out8 应触发 OUT 到指定端口；in8 应从宿主读到值。这两个是内核跟硬件打交道的唯一途径。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = """
fn _start() {
    out8(0x3F8, 65)
    let x = in8(0x60)
    sys_exit(x)
}
"""

code = compile_source(SRC)
print(f"compiled: {len(code)} bytes")

uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0, 0x10000)
uc.mem_write(0x1000, code)
uc.reg_write(UC_X86_REG_RSP, 0x8000)
uc.reg_write(UC_X86_REG_RBP, 0x8000)

outs = []
state = {}


def on_out(uc, *args):
    port, size, value = args[0], args[1], args[2]
    outs.append((port, value))


def on_in(uc, *args):
    port = args[0]
    return 42 if port == 0x60 else 0


def on_syscall(uc, ud):
    if uc.reg_read(UC_X86_REG_RAX) == 60:
        state["exit"] = uc.reg_read(UC_X86_REG_RDI)
        uc.emu_stop()


uc.hook_add(UC_HOOK_INSN, on_out, None, 1, 0, UC_X86_INS_OUT)
uc.hook_add(UC_HOOK_INSN, on_in, None, 1, 0, UC_X86_INS_IN)
uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
try:
    uc.emu_start(0x1000, 0, count=100000)
except UcError as e:
    print("stop:", e)

print(f"OUTs: {[(hex(p), v) for p, v in outs]}")
print(f"exit: {state.get('exit')} (expect 42)")
ok_out = (0x3F8, 65) in outs
ok_in = state.get("exit") == 42
print(f"[io] out8 wrote 0x3F8=65: {'PASS' if ok_out else 'FAIL'}")
print(f"[io] in8 read back 42:    {'PASS' if ok_in else 'FAIL'}")
print("RESULT:", "PASS" if (ok_out and ok_in) else "FAIL")
sys.exit(0 if (ok_out and ok_in) else 1)
