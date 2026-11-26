"""dsos-os/ds/verify_dsos.py — 验证「全 Ds 源码编译出的内核」在裸机下真的运行。

不碰 U 盘、不碰 Python 生成的机器码：
  kernel.ds --(Ds 工具链)--> 裸机 x86-64 --(unicorn 执行)--> 断言屏幕内容
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = (HERE / "kernel.ds").read_text(encoding="utf-8")
code = compile_source(SRC, target="bare")
print(f"kernel.ds 编译: {len(code)} 字节（内核区上限 4096）")
if len(code) > 4096:
    print("FAIL: 超出 4096 字节内核区")
    sys.exit(1)

BASE = 0x9000
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0, 0x200000)
uc.mem_write(BASE, code)
uc.reg_write(UC_X86_REG_RSP, 0x70000)
uc.reg_write(UC_X86_REG_RBP, 0x70000)

# 模拟键盘：端口 0x64 报告"有数据"，端口 0x60 依次给出 1E / 20 / 01(ESC)
keys = [0x1E, 0x20, 0x01]
state = {"i": 0, "halted": False}


def on_in(uc, *args):
    port = args[0]
    if port == 0x64:
        return 1 if state["i"] < len(keys) else 0
    if port == 0x60:
        if state["i"] < len(keys):
            v = keys[state["i"]]
            state["i"] += 1
            return v
        return 0
    return 0


uc.hook_add(UC_HOOK_INSN, on_in, None, 1, 0, UC_X86_INS_IN)
# halt() 编成 cli;hlt;jmp $ —— 找到它的位置，用 RIP 判定是否停在那里
HALT_SEQ = bytes([0xFA, 0xF4, 0xEB, 0xFE])
halt_off = code.find(HALT_SEQ)

err = None
try:
    uc.emu_start(BASE, 0, count=2000000)
except UcError as e:
    err = e
rip_off = uc.reg_read(UC_X86_REG_RIP) - BASE
if halt_off >= 0 and halt_off <= rip_off <= halt_off + 4:
    state["halted"] = True
print(f"halt_seq @ {halt_off}, final rip off = {rip_off}")

raw = bytes(uc.mem_read(0xB8000, 80 * 25 * 2))
lines = []
for r in range(25):
    row = "".join(chr(raw[(r * 80 + c) * 2]) if 32 <= raw[(r * 80 + c) * 2] < 127 else " "
                  for c in range(80)).rstrip()
    if row:
        lines.append(row)

print("屏幕内容:")
for ln in lines:
    print(f"  | {ln}")
print(f"halted={state['halted']} err={err} keys_consumed={state['i']}")

ok_banner = any("DsOS v0.6" in ln for ln in lines) and any("Ds toolchain" in ln for ln in lines)
ok_echo = any("1e" in ln for ln in lines) and any("20" in ln for ln in lines)
ok_halt = state["halted"]

print(f"[dsos] 横幅由 Ds 编译的内核打印: {'PASS' if ok_banner else 'FAIL'}")
print(f"[dsos] 键盘扫描码回显 1e/20:     {'PASS' if ok_echo else 'FAIL'}")
print(f"[dsos] ESC 触发停机:              {'PASS' if ok_halt else 'FAIL'}")
ok = ok_banner and ok_echo and ok_halt
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
