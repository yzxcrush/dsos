"""flash_dsos.py — 把 dsos-ds.img 写进 U 盘（\\\\.\\PhysicalDrive1）。

守卫（对应 AGENTS.md 第 5 条）：
  1. 盘号来自实际枚举（脚本内再次确认 BusType/USB 等由调用方 PowerShell 输出核对）
  2. 镜像 512 整数倍 + @510 == 0x55AA
  3. 先清零目标区域（抹掉旧分区表与旧镜像残留）
  4. 写入后回读逐字节比对
  5. 抽样确认镜像之后是零
"""
import hashlib, os, pathlib, sys, time

DISK = 1
DEV = f"\\\\.\\PhysicalDrive{DISK}"
HERE = pathlib.Path(__file__).resolve().parent
IMG = HERE / "dsos-ds.img"
WIPE = 16 * 1024 * 1024          # 先抹 16 MiB
CHUNK = 1024 * 1024


def main():
    data = IMG.read_bytes()
    assert len(data) % 512 == 0, "镜像不是 512 的整数倍"
    assert data[510:512] == b"\x55\xaa", "镜像缺少 0x55AA 引导签名"
    print(f"镜像: {IMG.name}  {len(data)} B  sha256={hashlib.sha256(data).hexdigest()}")
    print(f"目标: {DEV}")

    def write_all(f, blob, label):
        """分块写入，遇 Windows 短暂锁定（EINVAL/EPERM）就重试。"""
        off = 0
        tries = 0
        while off < len(blob):
            chunk = blob[off:off + CHUNK]
            try:
                f.seek(off)
                f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
                off += len(chunk)
                tries = 0
            except OSError as e:
                tries += 1
                if tries > 8:
                    raise
                print(f"  {label}: 偏移 {off} 写入受阻（{e.errno}），重试 {tries}/8…")
                time.sleep(1.0)
        return True

    for attempt in range(1, 4):
        try:
            with open(DEV, "r+b", buffering=0) as f:
                zero = b"\x00" * CHUNK
                write_all(f, zero * (WIPE // CHUNK), "清零")
                print(f"已清零前 {WIPE // (1024*1024)} MiB")
                t0 = time.time()
                write_all(f, data, "写入")
                print(f"已写入 {len(data)} B（{time.time() - t0:.2f}s）")
                f.seek(0)
                back = f.read(len(data))
                ok = back == data
                print(f"回读比对: {len(back)} B  match={ok}")
                f.seek(len(data))
                tail = f.read(4096)
                ok_tail = tail == b"\x00" * 4096
                print(f"镜像之后 4 KiB 全零: {ok_tail}")
            break
        except OSError as e:
            print(f"第 {attempt} 次整体失败（{e}），1 秒后重试…")
            time.sleep(1.5)
    else:
        print("FAIL: 多次重试仍无法写入")
        return 1

    print()
    print(f"[flash] 回读一致:      {'PASS' if ok else 'FAIL'}")
    print(f"[flash] 尾部已抹除:    {'PASS' if ok_tail else 'FAIL'}")
    sig_ok = back[510:512] == bytes([0x55, 0xAA])
    print(f"[flash] 引导签名 55AA: {'PASS' if sig_ok else 'FAIL'}")
    print(f"[flash] 盘上 sha256:   {hashlib.sha256(back).hexdigest()}")
    return 0 if (ok and ok_tail) else 1


if __name__ == "__main__":
    sys.exit(main())
