"""dsos-os/ds/verify_mbr.py — 验证「用 Ds 写的 MBR」真的能引导

流程：
  mbr.ds --(mini16)--> 16 位机器码（≤510 字节，末尾补 0x55AA）
  → 在 unicorn 16 位模式从 0x7C00 执行
  → 钩住 int 13h，按 DAP 参数把镜像内容"喂"给它
  → 断言：读请求正确、数据落到 0x8000、远跳到 stage2
"""
import pathlib, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from unicorn import *
from unicorn.x86_const import *
from mini16 import compile_source

SRC = (HERE / "mbr.ds").read_text(encoding="utf-8")
code = compile_source(SRC)
print(f"mbr.ds 编译: {len(code)} 字节（MBR 上限 510）")
if len(code) > 510:
    print("FAIL: 超出 510 字节")
    sys.exit(1)

# 造一个"磁盘"：LBA 0 = MBR，LBA 1..32 = stage2 区（用递增字节填充，便于比对）
IMG = bytearray(33 * 512)
IMG[0:512] = code + b"\x00" * (510 - len(code))
IMG[510:512] = b"\x55\xAA"
for i in range(512, len(IMG)):
    IMG[i] = (i * 7) & 0xFF

uc = Uc(UC_ARCH_X86, UC_MODE_16)
uc.mem_map(0, 0x100000)
uc.mem_write(0x7C00, bytes(IMG[0:512]))
uc.reg_write(UC_X86_REG_CS, 0)
uc.reg_write(UC_X86_REG_IP, 0x7C00)
uc.reg_write(UC_X86_REG_DL, 0x80)

reads = []
reached = {"stage2": False}


def on_intr(uc, intno, ud):
    if intno != 0x13:
        return
    eax = uc.reg_read(UC_X86_REG_EAX)
    ah = (eax >> 8) & 0xFF
    if ah == 0x02:                        # CHS 读
        al = eax & 0xFF
        cx = uc.reg_read(UC_X86_REG_ECX) & 0xFFFF
        dx = uc.reg_read(UC_X86_REG_EDX) & 0xFFFF
        cyl, sec = (cx >> 8) & 0xFF, cx & 0x3F
        head = (dx >> 8) & 0xFF
        lba = ((cyl * 255) + head) * 63 + (sec - 1)
        es = uc.reg_read(UC_X86_REG_ES) & 0xFFFF
        bx = uc.reg_read(UC_X86_REG_EBX) & 0xFFFF
        reads.append((lba, al, es, bx))
        buf = (es << 4) + bx
        uc.mem_write(buf, bytes(IMG[lba * 512: lba * 512 + al * 512]))
        uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) & ~1)
        return
    if ah == 0x42:                        # 扩展读
        si = uc.reg_read(UC_X86_REG_ESI) & 0xFFFF
        dap = bytes(uc.mem_read(si, 16))
        cnt = struct.unpack("<H", dap[2:4])[0]
        off = struct.unpack("<H", dap[4:6])[0]
        seg = struct.unpack("<H", dap[6:8])[0]
        lba = struct.unpack("<I", dap[8:12])[0]
        reads.append((lba, cnt, seg, off))
        buf = (seg << 4) + off
        data = bytes(IMG[lba * 512: lba * 512 + cnt * 512])
        uc.mem_write(buf, data)
        eflags = uc.reg_read(UC_X86_REG_EFLAGS) & ~1
        uc.reg_write(UC_X86_REG_EFLAGS, eflags)
        return
    reads.append((f"AH={ah:#x}",))


def on_code(uc, addr, size, ud):
    if addr == 0x8000:
        reached["stage2"] = True
        uc.emu_stop()


uc.hook_add(UC_HOOK_INTR, on_intr)
uc.hook_add(UC_HOOK_CODE, on_code)

err = None
try:
    uc.emu_start(0x7C00, 0, count=200000)
except UcError as e:
    err = e

print(f"int13h 请求: {reads}")
print(f"err={err}")
ok_read = any(r == (1, 32, 0x0800, 0) for r in reads if isinstance(r[0], int))
ok_mem = bytes(uc.mem_read(0x8000, 512)) == bytes(IMG[512:1024])
print(f"[mbr] 读请求正确 (LBA1 × 32 → 0x8000): {'PASS' if ok_read else 'FAIL'}")
print(f"[mbr] stage2 数据已落内存:            {'PASS' if ok_mem else 'FAIL'}")
print(f"[mbr] 远跳到 stage2 (0x8000):         {'PASS' if reached['stage2'] else 'FAIL'}")
sig_ok = bytes(IMG[510:512]) == bytes([0x55, 0xAA])
print(f"[mbr] MBR 末尾有 0x55AA:              {'PASS' if sig_ok else 'FAIL'}")
ok = ok_read and ok_mem and reached["stage2"]
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
