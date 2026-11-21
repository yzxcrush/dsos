#!/usr/bin/env python3
"""DsOS Phase 1 direct machine-code builder (no C/asm/linker).

Multiboot1 ELF32: 32-bit entry -> GDT -> PAE/long mode -> 64-bit kernel.
Kernel: UART COM1, "DsOS alive", heartbeat, echo, key/line stats.
"""
from __future__ import annotations
import pathlib, struct
HERE = pathlib.Path(__file__).resolve().parent

BASE = 0x100000
CODE_OFF = 0x1000
MB_MAGIC = 0x1BADB002

class A:
    def __init__(self): self.b=bytearray(); self.labels={}; self.fix=[]
    def l(self,n): self.labels[n]=len(self.b)
    def rel(self,op,label,size=4):
        p=len(self.b); self.b+=op+b"\x00"*size; self.fix.append((p+len(op),label,size)); return p
    def jmp(self,label): self.rel(b"\xe9",label)
    def call(self,label): self.rel(b"\xe8",label)
    def jcc(self,cc,label): self.rel(b"\x0f"+cc,label)
    def lea(self,label): self.rel(b"\x48\x8d\x35",label)
    def far32(self,label,sel):
        p=len(self.b); self.b+=b"\xea\x00\x00\x00\x00"+struct.pack("<H",sel); self.fix.append((p+1,label,4))

def u16(v): return struct.pack("<H",v&0xFFFF)
def u32(v): return struct.pack("<I",v&0xFFFFFFFF)

def build():
    a=A()
    # Multiboot header (within first 8K)
    a.b+=u32(MB_MAGIC)+u32(0)+u32((-(MB_MAGIC))&0xFFFFFFFF)
    while len(a.b)<0x20: a.b.append(0)
    a.l("entry32")
    a.b+=b"\xfa"                       # cli
    a.b+=b"\x0f\x01\x16"                # lgdt [disp32]
    gd_patch=len(a.b); a.b+=u32(0)
    a.b+=b"\x0f\x20\xc0\x0c\x01\x0f\x22\xc0"  # mov eax,cr0; or al,1; mov cr0,eax
    a.far32("pm32",0x08)
    a.l("pm32")
    a.b+=b"\x66\xb8\x10\x00\x8e\xd8\x8e\xc0\x8e\xd0"  # ax=10; ds/es/ss
    a.b+=b"\xbc\x00\x00\x07\x00"       # esp=0x70000
    a.b+=b"\x31\xc0\xbf\x00\x90\x00\x00\xb9\x00\x0c\x00\x00\xf3\xab"
    a.b+=b"\xc7\x05"+u32(0x9000)+u32(0xA003)
    a.b+=b"\xc7\x05"+u32(0xA000)+u32(0xB003)
    a.b+=b"\xc7\x05"+u32(0xB000)+u32(0x83)
    a.b+=b"\xb8"+u32(0x9000)+b"\x0f\x22\xd8"
    a.b+=b"\x0f\x20\xe0\x0d"+u32(0x20)+b"\x0f\x22\xe0"
    a.b+=b"\xb9"+u32(0xC0000080)+b"\x0f\x32\x0d"+u32(0x100)+b"\x0f\x30"
    a.b+=b"\x0f\x20\xc0\x0d"+u32(0x80000001)+b"\x0f\x22\xc0"
    a.far32("lm64",0x18)
    a.l("lm64")
    a.b+=b"\x66\xb8\x10\x00\x8e\xd8\x8e\xc0\x8e\xd0"
    a.b+=b"\x48\xbc"+struct.pack("<Q",0x70000)
    a.call("uart_init")
    a.lea("s_alive"); a.call("puts")
    a.b+=b"\x45\x31\xe4"  # xor r12d,r12d keys
    a.b+=b"\x45\x31\xed"  # r13d lines
    a.b+=b"\x45\x31\xf6"  # r14d ticks
    a.b+=b"\x0f\x31\x48\xc1\xe2\x20\x48\x09\xd0\x49\x89\xc7"  # rdtsc -> r15
    a.l("loop")
    a.call("has_data")
    a.b+=b"\xa8\x01"
    a.jcc(b"\x84","heartbeat")
    a.call("getc")
    a.call("putc")
    a.b+=b"\x49\xff\xc4"  # inc r12
    a.b+=b"\x3c\x0d"
    a.jcc(b"\x85","heartbeat")
    a.b+=b"\x49\xff\xc5"  # inc r13
    a.lea("s_keys"); a.call("puts")
    a.b+=b"\x44\x89\xe7"  # mov edi,r12d
    a.call("print_u32")
    a.lea("s_lines"); a.call("puts")
    a.b+=b"\x44\x89\xef"  # mov edi,r13d
    a.call("print_u32")
    a.lea("s_nl"); a.call("puts")
    a.l("heartbeat")
    a.b+=b"\x0f\x31\x48\xc1\xe2\x20\x48\x09\xd0"  # rdtsc
    a.b+=b"\x4c\x29\xf8"  # sub rax,r15
    a.b+=b"\x48\x3d"+u32(1000000000)
    a.jcc(b"\x82","loop")  # jb loop
    a.b+=b"\x0f\x31\x48\xc1\xe2\x20\x48\x09\xd0\x49\x89\xc7"  # reset r15
    a.b+=b"\x49\xff\xc6"  # inc r14
    a.lea("s_tick"); a.call("puts")
    a.b+=b"\x44\x89\xf7"  # mov edi,r14d
    a.call("print_u32")
    a.lea("s_nl"); a.call("puts")
    a.jmp("loop")
    # UART routines
    a.l("uart_init")
    for port,val in ((0x3f9,0),(0x3fb,0x80),(0x3f8,1),(0x3f9,0),(0x3fb,3),(0x3fa,0xC7)):
        a.b+=b"\x66\xba"+u16(port)+b"\xb0"+bytes([val])+b"\xee"
    a.b+=b"\xc3"
    a.l("putc")
    a.b+=b"\x50\x66\xba\xfd\x03"       # push rax; mov dx,0x3fd
    a.l("putc_wait"); a.b+=b"\xec\xa8\x20"; a.jcc(b"\x84","putc_wait")
    a.b+=b"\x66\xba\xf8\x03\x58\xee\xc3"
    a.l("getc")
    a.b+=b"\x66\xba\xfd\x03"
    a.l("getc_wait"); a.b+=b"\xec\xa8\x01"; a.jcc(b"\x84","getc_wait")
    a.b+=b"\x66\xba\xf8\x03\xec\xc3"
    a.l("has_data"); a.b+=b"\x66\xba\xfd\x03\xec\x24\x01\xc3"
    a.l("puts")
    a.l("puts_loop"); a.b+=b"\xac\x84\xc0"; a.jcc(b"\x84","puts_done")
    a.call("putc"); a.jmp("puts_loop"); a.l("puts_done"); a.b+=b"\xc3"
    # print_u32 (edi)
    a.l("print_u32")
    a.b+=b"\x89\xf8\x31\xd2\xb9\x0a\x00\x00\x00\x45\x31\xc9"
    a.l("pu_loop"); a.b+=b"\x31\xd2\xf7\xf1\x52\x49\xff\xc1\x85\xc0"; a.jcc(b"\x85","pu_loop")
    a.l("pu_pop"); a.b+=b"\x5a\x80\xc2\x30\x88\xd0"; a.call("putc")
    a.b+=b"\x49\xff\xc9"; a.jcc(b"\x85","pu_pop"); a.b+=b"\xc3"
    # strings
    for name,text in (("s_alive",b"DsOS alive\r\n"),("s_keys",b"\r\nkeys="),("s_lines",b" lines="),("s_tick",b"\r\ntick: "),("s_nl",b"\r\n")):
        a.l(name); a.b+=text+b"\x00"
    # GDT + GDTR
    a.l("gdt")
    for g in (0,0x00CF9A000000FFFF,0x00CF92000000FFFF,0x00AF9A000000FFFF,0x00AF92000000FFFF):
        a.b+=struct.pack("<Q",g)
    a.l("gdtr"); a.b+=u16(5*8-1)+u32(BASE+a.labels["gdt"])
    # patch
    for at,label,size in a.fix:
        target=BASE+a.labels[label]
        rel=target-(BASE+at+size)
        a.b[at:at+size]=struct.pack("<i",rel)
    a.b[gd_patch:gd_patch+4]=u32(BASE+a.labels["gdtr"])
    return bytes(a.b),a

def elf32(code: bytes) -> bytes:
    ident=b"\x7fELF\x01\x01\x01\x00"+b"\x00"*8
    entry=BASE+0x20
    eh=ident+struct.pack("<HHIIIIIHHHHHH",2,3,1,entry,52,0,0,52,32,1,0,0,0)
    total=CODE_OFF+len(code)
    ph=struct.pack("<IIIIIIII",1,CODE_OFF,BASE,BASE,len(code),len(code),7,0x1000)
    return eh+ph+b"\x00"*(CODE_OFF-52-32)+code

def main():
    code,a=build()
    (HERE / "kernel.bin").write_bytes(elf32(code))
    print(f"kernel.bin {len(elf32(code))} bytes, code {len(code)}")
if __name__=="__main__": main()
