"""dsos-os/ds/verify_thunk16.py — 端到端验证「16 位写盘 thunk 能写日志分区」

流程：
  1. 用 mini16 编译 thunk16.ds → 16 位机器码
  2. 造一个 8 MB 测试盘，把 thunk 放在 LBA 0（引导扇区）
  3. QEMU 启动它（BIOS 会执行 int 13h AH=03 写盘）
  4. 退出 QEMU，直接读测试镜像文件 LBA 6144 处
  5. 断言写入了 "DSLOG1" 魔数

QEMU 把磁盘写入真实落到文件上，所以这是**真写盘**验证，不是模拟。
"""
import pathlib, struct, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from mini16 import compile_source

QEMU = r"C:\Program Files\qemu\qemu-system-x86_64.exe"
LOG_LBA = 6144
SECTORS = 8
TEST_IMG = HERE / "_thunk_test.img"

code = compile_source((HERE / "thunk16.ds").read_text(encoding="utf-8"))
print(f"thunk16.ds 编译: {len(code)} 字节")
if len(code) > 510:
    print("FAIL: 超过 510 字节")
    sys.exit(1)

# 造测试盘：8 MiB，LBA 0 = thunk 引导扇区
size = (LOG_LBA + 64) * 512
img = bytearray(size)
img[0:len(code)] = code
img[510:512] = b"\x55\xaa"
TEST_IMG.write_bytes(bytes(img))

# QEMU 启动（无界面，跑完自动退出靠 -no-reboot + 我们的 halt）
log = HERE / "_thunk_qemu.log"
with open(log, "wb") as lf:
    proc = subprocess.Popen(
        [QEMU, "-drive", f"format=raw,file={TEST_IMG.name},if=ide,cache=writethrough",
         "-m", "64", "-display", "none", "-no-reboot",
         "-drive", f"format=raw,file={TEST_IMG.name},if=ide,cache=writethrough"],
        stdout=lf, stderr=subprocess.STDOUT, cwd=str(HERE))
    try:
        proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=5)
time.sleep(0.5)

# 读回测试盘
back = TEST_IMG.read_bytes()
off = LOG_LBA * 512
got = back[off:off + 16]
print(f"LBA {LOG_LBA} 处内容: {got.hex(' ')}  ascii={got[:8]!r}")

ok = got[:6] == b"DSLOG1"
print(f"[PASS] thunk 写入日志分区" if ok else "[FAIL] 日志分区未写入")
print("RESULT:", "PASS" if ok else "FAIL")

# 清理
try:
    TEST_IMG.unlink()
    log.unlink()
except OSError:
    pass
sys.exit(0 if ok else 1)
