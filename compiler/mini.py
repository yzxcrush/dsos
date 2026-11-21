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
        self.data = bytearray()          # .rodata：字符串字面量
        self.data_labels = {}            # label -> offset inside .data

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

    def add_string(self, text: str) -> str:
        label = f".str{len(self.data_labels)}"
        self.data_labels[label] = len(self.data)
        self.data += text.encode("utf-8")
        return label

    def lea_rip(self, reg, label):
        """lea reg, [rip+disp32]  — 目标可以是代码标签或 .rodata 标签"""
        assert reg == 6, "this slice only supports rsi"
        self.e(b"\x48\x8d\x35")
        at = len(self.b)
        self.e(b"\x00\x00\x00\x00")
        self.fix.append((at, label))

    def finish(self):
        code_len = len(self.b)
        for label, off in self.data_labels.items():
            self.labels[label] = code_len + off
        self.b += self.data
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
    def __init__(self, target="linux"):
        self.target = target
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
            if isinstance(v, str):
                # 字符串只作为 p() 的实参使用（本切片不做字符串值运算）
                raise NotImplementedError("string literal only allowed as p(...) argument")
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
            if name == "halt":
                self.e.e(b"\xfa\xf4\xeb\xfe")   # cli; hlt; jmp $
                return
            if name == "p" and self.target == "bare":
                arg = n.args[0]
                if type(arg).__name__ != "Lit" or not isinstance(getattr(arg, "value", None), str):
                    raise NotImplementedError("bare p() only supports string literals")
                text = arg.value.encode("utf-8")
                for i, ch in enumerate(text):
                    if ch == 0x0A:                  # 换行：本切片只写一行，忽略
                        continue
                    # mov byte [0xB8000 + i*2], ch      C6 04 25 <d32> <imm8>
                    self.e.e(b"\xc6\x04\x25" + struct.pack("<I", 0xB8000 + i * 2) + bytes([ch]))
                    # mov byte [0xB8000 + i*2 + 1], 0x0F
                    self.e.e(b"\xc6\x04\x25" + struct.pack("<I", 0xB8000 + i * 2 + 1) + b"\x0f")
                return
            if name == "p":
                arg = n.args[0]
                if type(arg).__name__ != "Lit" or not isinstance(getattr(arg, "value", None), str):
                    raise NotImplementedError("p() only supports string literals in this slice")
                text = arg.value
                label = self.e.add_string(text)
                self.e.e(b"\xb8\x01\x00\x00\x00")          # mov eax, 1 (SYS_write)
                self.e.e(b"\xbf\x01\x00\x00\x00")          # mov edi, 1 (stdout)
                self.e.lea_rip(6, label)                       # lea rsi, [rip+str]
                self.e.e(b"\xba" + struct.pack("<I", len(text.encode("utf-8"))))  # mov edx, len
                self.e.e(b"\x0f\x05")                        # syscall
                return
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


def compile_source(src, units=1, target="linux"):
    prog = parse_program(src)
    be = Backend(target)
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
    if target != "bare":
        e.e(b"\x48\x81\xc4" + struct.pack("<I", frame))   # add rsp, frame
        e.e(b"\x5d")                # pop rbp
        e.e(b"\xc3")                # ret
    else:
        e.e(b"\xfa\xf4\xeb\xfe")   # 兜底：cli; hlt; jmp $
    return e.finish()


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "out.bin")
    code = compile_source(src)
    out.write_bytes(code)
    print(f"✓ {out} ({len(code)} bytes)")


# ===========================================================================
# 阶段④ 第 1 项：用户函数调用与参数
# （在文件末尾重定义 compile_source，覆盖上面的单函数版本）
# ===========================================================================
ARG_REGS = (b"\x48\x89\x7d", b"\x48\x89\x75", b"\x48\x89\x55")  # mov [rbp+d], rdi/rsi/rdx


def _call(self, label):
    pos = len(self.b)
    self.e(b"\xe8", b"\x00\x00\x00\x00")
    self.fix.append((pos + 1, label))


Emit.call = _call


def compile_source(src, units=1, target="linux"):   # noqa: F811
    prog = parse_program(src)
    items = prog.items if hasattr(prog, "items") else prog
    fns = [it for it in items if type(it).__name__ == "FnDecl"]
    fnmap = {f.name: f for f in fns}
    if "_start" not in fnmap:
        raise NameError("no _start")
    global _FNMAP_CACHE
    _FNMAP_CACHE = fnmap

    e = Emit()
    order = ["_start"] + [f.name for f in fns if f.name != "_start"]

    for fname in order:
        fn = fnmap[fname]
        be = Backend(target)
        be.e = e
        be.fn = fn
        be.ep = f".ep_{fname}"
        e.label("fn_" + fname)
        e.e(b"\x55")                  # push rbp
        e.e(b"\x48\x89\xe5")        # mov rbp, rsp

        params = getattr(fn, "params", []) or []
        for i, p in enumerate(params):
            name = getattr(p, "name", None) or (p[0] if isinstance(p, (list, tuple)) else None)
            off = be.slot(name)
        # 先扫局部变量，确定帧大小
        body = block_items(fn.body)
        for st in body:
            if type(st).__name__ == "LetStmt":
                be.slot(st.name)
        frame = (be.nslots * 8 + 15) // 16 * 16
        if frame:
            e.e(b"\x48\x81\xec" + struct.pack("<I", frame))
        # 参数落栈
        for i in range(len(params)):
            off = be.slots[getattr(params[i], "name", None) or params[i][0]]
            e.e(ARG_REGS[i] + struct.pack("<b", off))

        for i, st in enumerate(body):
            be.stmt(st, i)

        e.label(be.ep)
        if frame:
            e.e(b"\x48\x81\xc4" + struct.pack("<I", frame))
        e.e(b"\x5d")                  # pop rbp
        e.e(b"\xc3")                  # ret

    return e.finish()


# --- Backend 扩展：return 与用户函数调用 ---
def _stmt(self, n, tag):
    t = type(n).__name__
    if t == "ReturnStmt":
        val = getattr(n, "value", None)
        if val is not None:
            self.expr(val)
        self.e.jmp(self.ep)
        return
    return _orig_stmt(self, n, tag)


_orig_stmt = Backend.stmt
Backend.stmt = _stmt


def _expr(self, n):
    if type(n).__name__ == "Call":
        fn = getattr(n, "fn", None)
        name = getattr(fn, "name", None)
        if name and name in _FNMAP_CACHE:
            args = list(getattr(n, "args", []) or [])
            if len(args) > 3:
                raise NotImplementedError(">3 args")
            for a in args:
                self.expr(a)
                self.e.e(b"\x50")             # push arg
            for reg in (b"\x5f", b"\x5e", b"\x5a")[:len(args)]:   # pop rdi/rsi/rdx
                self.e.e(reg)
            self.e.call("fn_" + name)
            return
    return _orig_expr(self, n)


_orig_expr = Backend.expr
Backend.expr = _expr
_FNMAP_CACHE = {}
