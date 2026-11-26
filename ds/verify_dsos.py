"""dsos-os/ds/verify_dsos.py — 验证「全 Ds 源码编译出的内核」在裸机下真的运行。

场景：
  A. 启动：横幅 + 日志 + 心跳推进 + ESC 停机
  B. 输入 "help" + Enter → 帮助文本落屏
  C. 输入 "shutdown" + Enter → ACPI S5 写 PM1a_CNT（0x604 = 0x3400）并停机
  D. 输入未知命令 → 提示 unknown
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compiler"))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = (HERE / "kernel.ds").read_text(encoding="utf-8")
CODE = compile_source(SRC, target="bare")
HALT_SEQ = bytes([0xFA, 0xF4, 0xEB, 0xFE])
# 内核里有多处 halt()（ESC 分支、shutdown 分支），全部收集
halt_offs = [i for i in range(len(CODE)) if CODE.startswith(HALT_SEQ, i)]


def at_halt(off):
    for h in halt_offs:
        if h <= off <= h + 4:
            return True
    return False
print(f"kernel.ds 编译: {len(CODE)} 字节（上限 12288）")
if len(CODE) > 12288:
    print("FAIL: 超出 12288 字节内核区")
    sys.exit(1)

BASE = 0x9000
KEY = {"h": 0x23, "e": 0x12, "l": 0x26, "p": 0x19, "s": 0x1F, "u": 0x16,
       "t": 0x14, "d": 0x20, "o": 0x18, "w": 0x11, "n": 0x31,
       "\n": 0x1C, "\x1b": 0x01, "x": 0x2D}


def keys_of(s):
    return [KEY[c] for c in s]


def boot(with_acpi=False):
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x200000)
    uc.mem_write(BASE, CODE)
    uc.reg_write(UC_X86_REG_RSP, 0x70000)
    uc.reg_write(UC_X86_REG_RBP, 0x70000)
    uc.reg_write(UC_X86_REG_RIP, BASE)

    if with_acpi:
        rsdp = bytearray(36)
        rsdp[0:8] = b"RSD PTR "
        rsdp[16:20] = (0xF0000).to_bytes(4, "little")
        uc.mem_write(0xE0000, bytes(rsdp))
        rsdt = bytearray(40)
        rsdt[0:4] = b"RSDT"
        rsdt[4:8] = (40).to_bytes(4, "little")
        rsdt[36:40] = (0xF1000).to_bytes(4, "little")
        uc.mem_write(0xF0000, bytes(rsdt))
        fadt = bytearray(256)
        fadt[0:4] = b"FACP"
        fadt[4:8] = (244).to_bytes(4, "little")
        fadt[64:68] = (0x604).to_bytes(4, "little")
        uc.mem_write(0xF1000, bytes(fadt))

    st = {"keys": [], "outs": [], "halted": False}

    def on_in(uc, *args):
        port = args[0]
        if port == 0x64:
            return 1 if st["keys"] else 0
        if port == 0x60:
            return st["keys"].pop(0) if st["keys"] else 0
        return 0

    def on_out(uc, *args):
        st["outs"].append((args[0], args[2] & 0xFF))

    uc.hook_add(UC_HOOK_INSN, on_in, None, 1, 0, UC_X86_INS_IN)
    uc.hook_add(UC_HOOK_INSN, on_out, None, 1, 0, UC_X86_INS_OUT)
    return uc, st


def row(uc, r):
    raw = bytes(uc.mem_read(0xB8000 + r * 160, 160))
    return "".join(chr(raw[i]) if 32 <= raw[i] < 127 else " " for i in range(0, 160, 2)).rstrip()


def screen(uc, n=25):
    return "\n".join(row(uc, r) for r in range(n))


def run(uc, n):
    try:
        uc.emu_start(uc.reg_read(UC_X86_REG_RIP), 0, count=n)
    except UcError as e:
        print("  stop:", e)


results = {}

# ---------- A. 启动 + 日志 + 心跳 + ESC ----------
uc, st = boot()
run(uc, 2000000)
hb1 = row(uc, 21)
run(uc, 2000000)
hb2 = row(uc, 21)
st["keys"] = keys_of("\x1b")
run(uc, 1000000)
rip_off = uc.reg_read(UC_X86_REG_RIP) - BASE
scr = screen(uc, 25)
print("=== A. 启动 ===")
print(scr)
results["A 横幅"] = "DsOS v0.8" in row(uc, 0) and "Ds toolchain" in row(uc, 1)
results["A 日志"] = "entering main loop" in scr and "ACPI S5" in scr
results["A 心跳推进"] = hb1.startswith("[beat") and hb1 != hb2
results["A ESC 停机"] = at_halt(rip_off)
print(f"  心跳: {hb1!r} -> {hb2!r}")

# ---------- B. help ----------
uc, st = boot()
st["keys"] = keys_of("help\n")
run(uc, 12000000)
scr = screen(uc, 25)
print("\n=== B. help ===")
print(scr)
results["B help 生效"] = "show this text" in scr and "ACPI S5 power off" in scr
results["B 命令行回显"] = "cmd>" in scr

# ---------- C. shutdown（ACPI） ----------
uc, st = boot(with_acpi=True)
st["keys"] = keys_of("shutdown\n")
run(uc, 20000000)
scr = screen(uc, 25)
outs = st["outs"]
pm_writes = [(p, v) for p, v in outs if p in (0x604, 0x605)]
print("\n=== C. shutdown ===")
print(scr)
print(f"  端口写入: {[(hex(p), hex(v)) for p, v in pm_writes]}")
results["C shutdown 日志"] = "shutdown -> ACPI S5" in scr
results["C ACPI 0x604=0x3400"] = (0x604, 0x00) in pm_writes and (0x605, 0x34) in pm_writes
rip_off = uc.reg_read(UC_X86_REG_RIP) - BASE
results["C 停机"] = at_halt(rip_off)
print(f"  halt 位置 {halt_offs}, 最终 RIP 偏移 {rip_off}")

# ---------- D. 未知命令 ----------
uc, st = boot()
st["keys"] = keys_of("h\n")   # 单字母 h：未映射成命令 -> unknown
run(uc, 12000000)
scr = screen(uc, 25)
print("\n=== D. 未知命令 ===")
print(scr)
results["D unknown 提示"] = "unknown command" in scr

print("\n=== 结论 ===")
ok_all = True
for k, v in results.items():
    ok_all &= v
    print(f"[{'PASS' if v else 'FAIL'}] {k}")
print("RESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
