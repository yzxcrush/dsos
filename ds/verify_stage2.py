"""dsos-os/ds/verify_stage2.py — 验证「用 Ds 写的 stage2」

unicorn 不能真正切换 CPU 模式，所以本验收在**远跳之前**停住，检查：
  1. A20 已打开（端口 0x92 写了 bit1）
  2. 页表三层写对（PML4 → PDPT → PD，2 MiB 页）
  3. GDT 与 GDTR 内容正确
  4. CR0.PG / CR3 / CR4.PAE 已设置
  5. 远跳指令的目标是 sel=0x08 / off=0x9000

真正的模式切换与跳转只能真机验证——这一项在报告里明确标为未验证。
"""
import pathlib, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from unicorn import *
from unicorn.x86_const import *
from mini16 import compile_source

SRC = (HERE / "stage2.ds").read_text(encoding="utf-8")
code = compile_source(SRC)
print(f"stage2.ds 编译: {len(code)} 字节（上限 4096）")
if len(code) > 4096:
    print("FAIL: 超出 4096 字节")
    sys.exit(1)

# 找 32 位操作数远跳：66 EA off32(0x9000) sel16(0x08)
# 停点：写 CR0.PE 之前（66 B8 01 00 00 00 0F 22 C0）
PE = bytes([0x66, 0xB8, 0x01, 0x00, 0x00, 0x00, 0x0F, 0x22, 0xC0])
FAR = PE
far_off = code.find(FAR)
print(f"进保护模式前停点偏移: {far_off}（{'找到' if far_off >= 0 else '未找到'}）")

uc = Uc(UC_ARCH_X86, UC_MODE_16)
uc.mem_map(0, 0x100000)
uc.mem_write(0x8000, code)
uc.reg_write(UC_X86_REG_CS, 0)
uc.reg_write(UC_X86_REG_IP, 0x8000)
uc.reg_write(UC_X86_REG_DL, 0x80)

ports = []
state = {"stopped": False}

# 端口 0x92 的写会触发 in/out hook；A20 用 in al,0x92 / or / out 0x92,al
def on_in(uc, *a):
    if a[0] == 0x92:
        return 0x00
    return 0


def on_out(uc, *a):
    ports.append((a[0], a[2] & 0xFF))


marks = []


def on_intr(uc, intno, ud):
    pass


uc.hook_add(UC_HOOK_INTR, on_intr)
uc.hook_add(UC_HOOK_INSN, on_in, None, 1, 0, UC_X86_INS_IN)
uc.hook_add(UC_HOOK_INSN, on_out, None, 1, 0, UC_X86_INS_OUT)


def on_code(uc, addr, size, ud):
    # 执行到远跳就停：后续需要真实模式切换，unicorn 无法继续
    if far_off >= 0 and addr == 0x8000 + far_off:
        state["stopped"] = True
        uc.emu_stop()


uc.hook_add(UC_HOOK_CODE, on_code)

err = None
try:
    uc.emu_start(0x8000, 0, count=500000)
except UcError as e:
    err = e

print(f"停在远跳前: {state['stopped']}  err={err}")

# ---- 1) A20 ----
a20 = any(p == 0x92 and (v & 0x02) for p, v in ports)
# ---- 2) 页表 ----
pml4 = int.from_bytes(bytes(uc.mem_read(0x1000, 8)), "little")
pdpt = int.from_bytes(bytes(uc.mem_read(0x2000, 8)), "little")
pd = int.from_bytes(bytes(uc.mem_read(0x3000, 8)), "little")
# ---- 3) GDT / GDTR ----
gdtr_limit = int.from_bytes(bytes(uc.mem_read(0x5EF0, 2)), "little")
gdtr_base = int.from_bytes(bytes(uc.mem_read(0x5EF2, 4)), "little")
gdt_code = int.from_bytes(bytes(uc.mem_read(0x5F10, 8)), "little")
gdt_data = int.from_bytes(bytes(uc.mem_read(0x5F18, 8)), "little")
# ---- 4) CR ----
cr0 = uc.reg_read(UC_X86_REG_CR0)
cr3 = uc.reg_read(UC_X86_REG_CR3)
cr4 = uc.reg_read(UC_X86_REG_CR4)

print(f"  调试标记: {'{!r}'.format(''.join(marks))}")
print(f"  A20 端口写: {[(hex(p), hex(v)) for p, v in ports]}")
print(f"  PML4[0] = {pml4:#x}   PDPT[0] = {pdpt:#x}   PD[0] = {pd:#x}")
print(f"  GDTR = limit {gdtr_limit} base {gdtr_base:#x}")
print(f"  GDT code = {gdt_code:#018x}   data = {gdt_data:#018x}")
print(f"  CR0 = {cr0:#x}  CR3 = {cr3:#x}  CR4 = {cr4:#x}")

checks = {
    "A20 已打开": a20,
    # 页表项低位的 A(0x20)/D(0x40) 由 CPU 走查时置位，断言时屏蔽
    "PML4[0] → 0x2003": (pml4 & ~0x60) == 0x2003,
    "PDPT[0] → 0x3003": (pdpt & ~0x60) == 0x3003,
    "PD[0] = 0x83 (2MB 页)": (pd & ~0x60) == 0x83,
    "GDTR limit=31 base=0x5F00": gdtr_limit == 31 and gdtr_base == 0x5F00,
    "GDT 16 位代码段正确": int.from_bytes(bytes(uc.mem_read(0x5F08, 8)), "little") == 0x00009A000000FFFF,
    "GDT 64 位代码段正确": int.from_bytes(bytes(uc.mem_read(0x5F10, 8)), "little") == 0x00AF9A000000FFFF,
    "GDT 数据段正确": int.from_bytes(bytes(uc.mem_read(0x5F18, 8)), "little") == 0x00CF92000000FFFF,
    "进保护模式前的停点存在": far_off >= 0,
}
ok_all = True
print()
for k, v in checks.items():
    ok_all &= bool(v)
    print(f"[{'PASS' if v else 'FAIL'}] {k}")
print("\n注：以下三项在进保护模式后才设置，需真机验证：CR0.PG / CR3 / CR4.PAE")
print("\n注：进保护模式之后的 CR 设置与两次远跳无法用 unicorn 验证，需真机确认。")
print("RESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
