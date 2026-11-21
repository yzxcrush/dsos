"""compiler/mini.py — 最小 IR 后端的第一个切片（bootstrap 层，允许）

范围（刻意最小）：
  fn _start / let / assign / while / if / 算术 + 比较 / sys_exit
  所有局部变量一律占栈槽（先保证正确，寄存器分配后做）

不做：数组、指针解引用、字符串、函数调用（下一步）
"""
from __future__ import annotations
import pathlib, struct, sys

# 参考实现（dsv01 前端）的位置：由 DS_REF_ROOT 指定，默认取交接包中的仓库快照
import os
ROOT = pathlib.Path(os.environ.get(
    "DS_REF_ROOT",
    r"D:\文档\deepseek-harness\default-workspace\交接\交接\项目\ds-main"))
sys.path.insert(0, str(ROOT))
from dsv01.parser import parse_program


class Emit:
    def __init__(self):
        self.b = bytearray()
        self.labels = {}
        self.fix = []

    def e(self, *parts):
        for p in parts:
            self.b += p

    def label(self, name):
        self.labels[name] = len(self.b)

    def rel(self, op, label):
        pos = len(self.b)
        self.e(op, b"\x00\x00\x00\x00")
        self.fix.append((pos + len(op), label))

    def jmp(self, label):
        self.rel(b"\xe9", label)

    def jcc(self, cc, label):
        self.rel(b"\x0f" + cc, label)

    def finish(self):
        for at, label in self.fix:
            disp = self.labels[label] - (at + 4)
            self.b[at:at + 4] = struct.pack("<i", disp)
        return bytes(self.b)


def enc_mov_rax_imm(v):
    return b"\xb8" + struct.pack("<I", v & 0xFFFFFFFF)


def enc_load_rax(off):
    if not (-128 <= off < 128):
        raise NotImplementedError("stack offset too large")
    return b"\x48\x8b\x45" + struct.pack("<b", off)


def enc_store_rax(off):
    return b"\x48\x89\x45" + struct.pack("<b", off)


BINOPS = {
    "+": b"\x48\x01\xd8",          # add rax, rbx
    "-": b"\x48\x29\xc3" b"\x48\x89\xd8",   # sub rbx,rax ; mov rax,rbx
    "*": b"\x48\x0f\xaf\xc3",      # imul rax, rbx
}

CMPS = {
    "==": b"\x0f\x94\xc0",   # sete al
    "!=": b"\x0f\x95\xc0",   # setne al
    "<":  b"\x0f\x9c\xc0",   # setl al
    ">":  b"\x0f\x9f\xc0",   # setg al
    "<=": b"\x0f\x9e\xc0",   # setle al
    ">=": b"\x0f\x9d\xc0",   # setge al
}


class Backend:
    def __init__(self):
        self.e = Emit()
        self.slots = {}          # name -> rbp offset (negative)
        self.nslots = 0

    # ---- 变量 ----
    def slot(self, name, alloc=True):
        if name not in self.slots:
            if not alloc:
                raise NameError(f"undefined variable: {name}")
            self.nslots += 1
            self.slots[name] = -8 * self.nslots
        return self.slots[name]

    # ---- 表达式 ----
    def expr(self, n):
        t = type(n).__name__
        if t == "Lit":
            v = getattr(n, "value", None)
            if not isinstance(v, int):
                raise NotImplementedError(f"literal not int: {v!r}")
            self.e.e(enc_mov_rax_imm(v))
        elif t == "Var":
            self.e.e(enc_load_rax(self.slot(n.name, alloc=False)))
        elif t == "Binary":
            op = getattr(n, "op", None)
            self.expr(n.left)
            self.e.e(b"\x50")                 # push rax
            self.expr(n.right)
            self.e.e(b"\x5b")                 # pop rbx
            if op in BINOPS:
                self.e.e(BINOPS[op])
            elif op in CMPS:
                self.e.e(b"\x48\x39\xc3")     # cmp rbx, rax  (left - right)
                self.e.e(CMPS[op])
                self.e.e(b"\x0f\xb6\xc0")     # movzx eax, al
            else:
                raise NotImplementedError(f"binop {op}")
        elif t == "Index":
            self.addr_of(n)                       # rax = base + idx*8
            self.e.e(b"\x48\x8b\x00")           # mov rax, [rax]
        elif t == "Call":
            fn = getattr(n, "fn", None)
            name = getattr(fn, "name", None)
            if name != "sys_exit":
                raise NotImplementedError(f"call {name}")
            self.expr(n.args[0])
            self.e.e(b"\x48\x89\xc7")         # mov rdi, rax
            self.e.e(enc_mov_rax_imm(60))     # SYS_exit
            self.e.e(b"\x0f\x05")             # syscall
        else:
            raise NotImplementedError(f"expr node {t}")

    def addr_of(self, n):
        """Index: rax = base + index * 8"""
        self.expr(n.obj if hasattr(n, "obj") else n.base)
        self.e.e(b"\x50")                         # push base
        self.expr(n.index)
        self.e.e(b"\x48\x6b\xc0\x08")           # imul rax, rax, 8
        self.e.e(b"\x5b")                         # pop rbx (base)
        self.e.e(b"\x48\x01\xd8")               # add rax, rbx

    def if_stmt(self, n, tag):
        """if 当语句用：条件 → 两臂 → 结束标签。"""
        self.expr(n.cond)
        self.e.e(b"\x48\x85\xc0")              # test rax, rax
        self.e.jcc(b"\x84", f"if_else_{tag}")
        for st in block_items(n.then_block):
            self.stmt(st, f"{tag}t")
        self.e.jmp(f"if_end_{tag}")
        self.e.label(f"if_else_{tag}")
        other = getattr(n, "else_", None)
        if other is not None:
            for st in block_items(other):
                self.stmt(st, f"{tag}e")
        self.e.label(f"if_end_{tag}")

    # ---- 语句 ----
    def stmt(self, n, tag):
        t = type(n).__name__
        if t == "LetStmt":
            self.expr(n.value)
            self.e.e(enc_store_rax(self.slot(n.name)))
        elif t == "AssignStmt":
            tgt = type(n.target).__name__
            if tgt == "Var":
                self.expr(n.value)
                self.e.e(enc_store_rax(self.slot(n.target.name, alloc=False)))
            elif tgt == "Index":
                self.expr(n.value)                # rax = value
                self.e.e(b"\x50")                 # push value
                self.addr_of(n.target)            # rax = addr
                self.e.e(b"\x5a")                 # pop rdx (value)
                self.e.e(b"\x48\x89\x10")        # mov [rax], rdx
            else:
                raise NotImplementedError(f"assign target {tgt}")
        elif t == "WhileStmt":
            self.e.label(f"w_cond_{tag}")
            self.expr(n.cond)
            self.e.e(b"\x48\x85\xc0")         # test rax, rax
            self.e.jcc(b"\x84", f"w_end_{tag}")   # jz
            for s in block_items(n.body):
                self.stmt(s, tag)
            self.e.jmp(f"w_cond_{tag}")
            self.e.label(f"w_end_{tag}")
        elif t == "IfExpr":
            self.if_stmt(n, tag)
        elif t == "ExprStmt":
            if type(n.expr).__name__ == "IfExpr":
                self.if_stmt(n.expr, tag)
            else:
                self.expr(n.expr)
        elif t == "Block":
            for s in n.stmts:
                self.stmt(s, tag)
        else:
            raise NotImplementedError(f"stmt node {t}")


def block_items(node):
    """Block.stmts in this AST; tolerate a bare list too."""
    return getattr(node, "stmts", node if isinstance(node, list) else [node])


def compile_source(src, units=1):
    prog = parse_program(src)
    be = Backend()
    e = be.e
    e.e(b"\x55")                    # push rbp
    e.e(b"\x48\x89\xe5")            # mov rbp, rsp
    # 先扫一遍给所有 let 分配槽位（简化：按出现顺序）
    main = None
    for item in (prog.items if hasattr(prog, "items") else prog):
        if type(item).__name__ == "FnDecl" and item.name == "_start":
            main = item
    if main is None:
        raise NameError("no _start")
    body = block_items(main.body)
    for s in body:
        if type(s).__name__ == "LetStmt":
            be.slot(s.name)
    frame = (be.nslots * 8 + 15) // 16 * 16
    e.e(b"\x48\x81\xec" + struct.pack("<I", frame))   # sub rsp, frame
    for i, s in enumerate(body):
        be.stmt(s, i)
    e.e(b"\x48\x81\xc4" + struct.pack("<I", frame))   # add rsp, frame
    e.e(b"\x5d")                    # pop rbp
    e.e(b"\xc3")                    # ret
    return e.finish()


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "out.bin")
    code = compile_source(src)
    out.write_bytes(code)
    print(f"✓ {out} ({len(code)} bytes)")
