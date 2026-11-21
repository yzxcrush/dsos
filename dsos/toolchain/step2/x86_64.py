"""Step 2: 受限 Ds -> x86_64 机器码后端。

只处理：无参数、无局部变量、单/少量 sys_write/sys_exit 的函数。
不经过 C、汇编器、链接器；直接生成字节。
"""
from __future__ import annotations
import pathlib
import struct
from dataclasses import dataclass

from dsv01 import ast
from dsv01.parser import parse_program


class CodegenError(Exception):
    def __init__(self, code: str, message: str, line: int = 0, col: int = 0):
        super().__init__(message)
        self.code, self.message, self.line, self.col = code, message, line, col


@dataclass
class FnIR:
    name: str
    calls: list[tuple[str, list[object]]]
    line: int
    col: int


class Encoder:
    def __init__(self):
        self.code = bytearray()

    def mov_eax(self, v: int) -> None:
        self.code += b"\xb8" + struct.pack("<I", v & 0xFFFFFFFF)

    def mov_edi(self, v: int) -> None:
        self.code += b"\xbf" + struct.pack("<I", v & 0xFFFFFFFF)

    def mov_edx(self, v: int) -> None:
        self.code += b"\xba" + struct.pack("<I", v & 0xFFFFFFFF)

    def lea_rsi_rip(self) -> int:
        pos = len(self.code)
        self.code += b"\x48\x8d\x35\x00\x00\x00\x00"
        return pos + 3

    def patch_disp32(self, at: int, disp: int) -> None:
        self.code[at:at + 4] = struct.pack("<i", disp)

    def xor_edi_edi(self) -> None:
        self.code += b"\x31\xff"

    def syscall(self) -> None:
        self.code += b"\x0f\x05"

    def jmp_rel32(self, delta: int) -> None:
        self.code += b"\xe9" + struct.pack("<i", delta)

    def jmp_rel8(self, delta: int) -> None:
        self.code += b"\xeb" + bytes([delta & 0xFF])

    def ret(self) -> None:
        self.code += b"\xc3"


class Program:
    def __init__(self, fn: ast.FnDecl):
        self.fn = fn
        self.msg = b""
        self.calls: list[tuple[str, list[object]]] = []

    def extract(self) -> None:
        if self.fn.params:
            raise CodegenError("E_STEP2_PARAMS", "Step 2 只支持无参数函数", self.fn.line, self.fn.col)
        body = self.fn.body
        if not isinstance(body, ast.Block):
            raise CodegenError("E_STEP2_BODY", "Step 2 只支持块函数体", self.fn.line, self.fn.col)
        for st in body.stmts:
            if isinstance(st, ast.LetStmt):
                raise CodegenError("E_STEP2_LOCALS", "Step 2 不支持局部变量", st.line, st.col)
            if not isinstance(st, ast.ExprStmt) or not isinstance(st.expr, ast.Call):
                raise CodegenError("E_STEP2_STMT", "Step 2 只支持 syscall 调用语句", st.line, st.col)
            call = st.expr
            if not isinstance(call.fn, ast.Var):
                raise CodegenError("E_STEP2_CALL", "Step 2 只支持命名 syscall", call.line, call.col)
            name = call.fn.name
            if name not in ("sys_write", "sys_exit"):
                raise CodegenError("E_STEP2_SYSCALL", f"Step 2 不支持 syscall `{name}`", call.line, call.col)
            self.calls.append((name, list(call.args)))

    def compile(self) -> bytes:
        self.extract()
        enc = Encoder()
        # 数据先暂定放在代码后；收集 write 消息
        writes = [c for c in self.calls if c[0] == "sys_write"]
        exits = [c for c in self.calls if c[0] == "sys_exit"]
        if len(writes) > 1:
            raise CodegenError("E_STEP2_WRITES", "Step 2 只支持一个 sys_write")
        msg = b""
        if writes:
            _, args = writes[0]
            if len(args) != 2 or not isinstance(args[0], ast.Lit) or not isinstance(args[0].value, int):
                raise CodegenError("E_STEP2_ARGS", "Step 2 sys_write(fd, \"literal\")", writes[0][1][0].line if writes[0][1] else 0)
            if not isinstance(args[1], ast.Lit) or not isinstance(args[1].value, str):
                raise CodegenError("E_STEP2_ARGS", "Step 2 sys_write 第二个参数必须是字符串字面量")
            fd = int(args[0].value)
            msg = args[1].value.encode("utf-8")
            enc.mov_eax(1)
            enc.mov_edi(fd)
            disp_pos = enc.lea_rsi_rip()
            enc.mov_edx(len(msg))
            enc.syscall()
        # exit：显式参数或默认 0
        code = 0
        if exits:
            _, args = exits[0]
            if len(args) != 1 or not isinstance(args[0], ast.Lit) or not isinstance(args[0].value, int):
                raise CodegenError("E_STEP2_ARGS", "Step 2 sys_exit(code)")
            code = int(args[0].value)
        enc.mov_eax(60)
        if code == 0:
            enc.xor_edi_edi()
        else:
            enc.mov_edi(code)
        enc.syscall()
        enc.ret()  # 不可达，但保留 ret 指令覆盖
        msg_off = len(enc.code)
        if writes:
            enc.patch_disp32(disp_pos, msg_off - (disp_pos - 3 + 7))
        enc.code += msg
        return bytes(enc.code)


def find_entry(prog: ast.Program, entry: str = "_start") -> ast.FnDecl:
    for item in prog.items:
        if isinstance(item, ast.FnDecl) and item.name == entry:
            return item
    raise CodegenError("E_STEP2_ENTRY", f"找不到入口函数 `{entry}`")


def compile_source(src: str, filename: str = "<ds>", entry: str = "_start") -> bytes:
    try:
        prog = parse_program(src, filename)
    except Exception as exc:
        raise CodegenError("E_STEP2_PARSE", str(exc)) from exc
    fn = find_entry(prog, entry)
    return Program(fn).compile()


def elf64(code: bytes, base: int = 0x400000) -> bytes:
    ehsize, phentsize = 64, 56
    entry = base + ehsize + phentsize
    ident = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
    ehdr = ident + struct.pack("<HHIQQQIHHHHHH",
        2, 0x3E, 1, entry, ehsize, 0, 0, ehsize, phentsize, 1, 0, 0, 0)
    total = ehsize + phentsize + len(code)
    phdr = struct.pack("<IIQQQQQQ", 1, 5, 0, base, base, total, total, 0x1000)
    return ehdr + phdr + code


def write_outputs(code: bytes, out: pathlib.Path, emit: str) -> list[pathlib.Path]:
    written = []
    if emit == "bin":
        out.write_bytes(code); written.append(out)
    elif emit == "elf":
        out.write_bytes(elf64(code)); written.append(out)
    else:
        raise CodegenError("E_STEP2_EMIT", f"未知输出格式 {emit}")
    return written
