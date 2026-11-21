#!/usr/bin/env python3
"""生成可直接 dd 到磁盘/写盘的 x86_64 裸机镜像。

路径：BIOS MBR -> 实模式加载 stage2 -> 保护模式 -> PAE/长模式 -> COM1 输出。
无 C、无汇编器、无链接器；全部字节由 Python 生成。
"""
from __future__ import annotations
import hashlib
import pathlib
import sys
import struct

HERE = pathlib.Path(__file__).resolve().parent
STAGE2_ADDR = 0x8000
KERNEL_ENTRY = 0x9000
KERNEL_SECTORS = 8
GDT_OFF = 0x400
GDTR_OFF = 0x428
LOAD_SECTORS = 16


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


def vga_putc() -> bytes:
    """64-bit VGA text-mode putc: writes AL to 0xB8000 with attr 0x0F.

    Cursor state: dword [0x7F00] = row base byte offset (multiple of 160),
                  dword [0x7F04] = column byte offset (0..158).
    '\\r' -> next row, col 0 (wrap at 80x25); '\\n' -> ignored (we always emit "\\r\\n").
    Preserves RAX/RBX/RCX/RDX/R8 so the caller still has AL.
    """
    b = bytearray()
    b += b"\x50\x53\x51\x52\x41\x50"                     # push rax,rbx,rcx,rdx,r8
    b += b"\x48\xbb" + struct.pack("<Q", 0xB8000)        # mov rbx, 0xB8000
    b += b"\x8b\x14\x25" + struct.pack("<I", 0x7F00)     # mov edx,[0x7F00]  rowbase
    b += b"\x8b\x0c\x25" + struct.pack("<I", 0x7F04)     # mov ecx,[0x7F04]  col
    b += b"\x3c\x0d"                                     # cmp al,'\r'
    b += b"\x74\x00"; je_cr = len(b) - 1                 # je .cr
    b += b"\x3c\x0a"                                     # cmp al,'\n'
    b += b"\x74\x00"; je_st = len(b) - 1                 # je .store (ignore)
    b += b"\x4c\x8d\x04\x0a"                             # lea r8,[rdx+rcx]
    b += b"\x4c\x01\xc3"                                 # add rbx,r8
    b += b"\x88\x03"                                     # mov [rbx],al
    b += b"\xc6\x43\x01\x0f"                             # mov byte [rbx+1],0x0F
    b += b"\x83\xc1\x02"                                 # add ecx,2
    b += b"\x81\xf9\xa0\x00\x00\x00"                     # cmp ecx,160
    b += b"\x7c\x00"; jl_st1 = len(b) - 1                # jl .store
    b += b"\x31\xc9"                                     # xor ecx,ecx
    b += b"\x81\xc2\xa0\x00\x00\x00"                     # add edx,160
    b += b"\x81\xfa\xa0\x0f\x00\x00"                     # cmp edx,4000
    b += b"\x7c\x00"; jl_st2 = len(b) - 1                # jl .store
    b += b"\x31\xd2"                                     # xor edx,edx
    b += b"\xeb\x00"; jmp_st = len(b) - 1                # jmp .store
    cr = len(b)
    b += b"\x31\xc9"                                     # xor ecx,ecx
    b += b"\x81\xc2\xa0\x00\x00\x00"                     # add edx,160
    b += b"\x81\xfa\xa0\x0f\x00\x00"                     # cmp edx,4000
    b += b"\x7c\x00"; jl_st3 = len(b) - 1                # jl .store
    b += b"\x31\xd2"                                     # xor edx,edx
    st = len(b)
    b += b"\x89\x14\x25" + struct.pack("<I", 0x7F00)     # mov [0x7F00],edx
    b += b"\x89\x0c\x25" + struct.pack("<I", 0x7F04)     # mov [0x7F04],ecx
    b += b"\x41\x58\x5a\x59\x5b\x58\xc3"                 # pop r8,rdx,rcx,rbx,rax; ret
    b[je_cr] = (cr - (je_cr + 1)) & 0xFF
    b[je_st] = (st - (je_st + 1)) & 0xFF
    b[jl_st1] = (st - (jl_st1 + 1)) & 0xFF
    b[jl_st2] = (st - (jl_st2 + 1)) & 0xFF
    b[jmp_st] = (st - (jmp_st + 1)) & 0xFF
    b[jl_st3] = (st - (jl_st3 + 1)) & 0xFF
    return bytes(b)


def stage2(vga: bool = False, shell: bool = False) -> bytes:
    a = Asm()
    # 16-bit entry
    a.emit(b"\xfa")                          # cli
    a.emit(b"\x31\xc0")                      # xor ax,ax
    a.emit(b"\x8e\xd8")                      # mov ds,ax
    a.emit(b"\x8e\xc0")                      # mov es,ax
    a.emit(b"\x8e\xd0")                      # mov ss,ax
    a.emit(b"\xbc\x00\x7c")                  # mov sp,0x7c00
    # ---- read the DSSCRIPT slot (LBA 630, 32 sectors = 16 KiB) to 0x2000:0x0000 ----
    # LBA 630 = cyl 0 / head 10 / sector 1, so 32 sectors stay inside one track.
    a.emit(b"\xfb")                            # sti (BIOS disk services want IRQs)
    a.emit(b"\xb8\x00\x20")                  # mov ax,0x2000
    a.emit(b"\x8e\xc0")                       # mov es,ax
    a.emit(b"\x31\xdb")                       # xor bx,bx
    a.emit(b"\xb8\x20\x02")                  # mov ax,0x0220  (AH=02 read, AL=32 sectors)
    a.emit(b"\xb9\x01\x00")                  # mov cx,0x0001  (cyl 0, sector 1)
    a.emit(b"\xba\x00\x0a")                  # mov dx,0x0a00  (head 10)
    a.emit(b"\x8a\x16\xf0\x7d")              # mov dl,[0x7df0] (boot drive saved by stage1)
    a.emit(b"\xcd\x13")                       # int 13h
    a.emit(b"\xfa")                            # cli
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
    a.emit(b"\xbf\x00\x10\x00\x00")          # mov edi,0x9000
    a.emit(b"\xb9\x00\x0c\x00\x00")          # mov ecx,0xc00
    a.emit(b"\xf3\xab")                      # rep stosd
    # PML4[0]=0xa003
    a.emit(b"\xc7\x05" + a.u32(0x1000) + a.u32(0x2003))
    # PDPT[0]=0xb003
    a.emit(b"\xc7\x05" + a.u32(0x2000) + a.u32(0x3003))
    # PD[0]=0x83 (2MiB page)
    a.emit(b"\xc7\x05" + a.u32(0x3000) + a.u32(0x83))
    # CR3
    a.emit(b"\xb8" + a.u32(0x1000))          # mov eax,0x9000
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
    if shell:
        # hand control to the 64-bit kernel at KERNEL_ENTRY (its own uart/vga/idt/shell)
        # Marker in VGA text memory: if the kernel never takes over, the screen keeps
        # showing "S2 OK" and nothing else -> the handoff (not the kernel) is at fault.
        for _i, _cell in enumerate((0x07320753, 0x074F0720, 0x0720074B)):   # 'S','2',' ','O','K'
            a.emit(b"\xc7\x04\x25" + a.u32(0xB8000 + _i * 4) + a.u32(_cell))
        # NOTE: len(a.b) is a stage2-relative offset; the jump executes at STAGE2_ADDR + that.
        _next = STAGE2_ADDR + len(a.b) + 5
        a.emit(b"\xe9" + struct.pack("<i", KERNEL_ENTRY - _next))

    if vga:
        a.emit(b"\xc7\x04\x25" + a.u32(0x7F00) + a.u32(0))  # mov dword [0x7F00], 0
        a.emit(b"\xc7\x04\x25" + a.u32(0x7F04) + a.u32(0))  # mov dword [0x7F04], 0
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
    if vga:
        a.call("vga_putc")
    a.emit(b"\x50\x66\xba\xfd\x03")
    a.label("putc_wait"); a.emit(b"\xec\xa8\x20"); a.jcc(b"\x84", "putc_wait")
    a.emit(b"\x66\xba\xf8\x03\x58\xee\xc3")
    if vga:
        a.label("vga_putc"); a.emit(vga_putc())
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
    b += b"\xb8\x10\x02"               # mov ax,0x0210 (read 16 sectors)
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

    # 可选的 VGA 变体：默认不生成，保证上面两个产物的 hash 不变
    if "--vga" in sys.argv:
        st2v = stage2(vga=True)
        assert len(st2v) <= LOAD_SECTORS * 512, len(st2v)
        imgv = boot_sector() + st2v + b"\x00" * (LOAD_SECTORS * 512 - len(st2v))
        imgv += b"\x00" * (1440 * 1024 - len(imgv))
        outv = HERE / "dsos-x86_64-vga.img"
        outv.write_bytes(imgv)
        print(f"✓ {outv} ({len(imgv)} bytes) [VGA + serial]")
        print("vga sha256:", hashlib.sha256(imgv).hexdigest())
        print("vga stage2 bytes:", len(st2v))


if __name__ == "__main__":
    main()
