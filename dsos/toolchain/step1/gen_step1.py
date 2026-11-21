#!/usr/bin/env python3
"""Step 1: 手写 x86_64 机器码，无 C/汇编器/链接器。

产物：
- syscall.bin      Linux/DsOS syscall 语义的扁平机器码（入口 offset 0）
- syscall.elf      最小静态 ELF64，供 qemu-x86_64 验证
- bare_serial.bin  16 位裸机引导扇区，经 COM1 输出（QEMU 裸机兜底）

机器码（x86_64 SysV/Linux syscall）：
  write(1, "DsOS booted.\n", 13)
  exit(0)
"""
from __future__ import annotations
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
MSG = b"DsOS booted.\n"


def syscall_code() -> bytes:
    # 手写字节；LEA 的 RIP 相对位移在下方校验
    code = bytearray()
    code += b"\xb8\x01\x00\x00\x00"          # mov eax, 1        (sys_write)
    code += b"\xbf\x01\x00\x00\x00"          # mov edi, 1        (stdout)
    lea_off = len(code)
    code += b"\x48\x8d\x35\x00\x00\x00\x00"  # lea rsi, [rip+disp32]
    code += b"\xba" + struct.pack("<I", len(MSG))  # mov edx, len
    code += b"\x0f\x05"                      # syscall
    code += b"\xb8\x3c\x00\x00\x00"          # mov eax, 60       (sys_exit)
    code += b"\x31\xff"                      # xor edi, edi      (code 0)
    code += b"\x0f\x05"                      # syscall
    msg_off = len(code)
    disp = msg_off - (lea_off + 7)
    code[lea_off + 3:lea_off + 7] = struct.pack("<i", disp)
    code += MSG
    assert disp == 16, disp
    return bytes(code)


def elf64(code: bytes, base: int = 0x400000) -> bytes:
    """最小静态 ELF64：一个 RX PT_LOAD；入口 = base + 0x78。"""
    ehsize, phentsize = 64, 56
    entry = base + ehsize + phentsize
    ident = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
    ehdr = ident + struct.pack("<HHIQQQIHHHHHH",
        2, 0x3E, 1, entry, ehsize, 0, 0, ehsize, phentsize, 1, 0, 0, 0)
    total = ehsize + phentsize + len(code)
    phdr = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, total, total, 0x1000)
    return ehdr + phdr + code


def bare_serial() -> bytes:
    """16 位 BIOS 引导扇区：COM1 输出，QEMU -drive 裸机可验证。"""
    msg = b"DsOS booted.\r\n\x00"
    code = bytearray()
    code += b"\xba\xf8\x03"          # mov dx, 0x3f8
    msg_off = 17
    code += b"\xbe" + struct.pack("<H", 0x7C00 + msg_off)  # mov si, msg
    loop = len(code)                  # 0x06
    code += b"\xac"                  # lodsb
    code += b"\x84\xc0"              # test al, al
    jz_pos = len(code)
    code += b"\x74\x00"              # jz halt
    code += b"\xee"                  # out dx, al
    jmp_pos = len(code)
    code += b"\xeb\x00"              # jmp loop
    halt = len(code)
    code += b"\xf4"                  # hlt
    code += b"\xeb\xfd"              # jmp halt
    code[jz_pos + 1] = halt - (jz_pos + 2)
    code[jmp_pos + 1] = (loop - (jmp_pos + 2)) & 0xff
    assert len(code) == msg_off, (len(code), msg_off)
    code += msg
    assert len(code) <= 510
    code += b"\x00" * (510 - len(code)) + b"\x55\xaa"
    return bytes(code)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02x}" for x in b)


def main() -> None:
    code = syscall_code()
    (HERE / "syscall.bin").write_bytes(code)
    (HERE / "syscall.elf").write_bytes(elf64(code))
    (HERE / "bare_serial.bin").write_bytes(bare_serial())
    (HERE / "syscall.hex").write_text(hx(code) + "\n", encoding="utf-8")
    print("syscall.bin:", len(code), "bytes")
    print("syscall.hex:")
    print(hx(code))
    print("syscall.elf:", len(elf64(code)), "bytes")
    print("bare_serial.bin:", len(bare_serial()), "bytes")


if __name__ == "__main__":
    main()
