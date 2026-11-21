#!/usr/bin/env python3
"""Step 4: Ds -> x86_64 函数调用 + 栈帧。

支持子集：无/有参数函数、return、let 局部变量、用户函数调用、sys_exit。
不经过 C/汇编器/链接器；直接生成字节。
"""
from __future__ import annotations
import argparse
import pathlib
import struct
import sys
from dataclasses import dataclass, field

from dsv01 import ast
from dsv01.parser import parse_program

ARG_REGS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
ARG_MOV_RAX = {"rdi": b"\x48\x89\xc7", "rsi": b"\x48\x89\xc6", "rdx": b"\x48\x89\xc2",
               "rcx": b"\x48\x89\xc1", "r8": b"\x49\x89\xc0", "r9": b"\x49\x89\xc1"}
ARG_MOV_IMM = {"rdi": b"\xbf", "rsi": b"\xbe", "rdx": b"\xba", "rcx": b"\xb9",
               "r8": b"\x41\xb8", "r9": b"\x41\xb9"}
STORE_PARAM = {"rdi": b"\x48\x89\x7d", "rsi": b"\x48\x89\x75", "rdx": b"\x48\x89\x55",
               "rcx": b"\x48\x89\x4d", "r8": b"\x4c\x89\x45", "r9": b"\x4c\x89\x4d"}
LOAD_REG = {"rax": b"\x48\x8b\x45", "rdi": b"\x48\x8b\x7d", "rsi": b"\x48\x8b\x75",
            "rdx": b"\x48\x8b\x55", "rcx": b"\x48\x8b\x4d"}


class CodegenError(Exception):
    def __init__(self, code: str, msg: str, line: int = 0, col: int = 0):
        super().__init__(msg)
        self.code, self.message, self.line, self.col = code, msg, line, col


@dataclass
class FnMeta:
    fn: ast.FnDecl
    slots: dict[str, int] = field(default_factory=dict)
    frame: int = 0


class Compiler:
    def __init__(self, prog: ast.Program):
        self.prog = prog
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str]] = []
        self.jumps: list[tuple[int, str, int]] = []  # (disp_pos, label, opcode bytes len)
        self.meta: dict[str, FnMeta] = {}
        self.serial = 0
        self.fns = {i.name: i for i in prog.items if isinstance(i, ast.FnDecl)}

    def scan(self, fn: ast.FnDecl) -> FnMeta:
        names = [p.name for p in fn.params]
        for st in fn.body.stmts if isinstance(fn.body, ast.Block) else []:
            if isinstance(st, ast.LetStmt) and st.name not in names:
                names.append(st.name)
        slots = {n: -8 * (i + 1) for i, n in enumerate(names)}
        frame = ((8 * len(names) + 15) // 16) * 16
        return FnMeta(fn, slots, frame)

    def emit(self, b: bytes) -> int:
        pos = len(self.code)
        self.code += b
        return pos

    def new_label(self, prefix: str) -> str:
        self.serial += 1
        return f"{prefix}_{self.serial}"

    def emit_jcc(self, cc: bytes, label: str) -> None:
        pos = self.emit(b"\x0f" + cc + b"\x00\x00\x00\x00")
        self.jumps.append((pos + 2, label, 6))

    def emit_jmp(self, label: str) -> None:
        pos = self.emit(b"\xe9\x00\x00\x00\x00")
        self.jumps.append((pos + 1, label, 5))

    def prologue(self, m: FnMeta) -> None:
        self.emit(b"\x55")                       # push rbp
        self.emit(b"\x48\x89\xe5")               # mov rbp, rsp
        if m.frame:
            self.emit(b"\x48\x81\xec" + struct.pack("<I", m.frame))
        for reg, p in zip(ARG_REGS, m.fn.params):
            self.emit(STORE_PARAM[reg] + bytes([m.slots[p.name] & 0xFF]))

    def epilogue(self) -> None:
        self.emit(b"\xc9")                       # leave
        self.emit(b"\xc3")                       # ret

    def local_store(self, off: int, value_in_rax: bool = True) -> None:
        self.emit(b"\x48\x89\x45" + bytes([off & 0xFF]))

    def local_load(self, off: int, reg: str = "rax") -> None:
        if reg not in LOAD_REG:
            raise CodegenError("E_STEP4_REG", f"不支持的局部变量目标寄存器 {reg}")
        self.emit(LOAD_REG[reg] + bytes([off & 0xFF]))

    def call(self, name: str) -> None:
        if name not in self.fns:
            raise CodegenError("E_STEP4_CALL", f"未知函数 `{name}`")
        pos = self.emit(b"\xe8\x00\x00\x00\x00")
        self.fixups.append((pos + 1, name))

    def eval_cond(self, e: ast.Expr, m: FnMeta) -> None:
        if isinstance(e, ast.Binary) and e.op in ("==", "!=", "<", ">"):
            self.eval_to_rax(e.left, m)
            self.emit(b"\x50")                       # push rax
            self.eval_to_rax(e.right, m)
            self.emit(b"\x59")                       # pop rcx
            self.emit(b"\x48\x39\xc1")             # cmp rcx, rax
            cc = {"==": b"\x94", "!=": b"\x95", "<": b"\x9c", ">": b"\x9f"}[e.op]
            self.emit(b"\x0f" + cc + b"\xc0")       # setcc al
            self.emit(b"\x0f\xb6\xc0")             # movzx eax, al
            return
        self.eval_to_rax(e, m)
        self.emit(b"\x48\x83\xf8\x00")           # cmp rax, 0
        self.emit(b"\x0f\x95\xc0")                 # setne al
        self.emit(b"\x0f\xb6\xc0")                 # movzx eax, al

    def eval_to_rax(self, e: ast.Expr, m: FnMeta) -> None:
        if isinstance(e, ast.Lit) and isinstance(e.value, int):
            self.emit(b"\xb8" + struct.pack("<I", int(e.value) & 0xFFFFFFFF)); return
        if isinstance(e, ast.Var):
            if e.name not in m.slots:
                raise CodegenError("E_STEP4_NAME", f"未定义变量 `{e.name}`", e.line, e.col)
            self.local_load(m.slots[e.name]); return
        if isinstance(e, ast.Binary) and e.op in ("+", "-"):
            self.eval_to_rax(e.left, m)
            self.emit(b"\x50")                       # push rax
            self.eval_to_rax(e.right, m)
            self.emit(b"\x59")                       # pop rcx
            if e.op == "+":
                self.emit(b"\x48\x01\xc8")         # add rax, rcx
            else:
                self.emit(b"\x48\x29\xc1")         # sub rcx, rax
                self.emit(b"\x48\x89\xc8")         # mov rax, rcx
            return
        if isinstance(e, ast.Unary) and e.op == "-":
            self.eval_to_rax(e.expr, m); self.emit(b"\x48\xf7\xd8"); return
        if isinstance(e, ast.Call) and isinstance(e.fn, ast.Var):
            self.emit_call(e.fn.name, e.args, m); return
        raise CodegenError("E_STEP5_EXPR", "Step 5 只支持字面量/变量/调用/+-", getattr(e, "line", 0))

    def eval_to_reg(self, e: ast.Expr, m: FnMeta, reg: str) -> None:
        if isinstance(e, ast.Lit) and isinstance(e.value, int):
            if reg == "rax":
                self.emit(b"\xb8" + struct.pack("<I", int(e.value) & 0xFFFFFFFF))
            else:
                self.emit(ARG_MOV_IMM[reg] + struct.pack("<I", int(e.value) & 0xFFFFFFFF))
            return
        if isinstance(e, ast.Var) and e.name in m.slots:
            self.local_load(m.slots[e.name], reg); return
        self.eval_to_rax(e, m)
        if reg != "rax":
            self.emit(ARG_MOV_RAX[reg])

    def emit_call(self, name: str, args: list[ast.Expr], m: FnMeta) -> None:
        if len(args) > 6:
            raise CodegenError("E_STEP4_ARGS", "Step 4 最多 6 个参数")
        for reg, arg in zip(ARG_REGS, args):
            self.eval_to_reg(arg, m, reg)
        self.call(name)

    def compile_cond(self, e: ast.Expr, m: FnMeta, then_lbl: str) -> None:
        if isinstance(e, ast.Binary) and e.op in ("==", "!=", "<", ">"):
            self.eval_to_rax(e.left, m)
            self.emit(b"\x50")
            self.eval_to_rax(e.right, m)
            self.emit(b"\x59")
            self.emit(b"\x48\x39\xc1")             # cmp rcx, rax
            cc = {"==": b"\x84", "!=": b"\x85", "<": b"\x8c", ">": b"\x8f"}[e.op]
            self.emit_jcc(cc, then_lbl)
            return
        self.eval_to_rax(e, m)
        self.emit(b"\x48\x83\xf8\x00")             # cmp rax,0
        self.emit_jcc(b"\x85", then_lbl)             # jne then

    def compile_if(self, e: ast.IfExpr, m: FnMeta) -> None:
        then_lbl = self.new_label("then")
        else_lbl = self.new_label("else")
        end_lbl = self.new_label("endif")
        self.compile_cond(e.cond, m, then_lbl)
        self.emit_jmp(else_lbl)
        self.labels[then_lbl] = len(self.code)
        self.compile_stmts(e.then_block.stmts if isinstance(e.then_block, ast.Block) else [], m)
        self.emit_jmp(end_lbl)
        self.labels[else_lbl] = len(self.code)
        if isinstance(e.else_, ast.Block):
            self.compile_stmts(e.else_.stmts, m)
        elif isinstance(e.else_, ast.IfExpr):
            self.compile_if(e.else_, m)
        self.labels[end_lbl] = len(self.code)

    def compile_stmts(self, stmts: list[ast.Stmt], m: FnMeta) -> None:
        for st in stmts:
            if isinstance(st, ast.LetStmt):
                if st.value is None:
                    raise CodegenError("E_STEP4_LET", "let 必须有初值", st.line, st.col)
                self.eval_to_rax(st.value, m)
                self.local_store(m.slots[st.name])
            elif isinstance(st, ast.ReturnStmt):
                if st.value is not None:
                    self.eval_to_rax(st.value, m)
                else:
                    self.emit(b"\xb8\x00\x00\x00\x00")
                self.epilogue()
                return
            elif isinstance(st, ast.ExprStmt) and isinstance(st.expr, ast.IfExpr):
                self.compile_if(st.expr, m)
            elif isinstance(st, ast.ExprStmt) and isinstance(st.expr, ast.Call) and isinstance(st.expr.fn, ast.Var):
                if st.expr.fn.name == "sys_exit":
                    if len(st.expr.args) != 1:
                        raise CodegenError("E_STEP4_ARGS", "sys_exit(code)")
                    self.eval_to_rax(st.expr.args[0], m)
                    self.emit(b"\x48\x89\xc7")
                    self.emit(b"\xb8\x3c\x00\x00\x00")
                    self.emit(b"\x0f\x05")
                    return
                self.emit_call(st.expr.fn.name, st.expr.args, m)
            else:
                raise CodegenError("E_STEP5_STMT", "Step 5 不支持的语句", getattr(st, "line", 0))

    def compile_fn(self, fn: ast.FnDecl) -> None:
        m = self.meta[fn.name]
        self.labels[fn.name] = len(self.code)
        self.prologue(m)
        self.compile_stmts(fn.body.stmts if isinstance(fn.body, ast.Block) else [], m)
        self.emit(b"\xb8\x00\x00\x00\x00")
        self.epilogue()

    def compile(self) -> bytes:
        entry = "_start"
        if entry not in self.fns:
            raise CodegenError("E_STEP4_ENTRY", "找不到 `_start`")
        for fn in self.fns.values():
            self.meta[fn.name] = self.scan(fn)
        # _start 先布局，其余函数随后
        order = [entry] + [n for n in self.fns if n != entry]
        for n in order:
            self.compile_fn(self.fns[n])
        for at, name in self.fixups:
            if name not in self.labels:
                raise CodegenError("E_STEP4_LABEL", f"未解析函数 `{name}`")
            rel = self.labels[name] - (at + 4)
            self.code[at:at + 4] = struct.pack("<i", rel)
        for at, label, op_len in self.jumps:
            if label not in self.labels:
                raise CodegenError("E_STEP5_LABEL", f"未解析标签 `{label}`")
            rel = self.labels[label] - (at + 4)
            self.code[at:at + 4] = struct.pack("<i", rel)
        return bytes(self.code)


def compile_source(src: str, filename: str = "<ds>") -> bytes:
    try:
        prog = parse_program(src, filename)
    except Exception as exc:
        raise CodegenError("E_STEP4_PARSE", str(exc)) from exc
    return Compiler(prog).compile()


def elf64(code: bytes, base: int = 0x400000) -> bytes:
    ehsize, phentsize = 64, 56
    entry = base + ehsize + phentsize
    ident = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
    ehdr = ident + struct.pack("<HHIQQQIHHHHHH", 2, 0x3E, 1, entry, ehsize, 0, 0, ehsize, phentsize, 1, 0, 0, 0)
    total = ehsize + phentsize + len(code)
    phdr = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, total, total, 0x1000)
    return ehdr + phdr + code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dscc-step4")
    ap.add_argument("file"); ap.add_argument("--emit", choices=["bin", "elf"], default="bin")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    p = pathlib.Path(args.file)
    try:
        code = compile_source(p.read_text(encoding="utf-8"), p.name)
        out = pathlib.Path(args.output or (p.stem + "." + args.emit))
        data = code if args.emit == "bin" else elf64(code)
        out.write_bytes(data)
        print(f"✓ {out} ({len(code)} bytes code, {len(data)} bytes output)")
        return 0
    except CodegenError as exc:
        loc = f"{p}:{exc.line}:{exc.col}: " if exc.line else f"{p}: "
        print(f"{loc}error[{exc.code}]: {exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
