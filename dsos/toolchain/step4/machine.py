"""Step 4: DsOS 最小 x86_64 子集 VM（栈帧/函数调用/局部变量）。"""
from __future__ import annotations
import struct

BASE = 0x400000
MEM_SIZE = 1 << 20
STACK_TOP = BASE + 0x80000


class DsOSError(Exception):
    pass


class Machine:
    def __init__(self):
        self.mem = bytearray(MEM_SIZE)
        self.r = {k: 0 for k in ("rax", "rdi", "rsi", "rdx", "rcx", "r8", "r9", "rbp", "rsp", "rip")}
        self.r["rsp"] = STACK_TOP
        self.exit_code: int | None = None
        self.steps = 0
        self.outputs: list[bytes] = []
        self.flags = {"eq": False, "lt": False}

    def idx(self, addr: int) -> int:
        if addr < BASE or addr >= BASE + MEM_SIZE:
            raise DsOSError(f"address out of range: 0x{addr:x}")
        return addr - BASE

    def read64(self, addr: int) -> int:
        i = self.idx(addr)
        return struct.unpack_from("<Q", self.mem, i)[0]

    def write64(self, addr: int, v: int) -> None:
        i = self.idx(addr)
        struct.pack_into("<Q", self.mem, i, v & 0xFFFFFFFFFFFFFFFF)

    def push(self, v: int) -> None:
        self.r["rsp"] -= 8
        self.write64(self.r["rsp"], v)

    def pop(self) -> int:
        v = self.read64(self.r["rsp"])
        self.r["rsp"] += 8
        return v

    def load(self, code: bytes) -> None:
        if len(code) > MEM_SIZE // 2:
            raise DsOSError("code too large")
        self.mem[:len(code)] = code
        self.r["rip"] = 0

    def syscall(self) -> None:
        n = self.r["rax"]
        if n == 1:
            fd = self.r["rdi"]
            if fd not in (1, 2):
                raise DsOSError(f"unsupported fd {fd}")
            i = self.idx(self.r["rsi"])
            nbytes = self.r["rdx"]
            self.outputs.append(bytes(self.mem[i:i + nbytes]))
            self.r["rax"] = nbytes
        elif n == 60:
            self.exit_code = self.r["rdi"]
        else:
            raise DsOSError(f"unsupported syscall {n}")

    def step(self) -> None:
        self.steps += 1
        if self.steps > 200000:
            raise DsOSError("instruction limit")
        rip = self.r["rip"]
        m = self.mem
        if rip < 0 or rip >= len(m):
            raise DsOSError(f"rip out of range 0x{rip:x}")
        b = m[rip]
        if b == 0x50:                     # push rax
            self.push(self.r["rax"]); self.r["rip"] = rip + 1
        elif b == 0x59:                   # pop rcx
            self.r["rcx"] = self.pop(); self.r["rip"] = rip + 1
        elif m[rip:rip + 3] == b"\x48\x01\xc8":  # add rax, rcx
            self.r["rax"] = (self.r["rax"] + self.r["rcx"]) & 0xFFFFFFFFFFFFFFFF; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x48\x29\xc1":  # sub rcx, rax
            self.r["rcx"] = (self.r["rcx"] - self.r["rax"]) & 0xFFFFFFFFFFFFFFFF; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x48\x89\xc8":  # mov rax, rcx
            self.r["rax"] = self.r["rcx"]; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x48\xf7\xd8":  # neg rax
            self.r["rax"] = (-self.r["rax"]) & 0xFFFFFFFFFFFFFFFF; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x48\x39\xc1":  # cmp rcx, rax
            a, b2 = self.r["rcx"], self.r["rax"]
            self.flags["eq"] = a == b2; self.flags["lt"] = a < b2; self.r["rip"] = rip + 3
        elif m[rip:rip + 4] == b"\x48\x83\xf8\x00":  # cmp rax, 0
            self.flags["eq"] = self.r["rax"] == 0; self.flags["lt"] = self.r["rax"] < 0; self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x0f\x94\xc0":  # sete al
            self.r["rax"] = 1 if self.flags["eq"] else 0; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x0f\x95\xc0":  # setne al
            self.r["rax"] = 0 if self.flags["eq"] else 1; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x0f\x9c\xc0":  # setl al
            self.r["rax"] = 1 if self.flags["lt"] else 0; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x0f\x9f\xc0":  # setg al
            self.r["rax"] = 1 if (not self.flags["lt"] and not self.flags["eq"]) else 0; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x0f\xb6\xc0":  # movzx eax, al
            self.r["rax"] &= 0xFF; self.r["rip"] = rip + 3
        elif m[rip:rip + 2] == b"\x0f\x84":     # je rel32
            rel = struct.unpack_from("<i", m, rip + 2)[0]
            self.r["rip"] = (rip + 6 + rel) if self.flags["eq"] else rip + 6
        elif m[rip:rip + 2] == b"\x0f\x85":     # jne
            rel = struct.unpack_from("<i", m, rip + 2)[0]
            self.r["rip"] = (rip + 6 + rel) if not self.flags["eq"] else rip + 6
        elif m[rip:rip + 2] == b"\x0f\x8c":     # jl
            rel = struct.unpack_from("<i", m, rip + 2)[0]
            self.r["rip"] = (rip + 6 + rel) if self.flags["lt"] else rip + 6
        elif m[rip:rip + 2] == b"\x0f\x8f":     # jg
            rel = struct.unpack_from("<i", m, rip + 2)[0]
            self.r["rip"] = (rip + 6 + rel) if (not self.flags["lt"] and not self.flags["eq"]) else rip + 6
        elif b == 0xE9:                   # jmp rel32
            rel = struct.unpack_from("<i", m, rip + 1)[0]; self.r["rip"] = rip + 5 + rel
        elif b == 0x55:                     # push rbp
            self.push(self.r["rbp"]); self.r["rip"] = rip + 1
        elif m[rip:rip + 3] == b"\x48\x89\xe5":  # mov rbp,rsp
            self.r["rbp"] = self.r["rsp"]; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x48\x81\xec":  # sub rsp, imm32
            n = struct.unpack_from("<I", m, rip + 3)[0]
            self.r["rsp"] -= n; self.r["rip"] = rip + 7
        elif m[rip:rip + 3] == b"\x48\x83\xec":  # sub rsp, imm8
            n = m[rip + 3]; self.r["rsp"] -= n; self.r["rip"] = rip + 4
        elif b == 0xC9:                   # leave
            self.r["rsp"] = self.r["rbp"]; self.r["rbp"] = self.pop(); self.r["rip"] = rip + 1
        elif b == 0xC3:                   # ret
            self.r["rip"] = self.pop()
        elif b == 0xE8:                   # call rel32
            rel = struct.unpack_from("<i", m, rip + 1)[0]
            self.push(rip + 5); self.r["rip"] = rip + 5 + rel
        elif m[rip:rip + 3] == b"\x48\x89\x45":  # mov [rbp+disp], rax
            self.write64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0], self.r["rax"]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x8b\x45":  # mov rax,[rbp+disp]
            self.r["rax"] = self.read64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x89\x7d":  # mov [rbp+disp], rdi
            self.write64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0], self.r["rdi"]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x89\x75":  # rsi
            self.write64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0], self.r["rsi"]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x89\x55":  # rdx
            self.write64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0], self.r["rdx"]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x89\x4d":  # rcx
            self.write64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0], self.r["rcx"]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x4c\x89\x45":  # r8
            self.write64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0], self.r["r8"]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x4c\x89\x4d":  # r9
            self.write64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0], self.r["r9"]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x8b\x7d":  # mov rdi,[rbp+disp]
            self.r["rdi"] = self.read64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x8b\x75":
            self.r["rsi"] = self.read64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x8b\x55":
            self.r["rdx"] = self.read64(self.r["rbp"] + struct.unpack_from("<b", m, rip + 3)[0]); self.r["rip"] = rip + 4
        elif m[rip:rip + 3] == b"\x48\x89\xc7":  # mov rdi,rax
            self.r["rdi"] = self.r["rax"]; self.r["rip"] = rip + 3
        elif m[rip:rip + 3] == b"\x48\x89\xc6":
            self.r["rsi"] = self.r["rax"]; self.r["rip"] = rip + 3
        elif m[rip:rip + 2] == b"\x0f\x05":
            self.r["rip"] = rip + 2; self.syscall()
        elif b == 0xB8:
            self.r["rax"] = struct.unpack_from("<I", m, rip + 1)[0]; self.r["rip"] = rip + 5
        elif b == 0xBF:
            self.r["rdi"] = struct.unpack_from("<I", m, rip + 1)[0]; self.r["rip"] = rip + 5
        elif b == 0xBE:
            self.r["rsi"] = struct.unpack_from("<I", m, rip + 1)[0]; self.r["rip"] = rip + 5
        elif b == 0xBA:
            self.r["rdx"] = struct.unpack_from("<I", m, rip + 1)[0]; self.r["rip"] = rip + 5
        else:
            raise DsOSError(f"unsupported opcode 0x{b:02x} at 0x{rip:x}")

    def run(self) -> int:
        while self.exit_code is None:
            if self.r["rip"] == 0 and self.steps > 0 and self.r["rsp"] == STACK_TOP:
                # 没有 sys_exit 且 ret 回到 0：按 0 退出
                self.exit_code = 0
                break
            self.step()
        return self.exit_code


def load_and_run(code: bytes) -> tuple[int, bytes]:
    m = Machine(); m.load(code); rc = m.run()
    return rc, b"".join(m.outputs)
