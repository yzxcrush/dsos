"""compiler/verify_jit.py — ⑤ 第二圈最小增量：运行时生成机器码并执行。

Ds 程序用 store8 把 `mov eax,42; ret` 写进缓冲区，run(buf) 跳过去执行，
返回值应留在 rax。这是自举的基石：编译器运行时生成代码 → 执行它。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = """
fn _start() {
    let buf = 24576
    store8(buf, 184)       // 0xB8 mov eax, imm32
    store8(buf + 1, 42)    // 0x2A
    store8(buf + 2, 0)
    store8(buf + 3, 0)
    store8(buf + 4, 0)
    store8(buf + 5, 195)   // 0xC3 ret
    let x = run(buf)
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
state = {}


def on_syscall(uc, ud):
    if uc.reg_read(UC_X86_REG_RAX) == 60:
        state["exit"] = uc.reg_read(UC_X86_REG_RDI)
        uc.emu_stop()


uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
try:
    uc.emu_start(0x1000, 0, count=200000)
except UcError as e:
    print("stop:", e)

got = state.get("exit")
print(f"run(buf) 返回 = {got}  (expect 42)")
print("RESULT:", "PASS" if got == 42 else "FAIL")
sys.exit(0 if got == 42 else 1)
