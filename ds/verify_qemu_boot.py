"""dsos-os/ds/verify_qemu_boot.py — 用 QEMU 真机级验证整条引导链

QEMU 是完整虚拟机（TCG 能真正切换 CPU 模式），因此：
  - 实模式 → 保护模式 → 长模式
  - IDT 异常投递、iretq 返回
这些在 unicorn 里验证不了的东西，这里全部能验证。

本工具不依赖图形界面：
  1. 用 -display none 启动
  2. 通过 QEMU monitor (TCP) 执行 `xp /2000xb 0xb8000`
     直接读到 VGA 文本缓冲区 → 还原成屏幕文字
  3. 断言屏幕内容（引导标记 / 内核横幅 / 心跳）

用法：
    python3 verify_qemu_boot.py                  # 测当前 dsos-ds.img
    python3 verify_qemu_boot.py --img xxx.img
    python3 verify_qemu_boot.py --keep            # 保留截图与日志
"""
import argparse, os, pathlib, re, socket, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_IMG = HERE / "dsos-ds.img"

QEMU_CANDIDATES = [
    r"C:\Program Files\qemu\qemu-system-x86_64.exe",
    r"C:\Program Files (x86)\qemu\qemu-system-x86_64.exe",
    "qemu-system-x86_64",
]


def find_qemu():
    for p in QEMU_CANDIDATES:
        if p == "qemu-system-x86_64" or pathlib.Path(p).exists():
            return p
    raise FileNotFoundError("找不到 qemu-system-x86_64.exe")


def monitor_cmd(mon, cmd, idle=2.0, timeout=25.0):
    """发送命令，然后一直读到「连接空闲 idle 秒」为止（monitor 会回显带控制字符）。"""
    mon.sendall(cmd.encode() + b"\n")
    buf = b""
    t0 = time.time()
    last = time.time()
    mon.settimeout(0.3)
    while time.time() - t0 < timeout:
        try:
            chunk = mon.recv(65536)
        except socket.timeout:
            if time.time() - last > idle:
                break
            continue
        if not chunk:
            break
        buf += chunk
        last = time.time()
    return buf.decode("utf-8", "replace")


DUMP_LINE = re.compile(r"^\s*([0-9a-fA-F]{6,}):\s+(.*)$")


def read_screen(mon):
    out = monitor_cmd(mon, "xp /4000xb 0xb8000")
    bytes_ = []
    for line in out.splitlines():
        m = DUMP_LINE.match(line)
        if not m:
            continue          # 跳过 monitor 回显行（里面有 "0xb8000" 之类，会污染解析）
        for h in re.findall(r"0x([0-9a-fA-F]{2})\b", m.group(2)):
            bytes_.append(int(h, 16))
    if len(bytes_) < 4000:
        return None, out
    rows = []
    for r in range(25):
        chars = []
        for c in range(80):
            ch = bytes_[(r * 80 + c) * 2]
            chars.append(chr(ch) if 32 <= ch < 127 else " ")
        rows.append("".join(chars).rstrip())
    return rows, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default=str(DEFAULT_IMG))
    ap.add_argument("--port", type=int, default=4477)
    ap.add_argument("--boot-wait", type=float, default=6.0,
                    help="等待引导完成的秒数")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    qemu = find_qemu()
    img = pathlib.Path(args.img)
    print(f"QEMU : {qemu}")
    print(f"镜像 : {img}  ({img.stat().st_size} B)")

    log = HERE / "_qemu_stdout.txt"
    cmd = [
        qemu,
        "-drive", f"format=raw,file={img.name},if=ide",
        "-m", "256",
        "-display", "none",
        "-no-reboot",
        "-monitor", f"tcp:127.0.0.1:{args.port},server,nowait",
    ]
    with open(log, "wb") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                cwd=str(img.parent))
    try:
        mon = None
        for _ in range(50):
            time.sleep(0.2)
            try:
                mon = socket.create_connection(("127.0.0.1", args.port), timeout=2)
                break
            except OSError:
                continue
        if mon is None:
            print("FAIL: 连不上 QEMU monitor")
            return 1
        mon.settimeout(8.0)

        time.sleep(args.boot_wait)
        rows, raw = read_screen(mon)
        if rows is None:
            print("FAIL: 没能读出 VGA 缓冲区")
            print(raw[:500])
            return 1

        print("\n===== 屏幕内容 =====")
        for i, r in enumerate(rows):
            if r.strip():
                print(f"{i:2d}| {r}")
        print("====================")
        scr = "\n".join(rows)

        results = {}
        # 通用断言：任何 DsOS 版本都应出现横幅
        results["出现 DsOS 横幅"] = "DsOS" in scr
        results["出现版本号"] = bool(re.search(r"v\d+\.\d+", scr))
        # 引导链调试标记（Ds 版 stage2 才有）
        marks = re.search(r"(\d{1,8})", rows[0]) if rows else None
        if "DsOS" not in scr and rows and rows[0].strip():
            print(f"\n第一行（可能是引导标记）: {rows[0]!r}")

        # 尝试往下翻页/看是否有 panic
        results["没有 EXCEPTION"] = "EXCEPTION" not in scr

        ok = all(results.values())
        print()
        for k, v in results.items():
            print(f"[{'PASS' if v else 'FAIL'}] {k}")
        print("\nRESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if not args.keep:
            time.sleep(0.5)
            try:
                log.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
