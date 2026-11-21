"""Execute the DsOS artifacts on an actual x86 emulation core (unicorn = QEMU TCG).

Captures COM1 (0x3F8) output and Linux syscalls so we can compare against the
expected serial strings without a full BIOS/Multiboot boot.
"""
import os, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
OUTDIR = pathlib.Path(os.environ.get("VERIFY_OUT", str(REPO / "_verify_out")))
OUTDIR.mkdir(parents=True, exist_ok=True)
import io, os, struct, sys
from unicorn import *
from unicorn.x86_const import *

BASE = str(REPO)
OUT = []


def log(s=""):
    OUT.append(s)
    print(s)


def rd(path):
    with open(path, "rb") as f:
        return f.read()


class Serial:
    def __init__(self):
        self.buf = bytearray()

    def out(self, byte):
        self.buf.append(byte & 0xFF)

    @property
    def text(self):
        return self.buf.decode("utf-8", "replace")


# ---------------------------------------------------------------- syscall.bin
def run_syscall_bin():
    path = os.path.join(BASE, "dsos", "toolchain", "step1", "syscall.bin")
    code = rd(path)
    log(f"## syscall.bin  ({len(code)} bytes, x86_64 userspace syscall path)")
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    ADDR = 0x400000
    uc.mem_map(ADDR, 0x10000)
    uc.mem_write(ADDR, code)
    ser = Serial()
    state = {"writes": [], "exit": None}

    def on_syscall(uc, ud):
        rax = uc.reg_read(UC_X86_REG_RAX)
        if rax == 1:  # write
            fd = uc.reg_read(UC_X86_REG_RDI)
            buf = uc.reg_read(UC_X86_REG_RSI)
            n = uc.reg_read(UC_X86_REG_RDX)
            data = uc.mem_read(buf, n)
            state["writes"].append((fd, bytes(data)))
            uc.reg_write(UC_X86_REG_RAX, n)
        elif rax == 60:  # exit
            state["exit"] = uc.reg_read(UC_X86_REG_RDI)
            uc.emu_stop()
        else:
            state.setdefault("unknown", []).append(rax)
            uc.emu_stop()

    uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
    uc.reg_write(UC_X86_REG_RIP, ADDR)
    uc.reg_write(UC_X86_REG_RSP, 0x408000)
    try:
        uc.emu_start(ADDR, 0, count=1000)
    except UcError as e:
        log(f"   emulation error: {e}")
    for fd, data in state["writes"]:
        log(f"   write(fd={fd}, {len(data)}B) -> {data!r}")
    log(f"   exit code seen: {state['exit']}")
    got = b"".join(d for _, d in state["writes"])
    ok = got == b"DsOS booted.\n"
    log(f"   EXPECTED 'DsOS booted.\\n' -> {'PASS' if ok else 'FAIL'}")
    log()
    return ok


# ------------------------------------------------- 16-bit boot sectors (serial)
def run_boot16(path, label, expect, max_insns=2_000_000):
    code = rd(path)
    log(f"## {label}  ({len(code)} bytes, 16-bit real mode @0x7C00)")
    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0x0, 0x100000)
    uc.mem_write(0x7C00, code)
    ser = Serial()
    hits = {"n": 0}
    ports = {}

    def on_out(uc, *args):
        # unicorn passes (port, size, value) in some versions, or just uc
        try:
            port, size, value = args[0], args[1], args[2]
        except Exception:
            port = uc.reg_read(UC_X86_REG_DX)
            value = uc.reg_read(UC_X86_REG_AL)
        ports[port] = ports.get(port, 0) + 1
        if port == 0x3F8:
            ser.out(value)
        hits["n"] += 1

    hook_ok = True
    try:
        uc.hook_add(UC_HOOK_INSN, on_out, None, 1, 0, UC_X86_INS_OUT)
    except Exception as e:
        hook_ok = False
        log(f"   could not hook OUT: {e}")

    uc.reg_write(UC_X86_REG_CS, 0)
    uc.reg_write(UC_X86_REG_IP, 0x7C00)
    try:
        uc.emu_start(0x7C00, 0, count=max_insns)
    except UcError as e:
        log(f"   stopped: {e}")
    log(f"   out-hook calls: {hits['n']}  ports={ {hex(k): v for k, v in ports.items()} }")
    log(f"   serial captured: {ser.text!r}")
    ok = expect in ser.text
    log(f"   EXPECTED {expect!r} -> {'PASS' if ok else 'FAIL'}")
    log()
    return ok


# ------------------------------------- full image: stage1 disk read + stage2 start
def run_full_image():
    path = os.path.join(BASE, "dsos", "images", "x86_64", "dsos-x86_64.img")
    img = rd(path)
    log(f"## dsos-x86_64.img  ({len(img)} bytes) — stage1 MBR with simulated int 13h")
    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0x0, 0x200000)
    uc.mem_write(0x7C00, img[:512])
    ser = Serial()
    st = {"int13": 0, "out": 0, "cr0": None, "trace": []}

    def on_out(uc, *args):
        try:
            port, size, value = args[0], args[1], args[2]
        except Exception:
            port = uc.reg_read(UC_X86_REG_DX)
            value = uc.reg_read(UC_X86_REG_AL)
        st["out"] += 1
        if port == 0x3F8:
            ser.out(value)

    def on_intr(uc, intno, ud):
        if intno == 0x13:
            st["int13"] += 1
            ah = (uc.reg_read(UC_X86_REG_EAX) >> 8) & 0xFF
            al = uc.reg_read(UC_X86_REG_EAX) & 0xFF
            if ah == 0x02:  # read sectors
                cyl = ((uc.reg_read(UC_X86_REG_ECX) >> 8) & 0xFF)
                sec = (uc.reg_read(UC_X86_REG_ECX) & 0x3F)
                head = (uc.reg_read(UC_X86_REG_EDX) >> 8) & 0xFF
                lba = (cyl * 2 + head) * 18 + (sec - 1)
                buf = uc.reg_read(UC_X86_REG_EBX) & 0xFFFF
                count = al
                data = img[lba * 512: lba * 512 + count * 512]
                uc.mem_write(buf, data)
                eax = (uc.reg_read(UC_X86_REG_EAX) & 0xFFFF0000) | ((count & 0xFF) << 8) | 0
                uc.reg_write(UC_X86_REG_EAX, eax)
                uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) & ~0x1)
                st["trace"].append(f"int13 read lba={lba} n={count} -> 0x{buf:x}")
            else:
                st["trace"].append(f"int13 ah={ah:#x} (not emulated)")
        else:
            st["trace"].append(f"int {intno:#x}")

    uc.hook_add(UC_HOOK_INSN, on_out, None, 1, 0, UC_X86_INS_OUT)
    uc.hook_add(UC_HOOK_INTR, on_intr)
    uc.reg_write(UC_X86_REG_CS, 0)
    uc.reg_write(UC_X86_REG_IP, 0x7C00)
    uc.reg_write(UC_X86_REG_DL, 0x00)  # boot drive
    try:
        uc.emu_start(0x7C00, 0, count=3_000_000)
        log("   emulation finished without error")
    except UcError as e:
        log(f"   stopped: {e}")
    try:
        cr0 = uc.reg_read(UC_X86_REG_CR0)
        log(f"   final CR0 = {cr0:#x} (PE bit = {cr0 & 1})")
    except Exception:
        pass
    log(f"   int13 calls: {st['int13']}   out calls: {st['out']}")
    for t in st["trace"][:6]:
        log(f"     {t}")
    log(f"   serial captured: {ser.text!r}")
    log(f"   EXPECTED 'DsOS alive' -> {'PASS' if 'DsOS alive' in ser.text else 'FAIL (did not reach long-mode UART output)'}")
    log()


ok1 = run_syscall_bin()
ok2 = run_boot16(os.path.join(BASE, "dsos", "toolchain", "step1", "bare_serial.bin"),
                 "bare_serial.bin", "DsOS booted.")
ok3 = run_boot16(os.path.join(BASE, "dsos", "images", "x86_64", "dsos-bios.img"),
                 "dsos-bios.img", "DsOS booted.")
run_full_image()

log(f"SUMMARY: syscall.bin={'PASS' if ok1 else 'FAIL'}  bare_serial={'PASS' if ok2 else 'FAIL'}  bios_img={'PASS' if ok3 else 'FAIL'}")
io.open(str(OUTDIR / "_emu_result.txt"), "w", encoding="utf-8").write("\n".join(OUT))
