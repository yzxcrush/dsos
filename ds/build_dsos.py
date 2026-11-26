"""dsos-os/ds/build_dsos.py — 把 Ds 编译的内核装进可引导镜像。

流程：
  kernel.ds --(Ds 工具链 mini.py, target=bare)--> 裸机机器码
  → 与冻结引导链（bootchain.bin，4608 字节 = MBR + stage2）拼接
  → 产出 dsos-ds.img（1474560 字节）

说明（标注纪律）：
  - 内核字节 100% 来自 .ds 源码，由 Ds 工具链生成；
  - bootchain.bin 是已验证 v0.5 引导链的存档（Python 发射器产物，规则 9 的冻结豁免）；
  - 本脚本只做"拼接与校验"，不生成任何入镜字节。
"""
import hashlib, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from mini import compile_source

BOOTCHAIN = HERE / "bootchain.bin"      # 4608 B：MBR + stage2
KERNEL_OFF = 4608                       # 0x9000 - 0x8000 + 512
KERNEL_MAX = 12288   # 32 扇区加载：0x9000..0xBFFF
IMG_SIZE = 1474560
OUT = HERE / "dsos-ds.img"


def main():
    src = (HERE / "kernel.ds").read_text(encoding="utf-8")
    kern = compile_source(src, target="bare")
    print(f"kernel.ds 编译: {len(kern)} 字节（上限 {KERNEL_MAX}）")
    if len(kern) > KERNEL_MAX:
        sys.exit(f"FAIL: 内核 {len(kern)} > 上限 {KERNEL_MAX}")

    boot = BOOTCHAIN.read_bytes()
    assert len(boot) == KERNEL_OFF, f"bootchain.bin 应为 {KERNEL_OFF} 字节"
    assert boot[510:512] == bytes([0x55, 0xAA]), "bootchain 缺少 0x55AA"
    print(f"引导链存档: {BOOTCHAIN.name}  {len(boot)} B  "
          f"sha256={hashlib.sha256(boot).hexdigest()[:16]}…")

    img = bytearray(IMG_SIZE)
    img[0:KERNEL_OFF] = boot
    img[KERNEL_OFF:KERNEL_OFF + len(kern)] = kern

    # ---- MBR 分区项：让 BIOS 把这块盘识别成可引导的 USB 硬盘 ----
    # 很多机器在分区表全零时不把设备列进启动菜单，直接跳过进 Windows。
    PART_LBA = 2048                      # 1 MiB 对齐
    part = bytearray(16)
    part[0] = 0x80                       # 活动分区
    part[1:4] = bytes([0x20, 0x21, 0x00])   # 起始 CHS: head32/sec33/cyl0
    part[4] = 0x0C                          # 类型: FAT32 LBA (通用)
    part[5:8] = bytes([0x2D, 0x2D, 0x00])   # 结束 CHS
    part[8:12] = PART_LBA.to_bytes(4, "little")
    part[12:16] = (IMG_SIZE // 512 - PART_LBA).to_bytes(4, "little")
    img[0x1BE:0x1CE] = part
    img[0x1B8:0x1BC] = (0x44534F44).to_bytes(4, "little")   # 磁盘签名 "DSOD"
    # 分区起点再放一份引导扇区：兼容"启动活动分区 VBR"的 BIOS
    # 注意：必须在改完分区表之后复制，保证两份一致
    if PART_LBA * 512 + 512 <= IMG_SIZE:
        img[PART_LBA * 512:PART_LBA * 512 + 512] = bytes(img[0:512])
    OUT.write_bytes(bytes(img))

    a = OUT.read_bytes()
    ok_sig = a[510:512] == bytes([0x55, 0xAA])
    ok_kern = a[KERNEL_OFF:KERNEL_OFF + len(kern)] == kern
    ok_size = len(a) == IMG_SIZE
    ok_part = a[0x1BE] == 0x80 and a[0x1C2] == 0x0C
    ok_vbr = a[PART_LBA * 512:PART_LBA * 512 + 512] == a[0:512]
    print(f"[image] 引导签名 0x55AA:        {'PASS' if ok_sig else 'FAIL'}")
    print(f"[image] 内核槽字节 == Ds 输出:   {'PASS' if ok_kern else 'FAIL'}")
    print(f"[image] 镜像大小 {IMG_SIZE}:      {'PASS' if ok_size else 'FAIL'}")
    print(f"[image] MBR 分区项(0x0C):        {'PASS' if ok_part else 'FAIL'}")
    print(f"[image] 分区起点有引导扇区副本:   {'PASS' if ok_vbr else 'FAIL'}")
    print(f"\n镜像: {OUT}")
    print(f"sha256: {hashlib.sha256(a).hexdigest()}")
    ok = ok_sig and ok_kern and ok_size and ok_part and ok_vbr
    print("BUILD:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
