#!/usr/bin/env python3
"""Step 2 dscc 后端：Ds -> x86_64 .bin/.elf，无 C/汇编器/链接器。"""
from __future__ import annotations
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from x86_64 import CodegenError, compile_source, write_outputs  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dscc --emit bin|elf", description="Step 2 x86_64 机器码后端")
    ap.add_argument("file")
    ap.add_argument("--emit", choices=["bin", "elf"], default="bin")
    ap.add_argument("-o", "--output")
    ap.add_argument("--entry", default="_start")
    args = ap.parse_args(argv)
    src_path = pathlib.Path(args.file)
    try:
        code = compile_source(src_path.read_text(encoding="utf-8"), src_path.name, args.entry)
        out = pathlib.Path(args.output or (src_path.stem + ("." + args.emit)))
        write_outputs(code, out, args.emit)
        print(f"✓ {out} ({len(code)} bytes)")
        return 0
    except FileNotFoundError:
        print(f"error: 文件不存在: {args.file}", file=sys.stderr); return 2
    except CodegenError as exc:
        loc = f"{args.file}:{exc.line}:{exc.col}: " if exc.line else f"{args.file}: "
        print(f"{loc}error[{exc.code}]: {exc.message}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
