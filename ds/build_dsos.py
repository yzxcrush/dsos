"""dsos-os/ds/build_dsos.py — 把 Ds 编译的内核装进可引导镜像。

流程：
  kernel.ds --(Ds 工具链 mini.py, target=bare)--> 裸机机器码
  → 写入冻结引导链镜像的内核槽（0x9000 / 文件偏移 4608）
  → 产出 dsos-ds.img

说明（标注纪律）：
  - 内核字节 100% 来自 .ds 源码，由 Ds 工具链生成；
  - boot sector / stage2 沿用已验证的冻结引导链（Python 发射器产物，规则 9 的冻结豁免）；
  - 本脚本只做"拼接与校验"，不生成任何入镜字节。
"""
import hashlib, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from mini import compile_source

ROOT = HERE.parents[1]                      # default-workspace
FROZEN = (ROOT / "交接" / "_publish_dsos" / "dsos" / "images" / "x86_64"
          / "dsos-x86_64-shell.img")
KERNEL_OFF = 4608                           # 0x9000 - 0x8000 + 512
KERNEL_MAX = 4096
OUT = HERE / "dsos-ds.img"


def main():
    src = (HERE / "kernel.ds").read_text(encoding="utf-8")
    kern = compile_source(src, target="bare")
    print(f"kernel.ds 编译: {len(kern)} 字节")
    if len(kern) > KERNEL_MAX:
        sys.exit(f"FAIL: 内核 {len(kern)} > 上限 {KERNEL_MAX}")

    img = bytearray(FROZEN.read_bytes())
    print(f"冻结引导链镜像: {FROZEN.name}  {len(img)} 字节  "
          f"sha256={hashlib.sha256(img).hexdigest()[:16]}…")
    img[KERNEL_OFF:KERNEL_OFF + len(kern)] = kern
    OUT.write_bytes(bytes(img))

    # ---- 结构校验 ----
    a = OUT.read_bytes()
    ok_sig = a[510:512] == b"\x55\xaa"
    ok_kern = a[KERNEL_OFF:KERNEL_OFF + len(kern)] == kern
    ok_size = len(a) == len(img)
    print(f"[image] 引导签名 0x55AA:        {'PASS' if ok_sig else 'FAIL'}")
    print(f"[image] 内核槽字节 == Ds 输出:   {'PASS' if ok_kern else 'FAIL'}")
    print(f"[image] 镜像大小未变:            {'PASS' if ok_size else 'FAIL'}")
    print(f"\n镜像: {OUT}")
    print(f"大小: {len(a)} 字节")
    print(f"sha256: {hashlib.sha256(a).hexdigest()}")
    ok = ok_sig and ok_kern and ok_size
    print("BUILD:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
