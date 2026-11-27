"""dsos-os/ds/verify_savelog.py — 端到端验证「日志落盘 U 盘」

完整链路（全部在 QEMU 里真实发生）：
  1. 启动 DsOS（Ds MBR + Python stage2 + Ds 内核）
  2. 通过 monitor sendkey 输入 "savelog" + 回车
  3. 内核把日志环拷到 0x10000，写魔数，然后写端口 0x64=0xFE 触发暖复位
  4. 复位后 BIOS 重新执行 MBR；Ds MBR 在实模式下检测到魔数
  5. MBR 用 int 13h AH=43 把 0x10000 的 8 个扇区写进日志分区 LBA 6144
  6. 脚本退出 QEMU，直接读镜像文件 LBA 6144，断言里面有日志文本
"""
import pathlib, re, socket, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
QEMU = r"C:\Program Files\qemu\qemu-system-x86_64.exe"
IMG = HERE / "dsos-ds.img"
LOG_LBA = 6144
PORT = 4491


def cmd(mon, c, idle=1.2, timeout=20.0):
    mon.settimeout(0.3)
    mon.sendall(c.encode() + b"\n")
    buf, last, t0 = b"", time.time(), time.time()
    while time.time() - t0 < timeout:
        try:
            ch = mon.recv(65536)
        except socket.timeout:
            if time.time() - last > idle:
                break
            continue
        if not ch:
            break
        buf += ch
        last = time.time()
    return buf.decode("utf-8", "replace")


def screen(mon):
    out = cmd(mon, "xp /4000xb 0xb8000", idle=2.0)
    bs = []
    for line in out.splitlines():
        m = re.match(r"^\s*([0-9a-f]{6,}):\s+(.*)$", line)
        if m:
            bs += [int(h, 16) for h in re.findall(r"0x([0-9a-fA-F]{2})\b", m.group(2))]
    if len(bs) < 4000:
        return ""
    rows = []
    for r in range(25):
        rows.append("".join(chr(bs[(r * 80 + c) * 2]) if 32 <= bs[(r * 80 + c) * 2] < 127
                            else " " for c in range(80)).rstrip())
    return "\n".join(rows)


print(f"镜像: {IMG.name}  {IMG.stat().st_size} B")
proc = subprocess.Popen(
    [QEMU, "-drive", f"format=raw,file={IMG.name},if=ide,cache=writethrough",
     "-m", "256", "-display", "none",
     "-monitor", f"tcp:127.0.0.1:{PORT},server,nowait"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(HERE))

try:
    mon = None
    for _ in range(60):
        time.sleep(0.2)
        try:
            mon = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            break
        except OSError:
            pass
    if mon is None:
        print("FAIL: 连不上 monitor")
        sys.exit(1)

    time.sleep(7)
    scr = screen(mon)
    print("\n--- 启动后屏幕 ---")
    print("\n".join(l for l in scr.splitlines() if l.strip())[:600])
    booted = "DsOS" in scr
    print(f"\n[{'PASS' if booted else 'FAIL'}] 启动出现 DsOS 横幅")
    if not booted:
        sys.exit(1)

    # 输入 savelog + 回车
    print("\n输入 savelog …")
    for k in "savelog":
        cmd(mon, f"sendkey {k}", idle=0.25, timeout=3)
        time.sleep(0.12)
    cmd(mon, "sendkey ret", idle=0.25, timeout=3)
    time.sleep(6)          # 暖复位 + MBR 写盘 + 二次启动

    scr2 = screen(mon)
    print("\n--- 复位后屏幕 ---")
    print("\n".join(l for l in scr2.splitlines() if l.strip())[:600])
finally:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    time.sleep(0.5)

# 检查镜像文件上的日志分区
data = IMG.read_bytes()
off = LOG_LBA * 512
blob = data[off:off + 8192]
print(f"\nLBA {LOG_LBA} 前 64 字节: {blob[:64].hex(' ')}")
text = blob.decode("latin-1")
has_boot = "[boot]" in text or "[log]" in text
has_dsos = "DsOS" in text
print(f"[{'PASS' if has_dsos else 'FAIL'}] 日志分区含 DsOS 文本")
print(f"[{'PASS' if has_boot else 'FAIL'}] 日志分区含 [boot] 启动日志")
print("日志片段:", repr(text[:240]))

ok = booted and has_dsos and has_boot
print("\nRESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
