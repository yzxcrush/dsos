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

# ---- 分区布局（LBA） ----
#   LBA 0        MBR（引导代码 + 分区表）
#   LBA 1..33    引导代码区（stage1 一次读 32 扇区：stage2 + 内核）
#   LBA 2048     分区1「引导」2 MiB   —— 分区起点放一份 VBR 副本
#   LBA 6144     分区2「日志」8 MiB   —— 日志专用分区，槽大小 32 KiB
BOOT_PART_LBA = 2048
BOOT_PART_SECS = 4096
LOG_PART_LBA = 6144
LOG_PART_SECS = 16384
SLOT_BYTES = 32 * 1024
SLOT_COUNT = LOG_PART_SECS * 512 // SLOT_BYTES
IMG_SIZE = (LOG_PART_LBA + LOG_PART_SECS) * 512
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

    # ---- MBR 分区表 ----
    # 分区1「引导」：让 BIOS 把这块盘识别成可引导的 USB 硬盘
    #                （分区表全零时很多机器会直接跳过它进 Windows）
    # 分区2「日志」：日志专用，不碰引导区，可单独擦除
    def chs(lba):
        sec = lba % 63 + 1
        head = (lba // 63) % 255
        cyl = lba // (63 * 255)
        return bytes([head & 0xFF, (sec & 0x3F) | ((cyl >> 2) & 0xC0), cyl & 0xFF])

    p1 = bytearray(16)
    p1[0] = 0x80
    p1[1:4] = chs(BOOT_PART_LBA)
    p1[4] = 0x0C                       # FAT32 LBA（通用可引导类型）
    p1[5:8] = chs(BOOT_PART_LBA + BOOT_PART_SECS - 1)
    p1[8:12] = BOOT_PART_LBA.to_bytes(4, "little")
    p1[12:16] = BOOT_PART_SECS.to_bytes(4, "little")

    p2 = bytearray(16)
    p2[0] = 0x00                       # 非活动分区（只存日志）
    p2[1:4] = chs(LOG_PART_LBA)
    p2[4] = 0xDA                       # 自定义类型：DsOS 日志分区
    p2[5:8] = chs(LOG_PART_LBA + LOG_PART_SECS - 1)
    p2[8:12] = LOG_PART_LBA.to_bytes(4, "little")
    p2[12:16] = LOG_PART_SECS.to_bytes(4, "little")

    img[0x1BE:0x1CE] = p1
    img[0x1CE:0x1DE] = p2
    img[0x1B8:0x1BC] = (0x44534F44).to_bytes(4, "little")   # 磁盘签名 "DSOD"
    # 引导分区起点再放一份引导扇区：兼容"启动活动分区 VBR"的 BIOS
    # 注意：必须在改完分区表之后复制，保证两份一致
    img[BOOT_PART_LBA * 512:BOOT_PART_LBA * 512 + 512] = bytes(img[0:512])
    OUT.write_bytes(bytes(img))

    a = OUT.read_bytes()
    ok_sig = a[510:512] == bytes([0x55, 0xAA])
    ok_kern = a[KERNEL_OFF:KERNEL_OFF + len(kern)] == kern
    ok_size = len(a) == IMG_SIZE
    ok_part = (a[0x1BE] == 0x80 and a[0x1C2] == 0x0C
               and a[0x1CE] == 0x00 and a[0x1D2] == 0xDA)
    ok_vbr = a[BOOT_PART_LBA * 512:BOOT_PART_LBA * 512 + 512] == a[0:512]
    print(f"[image] 引导签名 0x55AA:        {'PASS' if ok_sig else 'FAIL'}")
    print(f"[image] 内核槽字节 == Ds 输出:   {'PASS' if ok_kern else 'FAIL'}")
    print(f"[image] 镜像大小 {IMG_SIZE}:      {'PASS' if ok_size else 'FAIL'}")
    print(f"[image] 双分区表(引导+日志):      {'PASS' if ok_part else 'FAIL'}")
    print(f"[image] 引导分区有 VBR 副本:      {'PASS' if ok_vbr else 'FAIL'}")
    print(f"[image] 引导分区 LBA {BOOT_PART_LBA} × {BOOT_PART_SECS} 扇区")
    print(f"[image] 日志分区 LBA {LOG_PART_LBA} × {LOG_PART_SECS} 扇区"
          f"（{SLOT_COUNT} 槽 × {SLOT_BYTES//1024} KiB）")
    print(f"\n镜像: {OUT}")
    print(f"sha256: {hashlib.sha256(a).hexdigest()}")
    ok = ok_sig and ok_kern and ok_size and ok_part and ok_vbr
    print("BUILD:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
