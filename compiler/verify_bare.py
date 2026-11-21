"""compiler/verify_bare.py — 阶段③ 闭环：alive.ds → 裸机机器码 → 真写 VGA + 停机

不经过任何 syscall：直接写 0xB8000，然后 cli;hlt。
这是第一段"由 Ds 源码编译产生、会进入镜像"的字节。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = """
fn _start() {
    p("DsOS alive")
    halt()
}
"""

code = compile_source(SRC, target="bare")
print(f"compiled: {len(code)} bytes")
print(f"hex: {code.hex(' ')}")

BASE = 0x9000                      # 与冻结 stage2 的跳转目标一致
uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0, 0x200000)
uc.mem_write(BASE, code)
uc.reg_write(UC_X86_REG_RSP, 0x70000)
uc.reg_write(UC_X86_REG_RBP, 0x70000)

err = None
try:
    uc.emu_start(BASE, 0, count=10000)
except UcError as e:
    err = e
print(f"stop: {err}")

N = len("DsOS alive") * 2   # 只看实际写入的那些单元
raw = bytes(uc.mem_read(0xB8000, N))
text = "".join(chr(raw[i]) if 32 <= raw[i] < 127 else " " for i in range(0, N, 2))
attrs = {raw[i + 1] for i in range(0, N, 2)}
print(f"VGA text : {text!r}")
print(f"VGA attrs: {sorted(hex(a) for a in attrs)}")

ok_text = text == "DsOS alive"
ok_attr = attrs == {0x0F}
print(f"[bare] VGA contains 'DsOS alive': {'PASS' if ok_text else 'FAIL'}")
print(f"[bare] attributes are 0x0F:       {'PASS' if ok_attr else 'FAIL'}")
print("RESULT:", "PASS" if (ok_text and ok_attr) else "FAIL")
sys.exit(0 if (ok_text and ok_attr) else 1)
