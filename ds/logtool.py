"""dsos-os/ds/logtool.py — DsOS 日志分区工具（PC 端）

日志分区独立于引导区：
    分区2  类型 0xDA  LBA 6144  8 MiB  256 槽 × 32 KiB

槽格式（每槽 32 KiB，小端）：
    +0   magic  "DSLG"
    +4   u32 seq        会话序号（越大越新）
    +8   u32 len        正文长度
    +12  u32 crc32      正文 CRC32
    +16  u32 flags
    +20  u32 tick       内核心跳节拍（可选）
    +24  u32 reserved
    +28  u32 reserved
    +32  text           正文（最多 32736 字节）

用法：
    python3 logtool.py info                 # 显示分区与槽位使用情况
    python3 logtool.py list                 # 列出所有有效槽
    python3 logtool.py read                 # 打印最新一条日志
    python3 logtool.py read --seq 3         # 打印指定序号
    python3 logtool.py clear                # 清空日志分区
    python3 logtool.py selftest             # 写入一条测试日志并读回校验（会覆盖最新槽）
    python3 logtool.py info --device 1      # 直接操作 U 盘
"""
import argparse, hashlib, pathlib, struct, sys, zlib

MAGIC = b"DSLG"
SLOT_BYTES = 32 * 1024
HDR = 32
LOG_PART_LBA = 6144
LOG_PART_SECS = 16384
LOG_OFF = LOG_PART_LBA * 512
LOG_BYTES = LOG_PART_SECS * 512
SLOT_COUNT = LOG_BYTES // SLOT_BYTES
HERE = pathlib.Path(__file__).resolve().parent
IMAGE = HERE / "dsos-ds.img"


def open_stream(device, write=False):
    """打开镜像文件或物理盘；write=True 时以读写方式打开。"""
    if device is None:
        return open(IMAGE, "r+b" if write else "rb"), f"镜像文件 {IMAGE.name}"
    dev = f"\\\\.\\PhysicalDrive{device}"
    return open(dev, "r+b" if write else "rb", buffering=0), dev


def open_reader(device):
    return open_stream(device, write=False)


def read_slot(f, i):
    f.seek(LOG_OFF + i * SLOT_BYTES)
    raw = f.read(SLOT_BYTES)
    if len(raw) < HDR or raw[:4] != MAGIC:
        return None
    seq, ln, crc, flags, tick = struct.unpack("<IIIII", raw[4:24])
    if ln > SLOT_BYTES - HDR:
        return None
    text = raw[HDR:HDR + ln]
    return {"slot": i, "seq": seq, "len": ln, "crc": crc, "flags": flags,
            "tick": tick, "text": text, "crc_ok": zlib.crc32(text) & 0xFFFFFFFF == crc}


def cmd_info(args):
    f, what = open_reader(args.device)
    slots = [s for s in (read_slot(f, i) for i in range(SLOT_COUNT)) if s]
    f.close()
    print(f"日志分区: {what}")
    print(f"  LBA        {LOG_PART_LBA} .. {LOG_PART_LBA + LOG_PART_SECS - 1}")
    print(f"  大小       {LOG_BYTES / 1024 / 1024:.0f} MiB")
    print(f"  槽         {SLOT_COUNT} × {SLOT_BYTES // 1024} KiB")
    print(f"  有效槽     {len(slots)}")
    if slots:
        newest = max(slots, key=lambda s: s["seq"])
        print(f"  最新序号   {newest['seq']}（槽 {newest['slot']}，{newest['len']} 字节，"
              f"CRC {'OK' if newest['crc_ok'] else 'BAD'}）")
    return 0


def cmd_list(args):
    f, what = open_reader(args.device)
    slots = [s for s in (read_slot(f, i) for i in range(SLOT_COUNT)) if s]
    f.close()
    if not slots:
        print("（没有有效日志槽）")
        return 0
    print(f"{'seq':>5} {'slot':>5} {'len':>6} {'crc':>4} {'tick':>10}")
    for s in sorted(slots, key=lambda x: x["seq"]):
        print(f"{s['seq']:>5} {s['slot']:>5} {s['len']:>6} "
              f"{'OK' if s['crc_ok'] else 'BAD':>4} {s['tick']:>10}")
    return 0


def cmd_read(args):
    f, what = open_reader(args.device)
    slots = [s for s in (read_slot(f, i) for i in range(SLOT_COUNT)) if s]
    f.close()
    if not slots:
        print("（没有有效日志槽）—— 内核尚未把日志写入分区")
        return 1
    if args.seq is None:
        s = max(slots, key=lambda x: x["seq"])
    else:
        cand = [x for x in slots if x["seq"] == args.seq]
        if not cand:
            print(f"找不到 seq={args.seq}")
            return 1
        s = cand[0]
    print(f"# seq={s['seq']} slot={s['slot']} len={s['len']} "
          f"crc={'OK' if s['crc_ok'] else 'BAD'} tick={s['tick']}")
    print("-" * 60)
    sys.stdout.write(s["text"].decode("utf-8", "replace"))
    if not s["text"].endswith(b"\n"):
        print()
    return 0


def _write_slot(f, i, seq, text, tick=0, flags=0):
    body = text.encode("utf-8") if isinstance(text, str) else text
    if len(body) > SLOT_BYTES - HDR:
        raise ValueError("日志过长")
    crc = zlib.crc32(body) & 0xFFFFFFFF
    hdr = MAGIC + struct.pack("<IIIII", seq, len(body), crc, flags, tick) + b"\x00" * 8
    blob = hdr + body
    blob += b"\x00" * (SLOT_BYTES - len(blob))
    f.seek(LOG_OFF + i * SLOT_BYTES)
    f.write(blob)
    f.flush()
    try:
        import os
        os.fsync(f.fileno())
    except OSError:
        pass


def cmd_clear(args):
    f, what = open_stream(args.device, write=True)
    print(f"清空日志分区（{LOG_BYTES / 1024 / 1024:.0f} MiB）…")
    zero = b"\x00" * (1024 * 1024)
    off = LOG_OFF
    end = LOG_OFF + LOG_BYTES
    while off < end:
        f.seek(off)
        f.write(zero)
        off += len(zero)
    f.flush()
    try:
        import os
        os.fsync(f.fileno())
    except OSError:
        pass
    f.close()
    print("完成")
    return 0


def cmd_selftest(args):
    f, what = open_stream(args.device, write=True)
    print(f"自检：写入 → 读回 → 校验（{what}）")
    sample = ("[selftest] DsOS log partition round-trip\n"
              "[selftest] 中文也可以：日志槽 CRC 校验通过\n")
    slots = [s for s in (read_slot(f, i) for i in range(SLOT_COUNT)) if s]
    seq = (max((s["seq"] for s in slots), default=0)) + 1
    idx = seq % SLOT_COUNT
    _write_slot(f, idx, seq, sample, tick=1234)
    back = read_slot(f, idx)
    ok = (back is not None and back["seq"] == seq and back["crc_ok"]
          and back["text"].decode("utf-8") == sample and back["tick"] == 1234)
    print(f"  写入 seq={seq} 槽={idx} 长度={len(sample.encode())}")
    print(f"  读回 seq={back['seq'] if back else None} "
          f"crc={'OK' if back and back['crc_ok'] else 'BAD'}")
    print(f"  内容一致: {ok}")
    f.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(prog="logtool")
    ap.add_argument("cmd", choices=["info", "list", "read", "clear", "selftest"])
    ap.add_argument("--seq", type=int, default=None)
    ap.add_argument("--device", type=int, default=None, help="物理盘号，例如 1")
    args = ap.parse_args()
    return {"info": cmd_info, "list": cmd_list, "read": cmd_read,
            "clear": cmd_clear, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
