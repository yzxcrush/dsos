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
        return self.add_data(text.encode("utf-8") + b"\x00")

    def add_data(self, blob: bytes) -> str:
        label = f".dat{len(self.data_labels)}"
        self.data_labels[label] = len(self.data)
        self.data += blob
        return label

    def lea_rip(self, reg, label):
        """lea reg, [rip+disp32]  — 目标可以是代码标签或 .rodata 标签"""
        if reg == 6:
            self.e(b"\x48\x8d\x35")
        elif reg == 0:
            self.e(b"\x48\x8d\x05")
        else:
            raise NotImplementedError(f"lea_rip reg {reg}")
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

BITOPS = {
    "&": b"\x48\x21\xd8",          # and rax, rbx
    "|": b"\x48\x09\xd8",          # or  rax, rbx
    "^": b"\x48\x31\xd8",          # xor rax, rbx
}

CMPS = {
    "==": b"\x0f\x94\xc0",   # sete al
    "!=": b"\x0f\x95\xc0",   # setne al
    "<":  b"\x0f\x9c\xc0",   # setl al
    ">":  b"\x0f\x9f\xc0",   # setg al
    "<=": b"\x0f\x9e\xc0",   # setle al
    ">=": b"\x0f\x9d\xc0",   # setge al
}

SCRATCH = 4     # 每个函数预留的临时栈槽数（match 的 subject 等）


class Backend:
    def __init__(self, target="linux"):
        self.target = target
        self.e = Emit()
        self.slots = {}          # name -> rbp offset (negative)
        self.nslots = 0
        self.scratch_i = 0       # 已用的临时槽计数
        self.fn_name = "f"       # 当前函数名（标签前缀，避免跨函数撞名）
        self.label_n = 0

    def temp(self):
        """临时槽：位于已声明局部变量之下（更负），共 SCRATCH 个。返回 rbp 位移。"""
        k = self.scratch_i
        self.scratch_i += 1
        return -8 * (self.nslots + SCRATCH - k)

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
                label = self.e.add_string(v)
                self.e.lea_rip(0, label)          # lea rax, [rip+str]
                return
            if not isinstance(v, int):
                raise NotImplementedError(f"literal not int: {v!r}")
            self.e.e(enc_mov_rax_imm(v))
        elif t == "ArrayLit":
            items = getattr(n, "items", None) or getattr(n, "elements", None) or []
            data = b""
            for it in items:
                if type(it).__name__ != "Lit" or not isinstance(getattr(it, "value", None), int):
                    raise NotImplementedError("array literal: only int elements in this slice")
                data += struct.pack("<Q", getattr(it, "value", 0))
            label = self.e.add_data(data)
            self.e.lea_rip(0, label)              # lea rax, [rip+array]
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
            elif op in BITOPS:
                self.e.e(BITOPS[op])
            elif op in ("&&", "||"):
                # rbx=left, rax=right；非短路求值（本切片无副作用，语义等价）
                self.e.e(b"\x48\x85\xdb")                 # test rbx, rbx
                self.e.e(b"\x0f\x95\xc3")                 # setne bl
                self.e.e(b"\x48\x85\xc0")                 # test rax, rax
                self.e.e(b"\x0f\x95\xc0")                 # setne al
                self.e.e(b"\x48\x21\xd8" if op == "&&" else b"\x48\x09\xd8")
            elif op in ("<<", ">>"):
                # rbx = left, rax = right(count) -> rcx=count, rax=left, shift
                self.e.e(b"\x48\x89\xc1")                 # mov rcx, rax
                self.e.e(b"\x48\x89\xd8")                 # mov rax, rbx
                self.e.e(b"\x48\xd3\xe0" if op == "<<" else b"\x48\xd3\xe8")
            elif op in CMPS:
                self.e.e(b"\x48\x39\xc3")     # cmp rbx, rax  (left - right)
                self.e.e(CMPS[op])
                self.e.e(b"\x0f\xb6\xc0")     # movzx eax, al
            else:
                raise NotImplementedError(f"binop {op}")
        elif t == "Unary":
            op = getattr(n, "op", None)
            opr = getattr(n, "operand", None) or getattr(n, "expr", None) or getattr(n, "value", None)
            if op == "~":
                self.expr(opr)
                self.e.e(b"\x48\xf7\xd0")     # not rax
            elif op == "-":
                self.expr(opr)
                self.e.e(b"\x48\xf7\xd8")     # neg rax
            elif op == "!":
                self.expr(opr)
                self.e.e(b"\x48\x85\xc0")     # test rax, rax
                self.e.e(b"\x0f\x94\xc0")     # sete al
                self.e.e(b"\x0f\xb6\xc0")     # movzx eax, al
            else:
                raise NotImplementedError(f"unary {op}")
        elif t == "Cast":
            self.expr(n.expr)
            ty = getattr(getattr(n, "type", None), "name", None)
            CAST = {"u8": b"\x0f\xb6\xc0", "i8": b"\x0f\xbe\xc0",
                    "u16": b"\x0f\xb7\xc0", "i16": b"\x0f\xbf\xc0",
                    "u32": b"\x89\xc0", "i32": b"\x48\x63\xc0"}
            if ty in CAST:
                self.e.e(CAST[ty])
            elif ty in ("u64", "i64", "usize", "isize"):
                pass
            else:
                raise NotImplementedError(f"cast to {ty}")
        elif t == "MatchExpr":
            self.match_expr(n)
        elif t == "Index":
            self.addr_of(n)                       # rax = base + idx*8
            self.e.e(b"\x48\x8b\x00")           # mov rax, [rax]
        elif t == "Call":
            fn = getattr(n, "fn", None)
            name = getattr(fn, "name", None)
            # ---- 窄 load：load8/16/32/64(addr) -> 值（零扩展） ----
            LOAD = {"load8": b"\x0f\xb6\x00", "load16": b"\x0f\xb7\x00",
                    "load32": b"\x8b\x00", "load64": b"\x48\x8b\x00"}
            if name in LOAD:
                self.expr(n.args[0])          # rax = addr
                self.e.e(LOAD[name])
                return
            # ---- 窄 store：store8/16/32/64(addr, value) ----
            STORE = {"store8": b"\x88\x10", "store16": b"\x66\x89\x10",
                     "store32": b"\x89\x10", "store64": b"\x48\x89\x10"}
            if name in STORE:
                self.expr(n.args[1])          # value
                self.e.e(b"\x50")             # push value
                self.expr(n.args[0])          # addr
                self.e.e(b"\x5a")             # pop rdx (value)
                self.e.e(STORE[name])         # mov [rax], <rdx 窄>
                return
            # ---- 系统级内建：为"长模式 -> 实模式 -> 长模式"往返铺路 ----
            if name == "rdmsr":
                self.expr(n.args[0])                  # ecx = msr 号
                self.e.e(b"\x89\xc1")               # mov ecx, eax
                self.e.e(b"\x0f\x32")               # rdmsr
                self.e.e(b"\x48\xc1\xe2\x20")     # shl rdx, 32
                self.e.e(b"\x48\x09\xd0")          # or rax, rdx
                return
            if name == "wrmsr":
                self.expr(n.args[0])                  # msr
                self.e.e(b"\x89\xc1")               # mov ecx, eax
                self.expr(n.args[1])                  # value -> rax
                self.e.e(b"\x48\x89\xc2")          # mov rdx, rax
                self.e.e(b"\x48\xc1\xea\x20")     # shr rdx, 32
                self.e.e(b"\x0f\x30")               # wrmsr
                return
            CRC = {"read_cr0": b"\x0f\x20\xc0", "read_cr3": b"\x0f\x20\xd8",
                   "read_cr4": b"\x0f\x20\xe0"}
            if name in CRC:
                self.e.e(CRC[name])
                return
            CWC = {"write_cr0": b"\x0f\x22\xc0", "write_cr3": b"\x0f\x22\xd8",
                   "write_cr4": b"\x0f\x22\xe0"}
            if name in CWC:
                self.expr(n.args[0])
                self.e.e(b"\x48\x89\xc0")          # mov rax, rax（占位保持语义）
                self.e.e(CWC[name])
                return
            if name == "lgdt":
                self.expr(n.args[0])
                self.e.e(b"\x0f\x01\x10")          # lgdt [rax]
                return
            if name == "lidt":
                self.expr(n.args[0])
                self.e.e(b"\x0f\x01\x18")          # lidt [rax]
                return
            if name == "invlpg":
                self.expr(n.args[0])
                self.e.e(b"\x0f\x01\x38")          # invlpg [rax]
                return
            if name == "sti":
                self.e.e(b"\xfb")
                return
            if name == "run":
                # 跳到运行时生成的代码：call rax；返回值留在 rax
                self.expr(n.args[0])          # rax = addr
                self.e.e(b"\xff\xd0")         # call rax
                return
            if name == "out8":
                self.expr(n.args[1])          # value
                self.e.e(b"\x50")             # push value
                self.expr(n.args[0])          # port
                self.e.e(b"\x48\x89\xc2")     # mov rdx, rax
                self.e.e(b"\x58")             # pop rax (value)
                self.e.e(b"\xee")             # out dx, al
                return
            if name == "in8":
                self.expr(n.args[0])          # port
                self.e.e(b"\x48\x89\xc2")     # mov rdx, rax
                self.e.e(b"\xec")             # in al, dx
                self.e.e(b"\x0f\xb6\xc0")     # movzx eax, al
                return
            if name == "cli":
                self.e.e(b"\xfa")
                return
            if name == "hlt":
                self.e.e(b"\xf4")
                return
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

    def match_expr(self, n):
        """match 当表达式：LitPat / WildcardPat / BindPat。结果在 rax。"""
        # subject 先存到临时槽（只求值一次）
        subj = self.temp()
        self.expr(n.subject)
        self.e.e(enc_store_rax(subj))
        end = self.new_label("m_end")
        default = None
        # 先发比较（LitPat），跳过 BindPat/WildcardPat（它们无条件）
        arms = getattr(n, "arms", []) or []
        for i, arm in enumerate(arms):
            pat = arm.pattern
            pt = type(pat).__name__
            if pt == "LitPat":
                self.e.e(enc_load_rax(subj))          # rax = subject
                self.e.e(b"\x50")                     # push
                self.e.e(enc_mov_rax_imm(getattr(pat, "value", 0)))
                self.e.e(b"\x5b")                     # pop rbx = subject
                self.e.e(b"\x48\x39\xc3")           # cmp rbx, rax
                self.e.jcc(b"\x84", f"m_arm_{i}")
            elif pt == "BindPat":
                # 无条件绑定：subject -> 变量
                self.e.e(enc_load_rax(subj))
                self.e.e(enc_store_rax(self.slot(pat.name)))
                self.e.jmp(f"m_arm_{i}")
            elif pt == "WildcardPat":
                default = i
        if default is None:
            # 无通配：无匹配则结果为 0
            self.e.e(b"\x31\xc0")                   # xor eax, eax
        else:
            self.e.jmp(f"m_arm_{default}")
        for i, arm in enumerate(arms):
            self.e.label(f"m_arm_{i}")
            self.arm_body(arm.body)
            self.e.jmp(end)
        self.e.label(end)

    def arm_body(self, body):
        if type(body).__name__ == "Block":
            for st in body.stmts:
                self.stmt(st, None)
        else:
            self.expr(body)

    def new_label(self, prefix):
        self.label_n += 1
        return f".{self.fn_name}_{prefix}_{self.label_n}"

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
        l_else = self.new_label("ielse")
        l_end = self.new_label("iend")
        self.expr(n.cond)
        self.e.e(b"\x48\x85\xc0")              # test rax, rax
        self.e.jcc(b"\x84", l_else)
        for st in block_items(n.then_block):
            self.stmt(st, tag)
        self.e.jmp(l_end)
        self.e.label(l_else)
        other = getattr(n, "else_", None)
        if other is not None:
            for st in block_items(other):
                self.stmt(st, tag)
        self.e.label(l_end)

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
            l_cond = self.new_label("wcond")
            l_end = self.new_label("wend")
            self.e.label(l_cond)
            self.expr(n.cond)
            self.e.e(b"\x48\x85\xc0")         # test rax, rax
            self.e.jcc(b"\x84", l_end)           # jz
            for st2 in block_items(n.body):
                self.stmt(st2, tag)
            self.e.jmp(l_cond)
            self.e.label(l_end)
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
    frame = ((be.nslots + SCRATCH) * 8 + 15) // 16 * 16
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
        be.fn_name = fname
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
        frame = ((be.nslots + SCRATCH) * 8 + 15) // 16 * 16
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
            # 栈顶是最后一个实参，必须逆序弹出到 rdi/rsi/rdx
            for reg in list((b"\x5f", b"\x5e", b"\x5a")[:len(args)])[::-1]:
                self.e.e(reg)
            self.e.call("fn_" + name)
            return
    return _orig_expr(self, n)


_orig_expr = Backend.expr
Backend.expr = _expr
_FNMAP_CACHE = {}


# ===========================================================================
# 阶段④ 第 2 项：结构体（type P { x: i32 }）+ 字段访问（p.x）
# 设计：不改变标量的 8 字节槽；结构体按 size 预留 ceil(size/8) 个连续槽。
#       字段地址 = rbp - 8*(first+N-1) + offset      （first 为第一个槽下标）
# ===========================================================================
STRUCTS = {}          # name -> {"fields": {fname: (offset, size)}, "size": S}
_SIZE = {"i8": 1, "u8": 1, "bool": 1, "i16": 2, "u16": 2,
         "i32": 4, "u32": 4, "i64": 8, "u64": 8, "usize": 8, "isize": 8}
_ALIGN = {1: 1, 2: 2, 4: 4, 8: 8}


def prescan_lets(be, node, seen_fn=None):
    """递归收集函数体内所有 LetStmt（含 if/while/match 内部），为其分配栈槽。"""
    t = type(node).__name__
    if t == "FnDecl":
        return                      # 不进入其他函数
    if t == "LetStmt":
        tname = _type_name(getattr(node, "type", None))
        if tname in STRUCTS:
            lay = STRUCTS[tname]
            N = (lay["size"] + 7) // 8
            first = be.nslots + 1
            be.nslots += N
            be.svars[node.name] = (first, N, lay)
        else:
            be.slot(node.name)
        return
    for f in getattr(node, "__dataclass_fields__", {}):
        v = getattr(node, f, None)
        if hasattr(v, "__dataclass_fields__"):
            prescan_lets(be, v)
        elif isinstance(v, (list, tuple)):
            for x in v:
                if hasattr(x, "__dataclass_fields__"):
                    prescan_lets(be, x)


def _type_name(tn):
    n = getattr(tn, "name", None)
    return n if isinstance(n, str) else None


def _build_layouts(items):
    global STRUCTS
    STRUCTS = {}
    for it in items:
        if type(it).__name__ != "TypeDecl" or getattr(it, "alias", None) is not None:
            continue
        off, maxa, fields = 0, 1, {}
        for fd in (getattr(it, "fields", None) or []):
            fname = getattr(fd, "name", None)
            tname = _type_name(getattr(fd, "type", None))
            size = _SIZE.get(tname, 8)
            align = _ALIGN.get(size, 8)
            off = (off + align - 1) // align * align
            fields[fname] = (off, size)
            off += size
            maxa = max(maxa, align)
        size = (off + maxa - 1) // maxa * maxa
        STRUCTS[it.name] = {"fields": fields, "size": size}


def _fld_addr(self, name, fname):
    """返回 [rbp+disp] 的 disp（字段相对 rbp 的偏移）"""
    first, N, lay = self.svars[name]
    off, size = lay["fields"][fname]
    return -8 * (first + N - 1) + off, size


def _expr2(self, n):
    if type(n).__name__ == "AttrExpr":
        obj = getattr(n, "obj", None)
        if type(obj).__name__ == "Var" and obj.name in getattr(self, "svars", {}):
            disp, size = _fld_addr(self, obj.name, n.name)
            if size == 8:
                self.e.e(b"\x48\x8b\x45" + struct.pack("<b", disp))
            else:
                self.e.e(b"\x8b\x45" + struct.pack("<b", disp))      # mov eax,[rbp+d]
            return
        raise NotImplementedError("field access on non-struct")
    return _orig_expr2(self, n)


def _stmt2(self, n, tag):
    t = type(n).__name__
    if t == "LetStmt" and getattr(self, "svars", None) is not None:
        tname = _type_name(getattr(n, "type", None))
        if tname in STRUCTS:
            lay = STRUCTS[tname]
            N = (lay["size"] + 7) // 8
            first = self.nslots + 1
            self.nslots += N
            self.svars[n.name] = (first, N, lay)
            return
    if t == "AssignStmt" and type(getattr(n, "target", None)).__name__ == "AttrExpr":
        tgt = n.target
        obj = getattr(tgt, "obj", None)
        if type(obj).__name__ == "Var" and obj.name in getattr(self, "svars", {}):
            disp, size = _fld_addr(self, obj.name, tgt.name)
            self.expr(n.value)
            if size == 8:
                self.e.e(b"\x48\x89\x45" + struct.pack("<b", disp))
            else:
                self.e.e(b"\x89\x45" + struct.pack("<b", disp))      # mov [rbp+d],eax
            return
    return _orig_stmt2(self, n, tag)


_orig_expr2 = Backend.expr
_orig_stmt2 = Backend.stmt
Backend.expr = _expr2
Backend.stmt = _stmt2
Backend.svars = {}


def compile_source(src, units=1, target="linux"):   # noqa: F811
    prog = parse_program(src)
    items = prog.items if hasattr(prog, "items") else prog
    _build_layouts(items)
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
        be.fn_name = fname
        be.svars = {}
        e.label("fn_" + fname)
        e.e(b"\x55")
        e.e(b"\x48\x89\xe5")
        params = getattr(fn, "params", []) or []
        for p in params:
            nm = getattr(p, "name", None) or (p[0] if isinstance(p, (list, tuple)) else None)
            be.slot(nm)
        body = block_items(fn.body)
        for st in body:
            prescan_lets(be, st)
        frame = ((be.nslots + SCRATCH) * 8 + 15) // 16 * 16
        if frame:
            e.e(b"\x48\x81\xec" + struct.pack("<I", frame))
        for i in range(len(params)):
            nm = getattr(params[i], "name", None) or params[i][0]
            e.e(ARG_REGS[i] + struct.pack("<b", be.slots[nm]))
        for i, st in enumerate(body):
            be.stmt(st, i)
        e.label(be.ep)
        if frame:
            e.e(b"\x48\x81\xc4" + struct.pack("<I", frame))
        e.e(b"\x5d")
        e.e(b"\xc3")
    return e.finish()
