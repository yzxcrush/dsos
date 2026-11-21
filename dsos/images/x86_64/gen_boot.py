#!/usr/bin/env python3
"""生成可直接 dd 到磁盘/写盘的 x86_64 裸机镜像。

路径：BIOS MBR -> 实模式加载 stage2 -> 保护模式 -> PAE/长模式 -> COM1 输出。
无 C、无汇编器、无链接器；全部字节由 Python 生成。
"""
from __future__ import annotations
import hashlib
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
STAGE2_ADDR = 0x8000
GDT_OFF = 0x400
GDTR_OFF = 0x428
LOAD_SECTORS = 8


class Asm:
    def __init__(self):
        self.b = bytearray()
        self.labels = {}
        self.fix = []

    def emit(self, data: bytes) -> int:
        p = len(self.b)
        self.b += data
        return p

    def label(self, name: str) -> None:
        self.labels[name] = len(self.b)

    def rel(self, op: bytes, label: str, n: int = 4) -> int:
        p = self.emit(op + b"\x00" * n)
        self.fix.append((p + len(op), label, n))
        return p

    def jmp(self, label: str) -> None:
        self.rel(b"\xe9", label)

    def jcc(self, cc: bytes, label: str) -> None:
        self.rel(b"\x0f" + cc, label)

    def call(self, label: str) -> None:
        self.rel(b"\xe8", label)

    def lea(self, label: str) -> None:
        self.rel(b"\x48\x8d\x35", label)

    def u16(self, v: int) -> bytes:
        return struct.pack("<H", v & 0xFFFF)

    def u32(self, v: int) -> bytes:
        return struct.pack("<I", v & 0xFFFFFFFF)


def stage2() -> bytes:
    a = Asm()
    # 16-bit entry
    a.emit(b"\xfa")                          # cli
    a.emit(b"\x31\xc0")                      # xor ax,ax
    a.emit(b"\x8e\xd8")                      # mov ds,ax
    a.emit(b"\x8e\xc0")                      # mov es,ax
    a.emit(b"\x8e\xd0")                      # mov ss,ax
    a.emit(b"\xbc\x00\x7c")                  # mov sp,0x7c00
    # A20 fast gate
    a.emit(b"\xe4\x92")                      # in al,0x92
    a.emit(b"\x0c\x02")                      # or al,2
    a.emit(b"\xe6\x92")                      # out 0x92,al
    # lgdt [0x8120]
    a.emit(b"\x0f\x01\x16" + a.u16(STAGE2_ADDR + GDTR_OFF))
    # 16-bit mode 下 lgdt 用 16 位地址（0x8428 可表示），不需要 disp32/patch
    # enter protected mode
    a.emit(b"\x0f\x20\xc0")                  # mov eax,cr0
    a.emit(b"\x0c\x01")                      # or al,1
    a.emit(b"\x0f\x22\xc0")                  # mov cr0,eax
    # far jump 0x08:pm32 (66 EA off32 sel16)
    pm32_off = len(a.b) + 8
    a.emit(b"\x66\xea" + a.u32(STAGE2_ADDR + pm32_off) + a.u16(0x08))
    # --- 32-bit protected mode ---
    assert len(a.b) == pm32_off, (len(a.b), pm32_off)
    a.emit(b"\x66\xb8\x10\x00")              # mov ax,0x10
    a.emit(b"\x8e\xd8")                      # mov ds,ax
    a.emit(b"\x8e\xc0")                      # mov es,ax
    a.emit(b"\x8e\xd0")                      # mov ss,ax
    a.emit(b"\xbc\x00\x00\x07\x00")          # mov esp,0x70000
    # zero page tables 0x9000..0xbfff
    a.emit(b"\x31\xc0")                      # xor eax,eax
    a.emit(b"\xbf\x00\x90\x00\x00")          # mov edi,0x9000
    a.emit(b"\xb9\x00\x0c\x00\x00")          # mov ecx,0xc00
    a.emit(b"\xf3\xab")                      # rep stosd
    # PML4[0]=0xa003
    a.emit(b"\xc7\x05" + a.u32(0x9000) + a.u32(0xa003))
    # PDPT[0]=0xb003
    a.emit(b"\xc7\x05" + a.u32(0xa000) + a.u32(0xb003))
    # PD[0]=0x83 (2MiB page)
    a.emit(b"\xc7\x05" + a.u32(0xb000) + a.u32(0x83))
    # CR3
    a.emit(b"\xb8" + a.u32(0x9000))          # mov eax,0x9000
    a.emit(b"\x0f\x22\xd8")                  # mov cr3,eax
    # CR4.PAE
    a.emit(b"\x0f\x20\xe0")                  # mov eax,cr4
    a.emit(b"\x0d" + a.u32(0x20))            # or eax,0x20
    a.emit(b"\x0f\x22\xe0")                  # mov cr4,eax
    # EFER.LME
    a.emit(b"\xb9" + a.u32(0xC0000080))      # mov ecx,0xc0000080
    a.emit(b"\x0f\x32")                      # rdmsr
    a.emit(b"\x0d" + a.u32(0x100))           # or eax,0x100
    a.emit(b"\x0f\x30")                      # wrmsr
    # CR0.PG|PE
    a.emit(b"\x0f\x20\xc0")                  # mov eax,cr0
    a.emit(b"\x0d" + a.u32(0x80000001))      # or eax,0x80000001
    a.emit(b"\x0f\x22\xc0")                  # mov cr0,eax
    # far jump 0x18:lm64 (32-bit EA)
    lm64_off = len(a.b) + 7
    a.emit(b"\xea" + a.u32(STAGE2_ADDR + lm64_off) + a.u16(0x18))
    # --- 64-bit long mode ---
    assert len(a.b) == lm64_off, (len(a.b), lm64_off)
    a.emit(b"\x66\xb8\x10\x00")              # mov ax,0x10
    a.emit(b"\x8e\xd8")                      # mov ds,ax
    a.emit(b"\x8e\xc0")                      # mov es,ax
    a.emit(b"\x8e\xd0")                      # mov ss,ax
    a.emit(b"\x48\xbc" + struct.pack("<Q", 0x70000))  # mov rsp,0x70000
    a.call("uart_init")
    a.lea("s_alive"); a.call("puts")
    a.emit(b"\x45\x31\xe4")                  # xor r12d,r12d
    a.emit(b"\x0f\x31\x48\xc1\xe2\x20\x48\x09\xd0\x49\x89\xc7")
    a.label("tick_loop")
    a.emit(b"\x0f\x31\x48\xc1\xe2\x20\x48\x09\xd0")
    a.emit(b"\x4c\x29\xf8")                  # sub rax,r15
    a.emit(b"\x48\x3d" + a.u32(1000000000))
    a.jcc(b"\x82", "tick_loop")               # jb
    a.emit(b"\x0f\x31\x48\xc1\xe2\x20\x48\x09\xd0\x49\x89\xc7")
    a.emit(b"\x49\xff\xc4")                  # inc r12
    a.lea("s_tick"); a.call("puts")
    a.emit(b"\x44\x89\xe7")                  # mov edi,r12d
    a.call("print_u32")
    a.lea("s_nl"); a.call("puts")
    a.jmp("tick_loop")
    # --- UART routines (64-bit) ---
    a.label("uart_init")
    for port, val in ((0x3f9,0),(0x3fb,0x80),(0x3f8,1),(0x3f9,0),(0x3fb,3),(0x3fa,0xC7)):
        a.emit(b"\x66\xba" + a.u16(port) + b"\xb0" + bytes([val]) + b"\xee")
    a.emit(b"\xc3")
    a.label("putc")
    a.emit(b"\x50\x66\xba\xfd\x03")
    a.label("putc_wait"); a.emit(b"\xec\xa8\x20"); a.jcc(b"\x84", "putc_wait")
    a.emit(b"\x66\xba\xf8\x03\x58\xee\xc3")
    a.label("puts")
    a.label("puts_loop"); a.emit(b"\xac\x84\xc0"); a.jcc(b"\x84", "puts_done")
    a.call("putc"); a.jmp("puts_loop"); a.label("puts_done"); a.emit(b"\xc3")
    a.label("print_u32")
    a.emit(b"\x89\xf8\x31\xd2\xb9\x0a\x00\x00\x00\x45\x31\xc9")
    a.label("pu_loop"); a.emit(b"\x31\xd2\xf7\xf1\x52\x49\xff\xc1\x85\xc0"); a.jcc(b"\x85", "pu_loop")
    a.label("pu_pop"); a.emit(b"\x5a\x80\xc2\x30\x88\xd0"); a.call("putc")
    a.emit(b"\x49\xff\xc9"); a.jcc(b"\x85", "pu_pop"); a.emit(b"\xc3")
    for name, text in (("s_alive", b"DsOS alive\r\n"), ("s_tick", b"tick: "), ("s_nl", b"\r\n")):
        a.label(name); a.emit(text + b"\x00")
    # GDT at GDT_OFF
    assert len(a.b) <= GDT_OFF, len(a.b)
    a.b += b"\x00" * (GDT_OFF - len(a.b))
    gdt = [
        0x0000000000000000,
        0x00CF9A000000FFFF,  # 32-bit code
        0x00CF92000000FFFF,  # data
        0x00AF9A000000FFFF,  # 64-bit code
        0x00AF92000000FFFF,  # 64-bit data
    ]
    for g in gdt:
        a.b += struct.pack("<Q", g)
    assert len(a.b) == GDTR_OFF
    a.b += struct.pack("<HI", 5 * 8 - 1, STAGE2_ADDR + GDT_OFF)
    for at, label, n in a.fix:
        target = a.labels[label]
        a.b[at:at + n] = struct.pack("<i" if n == 4 else "<h", target - (at + n))
    return bytes(a.b)


def boot_sector() -> bytes:
    b = bytearray()
    b += b"\xfa"                       # cli
    b += b"\x31\xc0"                   # xor ax,ax
    b += b"\x8e\xd8"                   # mov ds,ax
    b += b"\x8e\xc0"                   # mov es,ax
    b += b"\x8e\xd0"                   # mov ss,ax
    b += b"\xbc\x00\x7c"               # mov sp,0x7c00
    b += b"\xfb"                       # sti
    b += b"\x88\x16\xf0\x7d"           # mov [0x7df0],dl
    b += b"\xb8\x08\x02"               # mov ax,0x0208 (read 8 sectors)
    b += b"\xb9\x02\x00"               # mov cx,0x0002 (cyl0, sector2)
    b += b"\xba\x00\x00"               # mov dx,0x0000
    b += b"\x8a\x16\xf0\x7d"           # mov dl,[0x7df0]
    b += b"\xbb\x00\x80"               # mov bx,0x8000
    b += b"\xcd\x13"                   # int 13h
    b += b"\x72\x05"                   # jc fail (+5, skip far jmp)
    b += b"\xea\x00\x80\x00\x00"       # jmp 0x0000:0x8000
    b += b"\xf4\xeb\xfd"               # fail: hlt; jmp fail
    assert len(b) <= 510
    b += b"\x00" * (510 - len(b)) + b"\x55\xaa"
    return bytes(b)


def simple_bios_sector() -> bytes:
    """512B 兜底：BIOS 引导扇区，直接 COM1 输出，不依赖 stage2。"""
    msg = b"DsOS booted.\r\n\x00"
    b = bytearray()
    b += b"\xba\xf8\x03"              # mov dx,0x3f8
    b += b"\xbe" + struct.pack("<H", 0x7C00 + 17)
    b += b"\xac"                        # lodsb
    b += b"\x84\xc0"                    # test al,al
    b += b"\x74\x03"                    # jz +3
    b += b"\xee"                        # out dx,al
    b += b"\xeb\xf8"                    # jmp -8
    b += b"\xf4\xeb\xfd"                # hlt; jmp
    assert len(b) == 17, len(b)
    b += msg
    b += b"\x00" * (510 - len(b)) + b"\x55\xaa"
    return bytes(b)


def main() -> None:
    st2 = stage2()
    assert len(st2) <= LOAD_SECTORS * 512, len(st2)
    st2_padded = st2 + b"\x00" * (LOAD_SECTORS * 512 - len(st2))
    img = boot_sector() + st2_padded
    # 1.44 MiB raw image，便于 dd / QEMU
    img += b"\x00" * (1440 * 1024 - len(img))
    out = HERE / "dsos-x86_64.img"
    out.write_bytes(img)
    bios = simple_bios_sector()
    (HERE / "dsos-bios.img").write_bytes(bios)
    print(f"✓ {out} ({len(img)} bytes)")
    print("sha256:", hashlib.sha256(img).hexdigest())
    print("boot signature:", img[510:512].hex())
    print("stage2 bytes:", len(st2))
    print("bios sha256:", hashlib.sha256(bios).hexdigest())


if __name__ == "__main__":
    main()
