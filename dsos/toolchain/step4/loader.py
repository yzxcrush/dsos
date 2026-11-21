#!/usr/bin/env python3
"""Step 4 DsOS 加载器：执行带栈帧/函数调用的 .bin。"""
from __future__ import annotations
import argparse
import pathlib
import sys

from machine import DsOSError, Machine


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dsos-stage4")
    ap.add_argument("bin")
    args = ap.parse_args(argv)
    code = pathlib.Path(args.bin).read_bytes()
    m = Machine()
    m.load(code)
    try:
        rc = m.run()
    except DsOSError as exc:
        print(f"dsos: error: {exc}", file=sys.stderr); return 1
    for chunk in m.outputs:
        sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
