"""Acceptance harness for DsOS v0.4.

Boots the 64-bit kernel on unicorn, injects keystrokes through the real IRQ1
handler registered in the IDT, and reads the VGA text buffer to assert output.
"""
import hashlib, os, struct, sys
from unicorn import *
from unicorn.x86_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_shell as gb
from kernel_body import build

IMG = os.path.join(HERE, "dsos-x86_64-shell.img")
STUB = 0x6000           # `hlt; jmp $` used as the iretq return target
LOWMEM = 0x200000


def vga_text(uc):
    raw = bytes(uc.mem_read(0xB8000, 80 * 25 * 2))
    lines = []
    for row in range(25):
        chunk = raw[row * 160:(row + 1) * 160]
        txt = "".join(chr(chunk[i]) if 32 <= chunk[i] < 127 else " " for i in range(0, 160, 2))
        lines.append(txt.rstrip())
    return "\n".join(lines).rstrip()


def plant_acpi(uc, pm1a=0x604, slp=5):
    """Fake a minimal RSDP -> RSDT -> FADT chain so the parse path is exercised."""
    rsdp = 0xF0000
    buf = bytearray(20)
    buf[0:8] = b"RSD PTR "
    buf[8] = 0x00            # revision 0
    struct.pack_into("<I", buf, 16, 0xF0100)   # RSDT address
    chk = (256 - (sum(buf) % 256)) % 256
    buf[15] = chk
    uc.mem_write(rsdp, bytes(buf))

    rsdt = 0xF0100
    hdr = bytearray(36)
    hdr[0:4] = b"RSDT"
    struct.pack_into("<I", hdr, 4, 36 + 4)     # length: header + 1 entry
    chk = (256 - (sum(hdr) % 256)) % 256
    hdr[9] = chk
    uc.mem_write(rsdt, bytes(hdr) + struct.pack("<I", 0xF0200))

    fadt = 0xF0200
    fb = bytearray(256)
    fb[0:4] = b"FACP"
    struct.pack_into("<I", fb, 4, 256)
    struct.pack_into("<I", fb, 64, pm1a)       # PM1a_CNT_BLK
    struct.pack_into("<H", fb, 0xB0, slp << 10)  # SLP_TYPa
    uc.mem_write(fadt, bytes(fb))


def main():
    img = open(IMG, "rb").read()
    blob, labels = build()
    print(f"image {len(img)}B  sha256={hashlib.sha256(img).hexdigest()[:32]}")
    print(f"kernel {len(blob)}B, labels: irq1=0x{0x9000 + labels['irq1']:x} "
          f"main_loop=0x{0x9000 + labels['main_loop']:x}")

    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, LOWMEM)
    uc.mem_write(gb.STAGE2_ADDR, img[512:512 + 4096])      # stage2 (for its GDT)
    uc.mem_write(0x9000, blob)                             # kernel
    uc.mem_write(STUB, b"\xf4\xeb\xfd")                    # hlt; jmp $
    uc.reg_write(UC_X86_REG_GDTR, (0, gb.STAGE2_ADDR + gb.GDT_OFF, 5 * 8 - 1, 0))
    uc.reg_write(UC_X86_REG_RSP, 0x70000)

    serial = bytearray()
    outs = []
    keys = []
    state = {"irqs": 0}

    def on_out(uc, *args):
        port, size, value = args[0], args[1], args[2]
        outs.append((port, size, value))
        if port == 0x3F8:
            serial.append(value & 0xFF)

    def on_in(uc, *args):
        port = args[0]
        if port == 0x3FD:
            return 0x20
        if port == 0x60:
            return keys.pop(0) if keys else 0
        return 0x00

    uc.hook_add(UC_HOOK_INSN, on_out, None, 1, 0, UC_X86_INS_OUT)
    uc.hook_add(UC_HOOK_INSN, on_in, None, 1, 0, UC_X86_INS_IN)

    def run(addr, count=200000):
        try:
            uc.emu_start(addr, 0, count=count)
        except UcError as e:
            msg = str(e)
            # hlt is not an error we care about
            if "EXCEPTION" not in msg and "halt" not in msg.lower():
                return msg
        return None

    def press(scan):
        """Enter the IRQ1 handler as the CPU would, with a real interrupt frame."""
        keys.append(scan)
        sp = 0x6F000
        uc.mem_write(sp, struct.pack("<Q", STUB))          # return RIP
        uc.mem_write(sp + 8, struct.pack("<Q", 0x18))      # CS
        uc.mem_write(sp + 16, struct.pack("<Q", 0x202))    # RFLAGS
        uc.reg_write(UC_X86_REG_RSP, sp)
        run(0x9000 + labels["irq1"], 5000)
        state["irqs"] += 1
        uc.reg_write(UC_X86_REG_RSP, 0x70000)
        run(0x9000 + labels["main_loop"], 200000)          # let the shell consume it

    def type_text(text):
        for ch in text:
            scan = SCANCODE[ch]
            press(scan)

    SCANCODE = {c: s for s, c in [(0x1C, "\n"), (0x39, " ")]}
    for i, ch in enumerate("1234567890"):
        SCANCODE[ch] = 0x02 + i
    for i, ch in enumerate("qwertyuiop"):
        SCANCODE[ch] = 0x10 + i
    for i, ch in enumerate("asdfghjkl"):
        SCANCODE[ch] = 0x1E + i
    for i, ch in enumerate("zxcvbnm"):
        SCANCODE[ch] = 0x2C + i

    print("\n--- boot kernel ---")
    err = run(0x9000)
    text = vga_text(uc)
    print(text[:400])
    ok_boot = "DsOS v0.4" in text and "dsos>" in text
    print(f"[a] boot + banner + prompt: {'PASS' if ok_boot else 'FAIL'}")

    print("\n--- type 'help' + Enter ---")
    type_text("help\n")
    text = vga_text(uc)
    ok_help = "commands:" in text and "shutdown" in text
    print(f"[b] help command: {'PASS' if ok_help else 'FAIL'}")

    print("\n--- type 'ticks' + Enter ---")
    type_text("ticks\n")
    text = vga_text(uc)
    ok_ticks = "ticks=" in text
    print(f"[c] ticks command: {'PASS' if ok_ticks else 'FAIL'}")

    print("\n--- plant fake ACPI tables, then 'shutdown' + Enter ---")
    plant_acpi(uc, pm1a=0x604, slp=5)
    before = len(outs)
    type_text("shutdown\n")
    text = vga_text(uc)
    poweroff = [o for o in outs[before:] if o[0] == 0x604 and o[2] == (5 << 10) | 0x2000]
    ok_acpi = "FADT" in text
    ok_s5 = bool(poweroff)
    print(f"    outs after shutdown: {[(hex(p), v) for p, s, v in outs[before:]][:8]}")
    print(f"[d] ACPI FADT parse path: {'PASS' if ok_acpi else 'FAIL'}")
    print(f"[e] S5 outw to 0x604 with 0x{(5 << 10) | 0x2000:x}: {'PASS' if ok_s5 else 'FAIL'}")

    print("\n--- [g] polling fallback: IRQ1 never fires ---")
    # Fresh VM: pretend the firmware never delivers IRQ1. Only port 0x60/0x64 work.
    uc2 = Uc(UC_ARCH_X86, UC_MODE_64)
    uc2.mem_map(0, LOWMEM)
    uc2.mem_write(0x9000, blob)
    uc2.mem_write(STUB, b"\xf4\xeb\xfd")
    uc2.reg_write(UC_X86_REG_GDTR, (0, gb.STAGE2_ADDR + gb.GDT_OFF, 5 * 8 - 1, 0))
    uc2.reg_write(UC_X86_REG_RSP, 0x70000)
    pending = []

    def on_out2(uc, *a):
        pass

    def on_in2(uc, *a):
        port = a[0]
        if port == 0x3FD:
            return 0x20
        if port == 0x64:
            return 0x01 if pending else 0x00      # output buffer full while a key waits
        if port == 0x60:
            return pending.pop(0) if pending else 0
        return 0

    uc2.hook_add(UC_HOOK_INSN, on_out2, None, 1, 0, UC_X86_INS_OUT)
    uc2.hook_add(UC_HOOK_INSN, on_in2, None, 1, 0, UC_X86_INS_IN)
    try:
        uc2.emu_start(0x9000, 0, count=300000)
    except UcError:
        pass
    for ch in "help\n":
        pending.append(SCANCODE[ch])
        try:
            uc2.emu_start(0x9000 + labels["main_loop"], 0, count=200000)
        except UcError:
            pass
    text2 = vga_text(uc2)
    ok_poll = "commands:" in text2 and "shutdown" in text2
    print(f"    screen tail: {text2.splitlines()[-3:] if text2 else 'EMPTY'}")
    print(f"[g] polling fallback works without IRQ1: {'PASS' if ok_poll else 'FAIL'}")

    print("\n--- [h] real handoff: stage2 long-mode entry -> jump -> kernel ---")
    # The real machine takes THIS path. Booting the kernel directly (case [a]) hides a
    # wrong jump displacement in stage2 — exactly the bug that powered a real board off.
    uc3 = Uc(UC_ARCH_X86, UC_MODE_64)
    uc3.mem_map(0, LOWMEM)
    uc3.mem_write(gb.STAGE2_ADDR, img[512:512 + 4096])
    uc3.mem_write(0x9000, img[4608:4608 + 4096])
    uc3.reg_write(UC_X86_REG_GDTR, (0, gb.STAGE2_ADDR + gb.GDT_OFF, 5 * 8 - 1, 0))
    uc3.reg_write(UC_X86_REG_RSP, 0x70000)

    def on_in3(uc, *a):
        return 0x20 if a[0] == 0x3FD else 0x00

    def on_out3(uc, *a):
        pass

    uc3.hook_add(UC_HOOK_INSN, on_out3, None, 1, 0, UC_X86_INS_OUT)
    uc3.hook_add(UC_HOOK_INSN, on_in3, None, 1, 0, UC_X86_INS_IN)
    st2 = bytes(img[512:512 + 4096])
    lm = None
    for i in range(len(st2) - 7):
        if st2[i] == 0xEA and st2[i + 5:i + 7] == b"\x18\x00":
            lm = struct.unpack_from("<I", st2, i + 1)[0]
    print(f"    stage2 long-mode entry: {lm and hex(lm)}")
    try:
        uc3.emu_start(lm, 0, count=300000)
    except UcError as e:
        print(f"    (stopped: {e})")
    text3 = vga_text(uc3)
    print(f"    screen: {text3.splitlines()[:2] if text3 else 'EMPTY'}")
    ok_handoff = "DsOS v0.4" in text3 and "dsos>" in text3
    print(f"[h] stage2 jump reaches the kernel: {'PASS' if ok_handoff else 'FAIL'}")

    print("\n--- final screen ---")
    print(vga_text(uc)[-500:])

    legacy = {
        "dsos-x86_64.img": "32669f00bd249129ded0b1060e897364ab90b99984ce5bf3f8a103393f8e2aed",
        "dsos-x86_64-vga.img": "7559cead34556b03476ff3349a6537fcc6f8c0591ece8b6ba86ae9cf4f725c4e",
    }
    ok_legacy = True
    vga_dir = r"D:\文档\deepseek-harness\default-workspace\dsos-vga"
    for name, want in legacy.items():
        p = os.path.join(vga_dir, name)
        if os.path.exists(p):
            got = hashlib.sha256(open(p, "rb").read()).hexdigest()
            if got != want:
                ok_legacy = False
                print(f"    LEGACY CHANGED: {name} {got}")
    print(f"[f] legacy images unchanged: {'PASS' if ok_legacy else 'FAIL'}")

    allok = all([ok_boot, ok_help, ok_ticks, ok_acpi, ok_s5, ok_legacy, ok_poll, ok_handoff])
    print(f"\nRESULT: {'PASS' if allok else 'FAIL'}   (irq1 injections: {state['irqs']})")
    open(os.path.join(HERE, "verify_out.txt"), "w", encoding="utf-8").write(vga_text(uc))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
