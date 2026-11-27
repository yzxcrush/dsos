"""compiler/mini16.py — Ds 的 16 位实模式后端（最小可用）

目的：让 MBR 也能用 Ds 写，从而去掉引导链里的 Python 发射器。

本后端只覆盖 MBR 需要的那一小撮语义：
    函数（栈帧在 bp）/ let / assign / if / while / 比较 / 加减
    内建：set_ds/set_es/set_ss/mov_sp / bios_putc / int13_read / halt / cli / sti
           mem_write8 / mem_read8 / ljmp_far

编码约定：16 位实模式，无 REX 前缀，偏移地址默认 16 位。
"""
from __future__ import annotations
import pathlib, struct, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import os
_REF = os.environ.get("DS_REF_ROOT",
                      r"D:\文档\deepseek-harness\default-workspace\交接\交接\项目\ds-main")
sys.path.insert(0, _REF)
from dsv01.parser import parse_program


def block_items(node):
    return getattr(node, "stmts", node if isinstance(node, list) else [node])


# ---------- 16 位编码工具 ----------
def mov_ax_imm(v):      return b"\xb8" + struct.pack("<H", v & 0xFFFF)
def mov_bx_imm(v):      return b"\xbb" + struct.pack("<H", v & 0xFFFF)
def mov_cx_imm(v):      return b"\xb9" + struct.pack("<H", v & 0xFFFF)
def mov_dx_imm(v):      return b"\xba" + struct.pack("<H", v & 0xFFFF)
def mov_ax_mem(off):    return b"\xa1" + struct.pack("<H", off & 0xFFFF)   # mov ax,[disp16]
def mov_mem_ax(off):    return b"\xa3" + struct.pack("<H", off & 0xFFFF)   # mov [disp16],ax
def mov_bp_mem(disp):   return b"\x89\x46" + struct.pack("<b", disp)       # mov [bp+d],ax
def mov_mem_bp(disp):   return b"\x8b\x46" + struct.pack("<b", disp)       # mov ax,[bp+d]
def mov_seg(seg, op):   # seg: b"\xd8"=ds  b"\xc0"=es  b"\xd0"=ss
    return b"\x8e" + seg
def add_ax_bx():        return b"\x01\xd8"
def sub_ax_bx():        return b"\x29\xd8"
def cmp_bx_ax():        return b"\x39\xc3"          # cmp bx,ax (left - right)
def test_ax_ax():       return b"\x85\xc0"
def push_ax():          return b"\x50"
def pop_bx():           return b"\x5b"
def pop_ax():           return b"\x58"
def cli():              return b"\xfa"
def sti():              return b"\xfb"
def hlt():              return b"\xf4"


class Asm:
    def __init__(self):
        self.b = bytearray()
        self.labels = {}
        self.fix = []

    def e(self, *parts):
        for p in parts:
            self.b += p

    def label(self, name):
        self.labels[name] = len(self.b)

    def rel(self, op, label, size=2):
        pos = len(self.b)
        self.e(op, b"\x00" * size)
        self.fix.append((pos + len(op), label, size))

    def jmp(self, label):      self.rel(b"\xe9", label, 2)   # rel16
    def jz(self, label):       self.rel(b"\x74", label, 1)   # rel8
    def jnz(self, label):      self.rel(b"\x75", label, 1)
    def jl(self, label):       self.rel(b"\x7c", label, 1)
    def jg(self, label):       self.rel(b"\x7f", label, 1)

    def finish(self):
        for at, label, size in self.fix:
            disp = self.labels[label] - (at + size)
            self.b[at:at + size] = struct.pack("<h" if size == 2 else "<b", disp)
        return bytes(self.b)


class Backend:
    def __init__(self):
        self.a = Asm()
        self.slots = {}
        self.nslots = 0
        self.nlabel = 0

    def new_label(self, p):
        self.nlabel += 1
        return f".{p}{self.nlabel}"

    def slot(self, name, alloc=True):
        if name not in self.slots:
            if not alloc:
                raise NameError(f"undefined variable: {name}")
            self.nslots += 1
            self.slots[name] = -2 * self.nslots
        return self.slots[name]

    # ---- 表达式 ----
    def expr(self, n):
        t = type(n).__name__
        if t == "Lit":
            v = getattr(n, "value", None)
            if not isinstance(v, int):
                raise NotImplementedError("16 位后端只支持整数常量")
            self.a.e(mov_ax_imm(v))
        elif t == "Var":
            self.a.e(mov_mem_bp(self.slot(n.name, alloc=False)))
        elif t == "Binary":
            op = getattr(n, "op", None)
            self.expr(n.left)
            self.a.e(push_ax())
            self.expr(n.right)
            self.a.e(pop_bx())
            if op == "+":
                self.a.e(add_ax_bx())
            elif op == "-":
                self.a.e(sub_ax_bx())
            elif op in ("==", "!=", "<", ">"):
                self.a.e(cmp_bx_ax())
                self.a.e(b"\x0f" + {"==": b"\x94", "!=": b"\x95",
                                    "<": b"\x9c", ">": b"\x9f"}[op] + b"\xc0")
                self.a.e(b"\x0f\xb6\xc0")
            else:
                raise NotImplementedError(f"binop {op}")
        elif t == "Call":
            self.call(n)
        else:
            raise NotImplementedError(f"expr node {t}")

    def call(self, n):
        fn = getattr(n, "fn", None)
        name = getattr(fn, "name", None)
        a = self.a
        if name == "set_ds":
            self.expr(n.args[0]); a.e(b"\x8e\xd8"); return
        if name == "set_es":
            self.expr(n.args[0]); a.e(b"\x8e\xc0"); return
        if name == "set_ss":
            self.expr(n.args[0]); a.e(b"\x8e\xd0"); return
        if name == "mov_sp":
            self.expr(n.args[0]); a.e(b"\x89\xc4"); return
        if name == "bios_putc":                     # int 10h AH=0E
            self.expr(n.args[0])
            a.e(b"\x89\xc2")                        # mov dx, ax (字符)
            a.e(mov_ax_imm(0x0E00 | 0))             # AH=0E
            a.e(b"\x89\xd1")                        # mov cx, dx? 不需要；用 al 传字符
            # 重新来：al = 字符, ah = 0x0E
            a.e(b"\x88\xd0")                        # mov al, dl
            a.e(b"\xcd\x10")
            return
        if name == "cli":  a.e(b"\xfa"); return
        if name == "sti":  a.e(b"\xfb"); return
        if name == "halt": a.e(b"\xfa\xf4\xeb\xfe"); return
        if name == "int3": a.e(b"\xcc"); return

        # ---- 以下原语只接受字面量参数（MBR/stage2 里地址都是常量，省寄存器操作） ----
        def lit(i):
            v = getattr(n.args[i], "value", None)
            if not isinstance(v, int):
                raise NotImplementedError(f"{name} 的第 {i+1} 个参数必须是整数字面量")
            return v

        if name == "disk_read":
            lba, cnt, seg, off = lit(0), lit(1), lit(2), lit(3)
            a.e(b"\xc7\x06\x00\x05" + struct.pack("<H", 16))       # DAP.size = 16
            a.e(b"\xc7\x06\x02\x05" + struct.pack("<H", cnt))      # count
            a.e(b"\xc7\x06\x04\x05" + struct.pack("<H", off))      # offset
            a.e(b"\xc7\x06\x06\x05" + struct.pack("<H", seg))      # segment
            a.e(b"\x66\xc7\x06\x08\x05" + struct.pack("<I", lba)) # LBA 低 32 位
            a.e(b"\x66\xc7\x06\x0c\x05" + struct.pack("<I", 0))   # LBA 高 32 位
            a.e(b"\xbe\x00\x05")                                    # mov si,0x0500
            a.e(b"\xb4\x42")                                         # mov ah,0x42
            a.e(b"\xcd\x13")                                         # int 13h
            return
        if name == "disk_read_chs":
            # count, cyl, sec, head, seg, off —— 全部字面量；保持 DL（启动盘号）不变
            cnt, cyl, sec, head = lit(0), lit(1), lit(2), lit(3)
            seg, off = lit(4), lit(5)
            a.e(b"\xb8" + struct.pack("<H", seg))        # mov ax,seg
            a.e(b"\x8e\xc0")                            # mov es,ax
            a.e(b"\xb8" + struct.pack("<H", 0x0200 | (cnt & 0x3F)))   # AH=02, AL=count
            a.e(b"\xb9" + struct.pack("<H", ((cyl & 0xFF) << 8) | (sec & 0x3F)))  # CH=cyl, CL=sec
            a.e(b"\xb6" + bytes([head & 0xFF]))          # mov dh,head
            a.e(b"\xbb" + struct.pack("<H", off))        # mov bx,off
            a.e(b"\xcd\x13")                            # int 13h
            return
        if name == "mem_zero":
            # 用 rep stosw 清零（ES 必须已置 0）
            start, words = lit(0), lit(1)
            a.e(b"\x31\xc0")                              # xor ax,ax
            a.e(b"\xbf" + struct.pack("<H", start & 0xFFFF))  # mov di,start
            a.e(b"\xb9" + struct.pack("<H", words & 0xFFFF))  # mov cx,words
            a.e(b"\xf3\xab")                              # rep stosw
            return
        if name == "read_port":
            a.e(b"\xba" + struct.pack("<H", lit(0)))        # mov dx,port
            a.e(b"\xec")                                   # in al,dx
            return
        if name == "a20_fast":
            a.e(b"\xe4\x92")        # in al,0x92
            a.e(b"\x0c\x02")        # or al,2
            a.e(b"\xe6\x92")        # out 0x92,al
            return
        if name == "lgdt_imm":
            a.e(b"\x0f\x01\x16" + struct.pack("<H", lit(0)))   # lgdt [disp16]
            return
        if name == "lidt_imm":
            a.e(b"\x0f\x01\x1e" + struct.pack("<H", lit(0)))   # lidt [disp16]
            return
        if name == "cr0_set":
            a.e(b"\x66\xb8" + struct.pack("<I", lit(0)))        # mov eax,imm32
            a.e(b"\x0f\x22\xc0")                               # mov cr0,eax
            return
        if name == "cr3_set":
            a.e(b"\x66\xb8" + struct.pack("<I", lit(0)))
            a.e(b"\x0f\x22\xd8")                               # mov cr3,eax
            return
        if name == "cr4_set":
            a.e(b"\x66\xb8" + struct.pack("<I", lit(0)))
            a.e(b"\x0f\x22\xe0")                               # mov cr4,eax
            return
        if name == "efer_set":
            a.e(b"\x66\xb8" + struct.pack("<I", lit(0)))        # mov eax,imm32
            a.e(b"\x66\x31\xd2")                               # xor edx,edx
            a.e(b"\xb9" + struct.pack("<I", 0xC0000080))         # mov ecx,0xC0000080
            a.e(b"\x0f\x30")                                    # wrmsr
            return
        if name == "far_jmp":
            seg, off = lit(0), lit(1)
            a.e(b"\xea" + struct.pack("<H", off) + struct.pack("<H", seg))
            return
        if name == "write32":
            a.e(b"\x66\xc7\x06" + struct.pack("<H", lit(0)) + struct.pack("<I", lit(1)))
            return
        if name == "write16":
            a.e(b"\xc7\x06" + struct.pack("<H", lit(0)) + struct.pack("<H", lit(1)))
            return
        if name == "write8":
            a.e(b"\xc6\x06" + struct.pack("<H", lit(0)) + bytes([lit(1) & 0xFF]))
            return
        if name == "out8":
            a.e(b"\xb0" + bytes([lit(1) & 0xFF]))   # mov al,imm8
            a.e(b"\xba" + struct.pack("<H", lit(0))) # mov dx,imm16
            a.e(b"\xee")                            # out dx,al
            return
        if name == "mov16":                          # mov [addr], val
            self.expr(n.args[1]); a.e(push_ax())
            self.expr(n.args[0]); a.e(b"\x89\xc3")   # bx = 地址
            a.e(pop_ax())
            a.e(b"\x89\x07")                         # mov [bx], ax
            return
        raise NotImplementedError(f"call {name}")

    def if_stmt(self, n):
        l_else = self.new_label("ie")
        l_end = self.new_label("ie")
        self.expr(n.cond)
        self.a.e(test_ax_ax())
        self.a.jz(l_else)
        for s in block_items(getattr(n, "then_block", None)):
            self.stmt(s)
        self.a.jmp(l_end)
        self.a.label(l_else)
        other = getattr(n, "else_", None)
        if other is not None:
            for s in block_items(other):
                self.stmt(s)
        self.a.label(l_end)

    # ---- 语句 ----
    def stmt(self, n):
        t = type(n).__name__
        if t == "LetStmt":
            self.expr(n.value)
            self.a.e(mov_bp_mem(self.slot(n.name)))
        elif t == "AssignStmt":
            tg = type(n.target).__name__
            if tg != "Var":
                raise NotImplementedError("assign target 只支持变量")
            self.expr(n.value)
            self.a.e(mov_bp_mem(self.slot(n.target.name, alloc=False)))
        elif t == "ExprStmt":
            if type(n.expr).__name__ == "IfExpr":
                self.if_stmt(n.expr)
            else:
                self.expr(n.expr)
        elif t == "IfExpr":
            self.if_stmt(n)
        elif t == "WhileStmt":
            l_c = self.new_label("wc")
            l_e = self.new_label("we")
            self.a.label(l_c)
            self.expr(n.cond)
            self.a.e(test_ax_ax())
            self.a.jz(l_e)
            for s in block_items(n.body):
                self.stmt(s)
            self.a.jmp(l_c)
            self.a.label(l_e)
        elif t == "ReturnStmt":
            v = getattr(n, "value", None)
            if v is not None:
                self.expr(v)
        else:
            raise NotImplementedError(f"stmt {t}")


def prescan(be, node):
    t = type(node).__name__
    if t == "FnDecl":
        return
    if t == "LetStmt":
        be.slot(node.name)
        return
    for f in getattr(node, "__dataclass_fields__", {}):
        v = getattr(node, f, None)
        if hasattr(v, "__dataclass_fields__"):
            prescan(be, v)
        elif isinstance(v, (list, tuple)):
            for x in v:
                if hasattr(x, "__dataclass_fields__"):
                    prescan(be, x)


def compile_source(src: str) -> bytes:
    prog = parse_program(src)
    items = prog.items if hasattr(prog, "items") else prog
    main = None
    for it in items:
        if type(it).__name__ == "FnDecl" and it.name in ("_start16", "_start"):
            main = it
            break
    if main is None:
        raise NameError("no _start16 / _start")
    be = Backend()
    body = block_items(main.body)
    for st in body:
        prescan(be, st)
    a = be.a
    a.e(b"\xfc")                      # cld
    a.e(b"\x31\xc0")                  # xor ax,ax
    a.e(b"\x8e\xd8")                  # mov ds,ax
    a.e(b"\x8e\xc0")                  # mov es,ax
    a.e(b"\x8e\xd0")                  # mov ss,ax
    a.e(b"\xbc\x00\x7c")              # mov sp,0x7c00
    a.e(b"\x89\xe5")                  # mov bp,sp
    frame = (be.nslots * 2 + 1) // 2 * 2
    if frame:
        a.e(b"\x81\xec" + struct.pack("<H", frame))
    for st in body:
        be.stmt(st)
    a.e(b"\xfa\xf4\xeb\xfe")          # cli; hlt; jmp $
    return a.finish()


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "out16.bin")
    code = compile_source(src)
    out.write_bytes(code)
    print(f"✓ {out} ({len(code)} 字节)")
