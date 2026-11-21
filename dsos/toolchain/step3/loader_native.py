#!/usr/bin/env python3
"""Step 3 native: x86_64 mmap RWX -> copy -> jump.

只在 x86_64 Linux 上可用；这是 DsOS 用户态加载器的真实执行路径。
"""
from __future__ import annotations
import ctypes
import mmap
import pathlib
import platform
import sys


def load_and_run(code: bytes) -> None:
    if platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError(f"native loader requires x86_64, got {platform.machine()}")
    mm = mmap.mmap(-1, len(code), prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)
    mm.write(code)
    fn = ctypes.CFUNCTYPE(None)(ctypes.addressof(ctypes.c_char.from_buffer(mm)))
    fn()  # .bin 以 exit syscall 结束


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: loader_native.py file.bin", file=sys.stderr); return 2
    code = pathlib.Path(argv[0]).read_bytes()
    try:
        load_and_run(code)
        return 0
    except Exception as exc:
        print(f"dsos-native: error: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
