#!/usr/bin/env python3
"""Step 5: Step 4 编译器 + 算术/比较/if-else。"""
from __future__ import annotations
import argparse
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
STEP4 = HERE.parent / "step4"
sys.path.insert(0, str(STEP4))
spec = importlib.util.spec_from_file_location("dscc_step4", STEP4 / "dscc_step4.py")
base = importlib.util.module_from_spec(spec)
sys.modules["dscc_step4"] = base
spec.loader.exec_module(base)
CodegenError = base.CodegenError
compile_source = base.compile_source
elf64 = base.elf64


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dscc-step5")
    ap.add_argument("file"); ap.add_argument("--emit", choices=["bin", "elf"], default="bin")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    p = pathlib.Path(args.file)
    try:
        code = base.compile_source(p.read_text(encoding="utf-8"), p.name)
        out = pathlib.Path(args.output or (p.stem + "." + args.emit))
        data = code if args.emit == "bin" else base.elf64(code)
        out.write_bytes(data)
        print(f"✓ {out} ({len(code)} bytes code, {len(data)} bytes output)")
        return 0
    except CodegenError as exc:
        loc = f"{p}:{exc.line}:{exc.col}: " if exc.line else f"{p}: "
        print(f"{loc}error[{exc.code}]: {exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
