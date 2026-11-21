#!/usr/bin/env python3
"""Step 3: DsOS 最小加载器（可移植 x86_64 子集 VM）。

接口语义：
  load_and_run(code: @raw u8, len: u64) -> !

在 x86_64/Linux 上请用 loader_native.py 做真实 mmap+跳转；
本文件用于没有 x86_64 执行环境的主机（例如 aarch64 Termux）验证 Step 2 产物。
"""
from __future__ import annotations
import argparse
import pathlib
import struct
import sys

BASE = 0x400000
MEM_SIZE = 1 << 16


class DsOSError(Exception):
    pass


class Machine:
    def __init__(self):
        self.mem = bytearray(MEM_SIZE)
        self.regs = {"rax": 0, "rdi": 0, "rsi": 0, "rdx": 0, "rip": 0}
        self.steps = 0
        self.exit_code: int | None = None
        self.outputs: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.outputs.append(data)

    def syscall(self) -> None:
        if self.regs["rax"] == 1:  # write
            fd = self.regs["rdi"]
            if fd not in (1, 2):
                raise DsOSError(f"unsupported fd {fd}")
            off = self.regs["rsi"] - BASE
            n = self.regs["rdx"]
            if off < 0 or off + n > len(self.mem):
                raise DsOSError("sys_write buffer out of range")
            self.write(bytes(self.mem[off:off + n]))
            self.regs["rax"] = n
        elif self.regs["rax"] == 60:  # exit
            self.exit_code = self.regs["rdi"]
        else:
            raise DsOSError(f"unsupported syscall {self.regs['rax']}")

    def load(self, code: bytes) -> None:
        if len(code) > MEM_SIZE:
            raise DsOSError("code too large")
        self.mem[:len(code)] = code
        self.regs["rip"] = 0

    def step(self) -> None:
        self.steps += 1
        if self.steps > 100000:
            raise DsOSError("instruction limit exceeded")
        rip = self.regs["rip"]
        if rip < 0 or rip >= len(self.mem):
            raise DsOSError(f"rip out of range: 0x{rip:x}")
        op = self.mem[rip]
        if op == 0xB8:
            self.regs["rax"] = struct.unpack_from("<I", self.mem, rip + 1)[0]
            self.regs["rip"] = rip + 5
        elif op == 0xBF:
            self.regs["rdi"] = struct.unpack_from("<I", self.mem, rip + 1)[0]
            self.regs["rip"] = rip + 5
        elif op == 0xBA:
            self.regs["rdx"] = struct.unpack_from("<I", self.mem, rip + 1)[0]
            self.regs["rip"] = rip + 5
        elif self.mem[rip:rip + 3] == b"\x48\x8d\x35":
            disp = struct.unpack_from("<i", self.mem, rip + 3)[0]
            self.regs["rsi"] = BASE + rip + 7 + disp
            self.regs["rip"] = rip + 7
        elif self.mem[rip:rip + 2] == b"\x0f\x05":
            self.regs["rip"] = rip + 2
            self.syscall()
        elif self.mem[rip:rip + 2] == b"\x31\xff":
            self.regs["rdi"] = 0
            self.regs["rip"] = rip + 2
        elif op == 0xC3:
            self.exit_code = 0
        elif op == 0xE9:
            rel = struct.unpack_from("<i", self.mem, rip + 1)[0]
            self.regs["rip"] = rip + 5 + rel
        elif op == 0xEB:
            rel = struct.unpack_from("<b", self.mem, rip + 1)[0]
            self.regs["rip"] = rip + 2 + rel
        else:
            raise DsOSError(f"unsupported opcode 0x{op:02x} at 0x{rip:x}")

    def run(self) -> int:
        while self.exit_code is None:
            self.step()
        return self.exit_code


def load_and_run(code: bytes) -> int:
    m = Machine()
    m.load(code)
    rc = m.run()
    for chunk in m.outputs:
        sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dsos-loader", description="DsOS Step3 可移植加载器")
    ap.add_argument("bin")
    args = ap.parse_args(argv)
    code = pathlib.Path(args.bin).read_bytes()
    try:
        return load_and_run(code)
    except (OSError, DsOSError) as exc:
        print(f"dsos: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
