"""DsOS v0.4 kernel — keyboard + shell + ACPI shutdown.

Pure Python emitting raw x86-64 machine code (no assembler, no C, no linker).
Built on gen_shell.Asm (labels + rel32 fixups) with the extra instruction forms we need.

Memory map
----------
0x001000/0x002000/0x003000   PML4 / PDPT / PD      (set up by stage2)
0x003FF0                     IDTR (10 bytes)
0x004000..0x004FFF           IDT (256 gates)
0x003000                     (PD — note: buffers are placed below 0x3000-free zone)
0x003100                     line buffer (256)
0x003180                     line length (dword)
0x003200                     keyboard ring: head @0x3200, tail @0x3204, data @0x3210
0x003400                     tick counter (dword)
0x007F00/0x007F04            VGA cursor row-base / column
0x009000                     this kernel
0x070000                     stack (set by stage2)
"""
import struct
import gen_shell as gb

ENTRY = 0x9000

# ---- state addresses -------------------------------------------------------
# NOTE: the PD lives at 0x3000..0x3FFF, so nothing of ours may sit there.
IDTR = 0x5FF0
IDT = 0x4000
LINE = 0x5000
LINELEN = 0x5080
RING_HEAD = 0x5100
RING_TAIL = 0x5104
RING_BUF = 0x5110
TICKS = 0x5200
IRQFLAG = 0x5210          # set to 1 the first time IRQ1 actually fires
VGA_ROW = 0x7F00
VGA_COL = 0x7F04

# ---- register numbers ------------------------------------------------------
RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
R8, R9, R10, R11, R12, R13, R14, R15 = range(8, 16)

ALU = {"add": 0x01, "sub": 0x29, "and": 0x21, "or": 0x09, "xor": 0x31, "cmp": 0x39, "test": 0x85}
ALU_EXT = {"add": 0, "or": 1, "and": 4, "sub": 5, "xor": 6, "cmp": 7}   # for 0x81 /ext imm32


def modrm(mod, reg, rm):
    return bytes([(mod << 6) | ((reg & 7) << 3) | (rm & 7)])


def rex(w=1, r=0, x=0, b=0):
    v = 0x40 | (w << 3) | (r << 2) | (x << 1) | b
    return bytes([v]) if v != 0x40 else b""


class K(gb.Asm):
    # -- primitives ------------------------------------------------------
    def mov_ri(self, reg, imm):
        """mov r64, imm64"""
        self.emit(rex(1, 0, 0, reg >> 3) + bytes([0xB8 + (reg & 7)]) + struct.pack("<Q", imm & 0xFFFFFFFFFFFFFFFF))

    def mov_r32i(self, reg, imm):
        self.emit(rex(0, 0, 0, reg >> 3) + bytes([0xB8 + (reg & 7)]) + struct.pack("<I", imm & 0xFFFFFFFF))

    def mov_rr(self, dst, src):
        """mov r64, r64"""
        self.emit(rex(1, src >> 3, 0, dst >> 3) + b"\x89" + modrm(3, src, dst))

    def mov_r8r8(self, dst, src):
        self.emit(rex(0, src >> 3, 0, dst >> 3) + b"\x88" + modrm(3, src, dst))

    def alu(self, op, dst, src):
        """add/sub/and/or/xor/cmp/test r64, r64 (dst op= src)"""
        self.emit(rex(1, src >> 3, 0, dst >> 3) + bytes([ALU[op]]) + modrm(3, src, dst))

    def alu_i(self, op, reg, imm):
        """add/sub/and/or/xor/cmp r64, imm32 (sign-extended)"""
        self.emit(rex(1, 0, 0, reg >> 3) + b"\x81" + modrm(3, ALU_EXT[op], reg) + struct.pack("<i", imm))

    def alu_i8(self, op, reg, imm):
        self.emit(rex(1, 0, 0, reg >> 3) + b"\x83" + modrm(3, ALU_EXT[op], reg) + bytes([imm & 0xFF]))

    def inc_r(self, reg):
        self.emit(rex(1, 0, 0, reg >> 3) + b"\xFF" + modrm(3, 0, reg))

    def dec_r(self, reg):
        self.emit(rex(1, 0, 0, reg >> 3) + b"\xFF" + modrm(3, 1, reg))

    def push_r(self, reg):
        self.emit((b"\x41" if reg >= 8 else b"") + bytes([0x50 + (reg & 7)]))

    def pop_r(self, reg):
        self.emit((b"\x41" if reg >= 8 else b"") + bytes([0x58 + (reg & 7)]))

    def ret(self):
        self.emit(b"\xc3")

    def sti(self):
        self.emit(b"\xfb")

    def cli(self):
        self.emit(b"\xfa")

    def hlt(self):
        self.emit(b"\xf4")

    def iretq(self):
        self.emit(b"\x48\xcf")

    # -- memory (absolute disp32, 64-bit) --------------------------------
    def load_r64_abs(self, reg, addr):
        self.emit(rex(1, reg >> 3, 0, 0) + b"\x8b" + modrm(0, reg, 4) + b"\x25" + struct.pack("<I", addr))

    def store_r64_abs(self, addr, reg):
        self.emit(rex(1, reg >> 3, 0, 0) + b"\x89" + modrm(0, reg, 4) + b"\x25" + struct.pack("<I", addr))

    def load_r32_abs(self, reg, addr):
        self.emit(rex(0, reg >> 3, 0, 0) + b"\x8b" + modrm(0, reg, 4) + b"\x25" + struct.pack("<I", addr))

    def store_r32_abs(self, addr, reg):
        self.emit(rex(0, reg >> 3, 0, 0) + b"\x89" + modrm(0, reg, 4) + b"\x25" + struct.pack("<I", addr))

    def load_al_abs(self, addr):
        self.emit(b"\x8a" + modrm(0, 0, 4) + b"\x25" + struct.pack("<I", addr))

    def store_al_abs(self, addr):
        self.emit(b"\x88" + modrm(0, 0, 4) + b"\x25" + struct.pack("<I", addr))

    def store_byte_abs(self, addr, imm):
        self.emit(b"\xc6" + modrm(0, 0, 4) + b"\x25" + struct.pack("<I", addr) + bytes([imm & 0xFF]))

    def store_word_abs(self, addr, imm):
        """mov word [addr], imm16"""
        self.emit(b"\x66\xc7" + modrm(0, 0, 4) + b"\x25" + struct.pack("<I", addr) + struct.pack("<H", imm))

    def store_qword_abs(self, addr, imm):
        """mov qword [addr], imm32 (sign extended)"""
        self.emit(b"\x48\xc7" + modrm(0, 0, 4) + b"\x25" + struct.pack("<I", addr) + struct.pack("<i", imm))

    def load_al_base(self, base):
        """mov al, [base]"""
        self.emit(rex(0, 0, 0, base >> 3) + b"\x8a" + modrm(0, 0, base))

    def load_r32_base(self, reg, base):
        self.emit(rex(0, reg >> 3, 0, base >> 3) + b"\x8b" + modrm(0, reg, base))

    def store_al_base(self, base):
        self.emit(rex(0, 0, 0, base >> 3) + b"\x88" + modrm(0, 0, base))

    def load_r32_base_index(self, reg, addr_expr=False):
        raise NotImplementedError

    def movzx_eax_byte_x(self, base, index):
        """movzx eax, byte [base + index]"""
        self.emit(rex(0, 0, index >> 3, base >> 3) + b"\x0f\xb6" + modrm(0, 0, 4)
                  + bytes([((index & 7) << 3) | (base & 7)]))

    # -- control flow ----------------------------------------------------
    def jmp_label(self, label):
        self.jmp(label)

    def jcc_label(self, cond, label):
        self.jcc(cond, label)

    def jmp_reg(self, reg):
        self.emit(rex(0, 0, 0, reg >> 3) + b"\xff" + modrm(3, 4, reg))

    def call_label(self, label):
        self.call(label)

    # -- string / io -----------------------------------------------------
    def lodsb(self):
        self.emit(b"\xac")

    def stosb(self):
        self.emit(b"\xaa")

    def rep_stosb(self):
        self.emit(b"\xf3\xaa")

    def in_al_dx(self):
        self.emit(b"\xec")

    def out_dx_al(self):
        self.emit(b"\xee")

    def out_dx_eax(self):
        self.emit(b"\xef")

    def out_imm8_al(self, port):
        self.emit(b"\xe6" + bytes([port]))

    def in_al_imm8(self, port):
        self.emit(b"\xe4" + bytes([port]))

    def outw_dx_ax(self):
        self.emit(b"\x66\xef")

    def mov_dx_imm16(self, val):
        self.emit(b"\x66\xba" + struct.pack("<H", val))

    def mov_ax_imm16(self, val):
        self.emit(b"\x66\xb8" + struct.pack("<H", val))

    def mov_al_imm(self, val):
        self.emit(b"\xb0" + bytes([val & 0xFF]))

    def test_al_imm(self, val):
        self.emit(b"\xa8" + bytes([val & 0xFF]))

    def cmp_al_imm(self, val):
        self.emit(b"\x3c" + bytes([val & 0xFF]))

    def shl_r64_imm(self, reg, n):
        self.emit(rex(1, 0, 0, reg >> 3) + b"\xc1" + modrm(3, 4, reg) + bytes([n]))

    def shr_r64_imm(self, reg, n):
        self.emit(rex(1, 0, 0, reg >> 3) + b"\xc1" + modrm(3, 5, reg) + bytes([n]))

    def div_r64(self, reg):
        self.emit(rex(1, 0, 0, reg >> 3) + b"\xf7" + modrm(3, 6, reg))

    def lidt_abs(self, addr):
        self.emit(b"\x0f\x01" + modrm(0, 3, 4) + b"\x25" + struct.pack("<I", addr))

    def lea_abs(self, reg, addr):
        """lea reg, [rip+disp] to an absolute address (fit via 32-bit disp)"""
        pos = len(self.b)
        # 48 8D /r with RIP-relative (mod=00, rm=101)
        self.emit(rex(1, reg >> 3, 0, 0) + b"\x8d" + modrm(0, reg, 5) + b"\x00\x00\x00\x00")
        disp = addr - (pos + 7)
        self.b[pos + 3:pos + 7] = struct.pack("<i", disp)

    def times(self, n, byte=b"\x00"):
        self.emit(byte * n)


# ---------------------------------------------------------------- addressing
def _modrm_mem(reg, base, disp, w=1, movzx=False):
    """Return modrm+sib+disp bytes for [base + disp] with reg as the other operand."""
    r = (reg & 7)
    b = (base & 7)
    rex_b = 1 if base >= 8 else 0
    rex_r = 1 if reg >= 8 else 0
    if disp == 0 and b != 5:
        mod, tail = 0, b""
    elif -128 <= disp < 128:
        mod, tail = 1, struct.pack("<b", disp)
    else:
        mod, tail = 2, struct.pack("<i", disp)
    rm = b if b != 4 else 4          # rsp/r12 as base needs SIB
    if b == 4:
        sib = bytes([0x24])
        return rex(w, rex_r, 0, rex_b), bytes([(mod << 6) | (r << 3) | 4]) + sib + tail
    return rex(w, rex_r, 0, rex_b), bytes([(mod << 6) | (r << 3) | rm]) + tail


class K2(K):
    # memory with base+disp
    def ld32(self, reg, base, disp=0):
        rx, m = _modrm_mem(reg, base, disp, w=0)
        self.emit(rx + b"\x8b" + m)

    def st32(self, base, disp, reg):
        rx, m = _modrm_mem(reg, base, disp, w=0)
        self.emit(rx + b"\x89" + m)

    def ld64(self, reg, base, disp=0):
        rx, m = _modrm_mem(reg, base, disp, w=1)
        self.emit(rx + b"\x8b" + m)

    def st64(self, base, disp, reg):
        rx, m = _modrm_mem(reg, base, disp, w=1)
        self.emit(rx + b"\x89" + m)

    def ld8(self, reg, base, disp=0):
        rx, m = _modrm_mem(reg, base, disp, w=0)
        self.emit(rx + b"\x8a" + m)

    def st8(self, base, disp, reg):
        rx, m = _modrm_mem(reg, base, disp, w=0)
        self.emit(rx + b"\x88" + m)

    def movzx8(self, reg, base, disp=0):
        rx, m = _modrm_mem(reg, base, disp, w=0)
        self.emit(rx + b"\x0f\xb6" + m)

    def st8_imm(self, base, disp, imm):
        rx, m = _modrm_mem(0, base, disp, w=0)
        self.emit(rx + b"\xc6" + m + bytes([imm & 0xFF]))

    def inc_dword_abs(self, addr):
        self.emit(b"\xff\x04\x25" + struct.pack("<I", addr))

    def xor_self(self, reg):
        # same register on both sides: REX.R and REX.B must both be set for r8+
        self.emit(rex(0, reg >> 3, 0, reg >> 3) + b"\x31" + modrm(3, reg, reg))

    def movzx_eax_al(self):
        self.emit(b"\x0f\xb6\xc0")

    def dec_r(self, reg):
        self.emit(rex(1, 0, 0, reg >> 3) + b"\xff" + modrm(3, 1, reg))

    def rep_stosd(self):
        self.emit(b"\xf3\xab")

    def movsd_stosd(self):
        self.emit(b"\xab")

    def nop(self):
        self.emit(b"\x90")

    def j(self, label):
        self.jmp(label)

    def jz(self, label):
        self.jcc(b"\x84", label)

    def jnz(self, label):
        self.jcc(b"\x85", label)

    def jl(self, label):
        self.jcc(b"\x8c", label)

    def jle(self, label):
        self.jcc(b"\x8e", label)

    def jg(self, label):
        self.jcc(b"\x8f", label)

    def jge(self, label):
        self.jcc(b"\x8d", label)

    def jb(self, label):
        self.jcc(b"\x82", label)

    def jae(self, label):
        self.jcc(b"\x83", label)
