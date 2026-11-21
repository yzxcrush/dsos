"""Assemble the DsOS v0.4 kernel body. Appended to kernel.py's emitter."""
import struct
from kernel import *   # K2, gb, ENTRY, memory-map constants, emitter

# ---------------------------------------------------------------- scancode map
SCAN = {}
for i, ch in enumerate("1234567890"):
    SCAN[0x02 + i] = ord(ch)
SCAN[0x0E] = 0x08        # backspace
SCAN[0x0F] = ord('\t')
for i, ch in enumerate("qwertyuiop"):
    SCAN[0x10 + i] = ord(ch)
SCAN[0x1C] = 0x0A        # enter
for i, ch in enumerate("asdfghjkl"):
    SCAN[0x1E + i] = ord(ch)
for i, ch in enumerate("zxcvbnm"):
    SCAN[0x2C + i] = ord(ch)
SCAN[0x39] = 0x20        # space
SCAN[0x0C] = ord('-')
SCAN[0x34] = ord('.')
SCAN[0x35] = ord('/')


def build():
    k = K2()
    k.abs_fixups = []

    def mov_label(reg, label):
        k.mov_ri(reg, 0xAAAAAAAAAAAAAAAA)
        k.abs_fixups.append((len(k.b) - 8, label))

    # ================================================================ entry
    k.label("_start")
    k.emit(b"\xfc")                # cld: never trust the direction flag from firmware
    k.mov_al_imm(0)
    k.call_label("log_evt")         # boot
    k.call_label("draw_desktop")
    # call the helpers once, then jump OVER them (they end in `ret` and must not fall through)
    k.call_label("uart_init")
    k.jmp("init_idt")

    # ---- UART init (COM1 115200 8N1) ----
    k.label("uart_init")
    for port, val in ((0x3F9, 0), (0x3FB, 0x80), (0x3F8, 1), (0x3F9, 0), (0x3FB, 3), (0x3FA, 0xC7)):
        k.mov_dx_imm16(port)
        k.mov_al_imm(val)
        k.out_dx_al()
    k.ret()

    # ---- output primitives ----
    k.label("putc")                 # al = char
    k.call_label("vga_putc")
    k.push_r(RAX)
    k.mov_dx_imm16(0x3FD)
    k.label("putc_wait")
    k.in_al_dx()
    k.test_al_imm(0x20)
    k.jz("putc_wait")
    k.mov_dx_imm16(0x3F8)
    k.pop_r(RAX)
    k.out_dx_al()
    k.ret()

    k.label("vga_putc")             # al = char; honours [ATTR]; scrolls inside the console
    k.push_r(RAX)
    k.push_r(RBX)
    k.push_r(RCX)
    k.push_r(RDX)
    k.push_r(R8)
    k.mov_ri(RBX, 0xB8000)
    k.load_r32_abs(RDX, VGA_ROW)
    k.load_r32_abs(RCX, VGA_COL)
    k.cmp_al_imm(0x0D)              # CR = new line (we always emit CRLF)
    k.jz("vp_cr")
    k.cmp_al_imm(0x0A)              # LF ignored
    k.jz("vp_store")
    k.mov_rr(R8, RDX)
    k.alu("add", R8, RCX)
    k.alu("add", RBX, R8)
    k.st8(RBX, 0, RAX)              # the character
    k.load_al_abs(ATTR)             # current attribute
    k.st8(RBX, 1, RAX)
    k.alu_i("add", RCX, 2)
    k.alu_i("cmp", RCX, 160)
    k.jb("vp_store")
    k.xor_self(RCX)
    k.alu_i("add", RDX, 160)
    k.jmp("vp_advance")
    k.label("vp_cr")
    k.xor_self(RCX)
    k.alu_i("add", RDX, 160)
    k.label("vp_advance")
    k.load_al_abs(SCROLL_LOCK)       # status-bar painting holds the lock
    k.emit(b"\x84\xc0")
    k.jnz("vp_store")
    k.alu_i("cmp", RDX, CON_BOTTOM)
    k.jbe("vp_store")
    k.call_label("scroll_up")
    k.mov_r32i(RDX, CON_BOTTOM)
    k.label("vp_store")
    k.store_r32_abs(VGA_ROW, RDX)
    k.store_r32_abs(VGA_COL, RCX)
    k.pop_r(R8)
    k.pop_r(RDX)
    k.pop_r(RCX)
    k.pop_r(RBX)
    k.pop_r(RAX)
    k.ret()

    k.label("scroll_up")            # shift console rows 2..23 up one row
    k.push_r(RAX)
    k.push_r(RCX)
    k.push_r(RSI)
    k.push_r(RDI)
    k.emit(b"\xfc")                # cld
    k.mov_ri(RSI, 0xB8000 + 320)
    k.mov_ri(RDI, 0xB8000 + 160)
    k.mov_r32i(RCX, 22 * 160)
    k.emit(b"\xf3\xa4")           # rep movsb
    k.mov_ri(RDI, 0xB8000 + CON_BOTTOM)
    k.mov_r32i(RCX, 80)
    k.mov_ax_imm16(0x0720)
    k.emit(b"\x66\xf3\xab")           # rep stosw
    k.pop_r(RDI)
    k.pop_r(RSI)
    k.pop_r(RCX)
    k.pop_r(RAX)
    k.call_label("repaint_bars")    # scrolling must never damage the chrome
    k.ret()

    k.label("repaint_bars")         # title + status only (console untouched)
    k.store_byte_abs(SCROLL_LOCK, 1)
    k.load_r32_abs(RAX, VGA_ROW)    # painting moves the cursor -> save it
    k.store_r32_abs(SAVE_ROW, RAX)
    k.load_r32_abs(RAX, VGA_COL)
    k.store_r32_abs(SAVE_COL, RAX)
    k.mov_ri(RDI, 0xB8000)
    k.mov_al_imm(0x1F)
    k.call_label("fill_row")
    k.store_byte_abs(ATTR, 0x1F)
    k.xor_self(RAX)
    k.store_r32_abs(VGA_ROW, RAX)
    k.store_r32_abs(VGA_COL, RAX)
    k.lea("s_title")
    k.call_label("puts")
    k.mov_ri(RDI, 0xB8000 + STATUS_ROW)
    k.mov_al_imm(0x70)
    k.call_label("fill_row")
    k.store_byte_abs(ATTR, 0x70)
    k.mov_r32i(RAX, STATUS_ROW)
    k.store_r32_abs(VGA_ROW, RAX)
    k.xor_self(RAX)
    k.store_r32_abs(VGA_COL, RAX)
    k.lea("s_status")
    k.call_label("puts")
    k.store_byte_abs(ATTR, 0x0F)
    k.store_byte_abs(SCROLL_LOCK, 0)
    k.load_r32_abs(RAX, SAVE_ROW)   # restore the console cursor
    k.store_r32_abs(VGA_ROW, RAX)
    k.load_r32_abs(RAX, SAVE_COL)
    k.store_r32_abs(VGA_COL, RAX)
    k.ret()

    k.label("fill_row")             # rdi = row, al = attribute -> blank it
    k.push_r(RAX)
    k.push_r(RCX)
    k.push_r(RDI)
    k.emit(b"\xfc")                # cld
    k.emit(b"\x88\xc4")           # mov ah,al
    k.mov_al_imm(0x20)
    k.mov_r32i(RCX, 80)
    k.emit(b"\x66\xf3\xab")           # rep stosw
    k.pop_r(RDI)
    k.pop_r(RCX)
    k.pop_r(RAX)
    k.ret()

    k.label("draw_desktop")
    k.mov_ri(RDI, 0xB8000 + CON_TOP)     # clear the console area
    k.mov_r32i(RCX, 23 * 80)
    k.mov_ax_imm16(0x0720)
    k.emit(b"\x66\xf3\xab")
    k.mov_ri(RDI, 0xB8000)              # title bar
    k.mov_al_imm(0x1F)
    k.call_label("fill_row")
    k.store_byte_abs(ATTR, 0x1F)
    k.xor_self(RAX)
    k.store_r32_abs(VGA_ROW, RAX)
    k.store_r32_abs(VGA_COL, RAX)
    k.lea("s_title")
    k.call_label("puts")
    k.mov_ri(RDI, 0xB8000 + STATUS_ROW)  # status bar
    k.mov_al_imm(0x70)
    k.call_label("fill_row")
    k.store_byte_abs(ATTR, 0x70)
    k.mov_r32i(RAX, STATUS_ROW)
    k.store_r32_abs(VGA_ROW, RAX)
    k.xor_self(RAX)
    k.store_r32_abs(VGA_COL, RAX)
    k.lea("s_status")
    k.call_label("puts")
    k.store_byte_abs(ATTR, 0x0F)        # console home
    k.mov_r32i(RAX, CON_TOP)
    k.store_r32_abs(VGA_ROW, RAX)
    k.xor_self(RAX)
    k.store_r32_abs(VGA_COL, RAX)
    k.ret()

    k.label("update_status")            # repaint the tick counter in the status bar
    k.store_byte_abs(SCROLL_LOCK, 1)
    k.load_r32_abs(RAX, VGA_ROW)
    k.store_r32_abs(SAVE_ROW, RAX)
    k.load_r32_abs(RAX, VGA_COL)
    k.store_r32_abs(SAVE_COL, RAX)
    k.store_byte_abs(ATTR, 0x70)
    k.mov_r32i(RAX, STATUS_ROW)
    k.store_r32_abs(VGA_ROW, RAX)
    k.mov_r32i(RAX, 100)                # column 50 (byte offset = col*2)
    k.store_r32_abs(VGA_COL, RAX)
    k.lea("s_tick_lbl")
    k.call_label("puts")
    k.load_r32_abs(RDI, TICKS)
    k.call_label("print_u32")
    k.mov_al_imm(0x20)
    k.call_label("putc")
    k.mov_al_imm(0x20)
    k.call_label("putc")
    k.store_byte_abs(ATTR, 0x0F)
    k.store_byte_abs(SCROLL_LOCK, 0)
    k.load_r32_abs(RAX, SAVE_ROW)
    k.store_r32_abs(VGA_ROW, RAX)
    k.load_r32_abs(RAX, SAVE_COL)
    k.store_r32_abs(VGA_COL, RAX)
    k.ret()

    k.label("puts")                 # rsi = NUL-terminated
    k.label("puts_loop")
    k.lodsb()
    k.emit(b"\x84\xc0")             # test al,al -> ZF if zero
    k.jz("puts_done")
    k.call_label("putc")
    k.jmp("puts_loop")
    k.label("puts_done")
    k.ret()

    k.label("print_u32")            # edi = value
    k.mov_rr(RAX, RDI)
    k.xor_self(RDX)
    k.mov_r32i(RCX, 10)
    k.xor_self(R9)
    k.label("pu_loop")
    k.xor_self(RDX)
    k.div_r64(RCX)
    k.push_r(RDX)
    k.inc_r(R9)
    k.alu("test", RAX, RAX)
    k.jnz("pu_loop")
    k.label("pu_pop")
    k.pop_r(RDX)
    k.emit(b"\x80\xc2\x30")         # add dl,'0'
    k.emit(b"\x88\xd0")             # mov al,dl
    k.call_label("putc")
    k.dec_r(R9)
    k.jnz("pu_pop")
    k.ret()

    k.label("log_evt")              # al = event id; records (id, tick) in the ring
    k.push_r(RAX)
    k.push_r(RBX)
    k.push_r(RCX)
    k.push_r(RDX)
    k.movzx_eax_al()
    k.load_r32_abs(RCX, LOG_COUNT)
    k.alu_i("cmp", RCX, 32)
    k.jae("log_full")
    k.mov_rr(RBX, RCX)
    k.shl_r64_imm(RBX, 3)
    k.mov_r32i(RDX, LOG_BASE)
    k.alu("add", RDX, RBX)
    k.st8(RDX, 0, RAX)              # id
    k.load_r32_abs(RAX, TICKS)
    k.st32(RDX, 4, RAX)             # tick
    k.inc_dword_abs(LOG_COUNT)
    k.label("log_full")
    k.pop_r(RDX)
    k.pop_r(RCX)
    k.pop_r(RBX)
    k.pop_r(RAX)
    k.ret()

    k.label("print_prompt")
    k.lea("s_prompt")
    k.call_label("puts")
    k.ret()

    # ================================================================ IDT
    k.label("init_idt")
    k.mov_al_imm(1)
    k.call_label("log_evt")         # idt
    k.mov_r32i(RDI, IDT)
    k.xor_self(RAX)
    k.mov_r32i(RCX, 4096)
    k.rep_stosb()

    def gate(vec, label):
        base = IDT + vec * 16
        mov_label(RAX, label)
        k.mov_rr(RBX, RAX)
        k.alu_i("and", RBX, 0xFFFF)          # low16
        k.mov_rr(RCX, RAX)
        k.shr_r64_imm(RCX, 16)
        k.alu_i("and", RCX, 0xFFFF)          # mid16
        k.mov_rr(RDX, RAX)
        k.shr_r64_imm(RDX, 32)               # high32
        k.mov_rr(R8, RBX)
        k.alu_i("or", R8, 0x18 << 16)        # selector 0x18
        k.store_r32_abs(base + 0, R8)
        k.mov_rr(R9, RCX)
        k.shl_r64_imm(R9, 16)
        k.alu_i("or", R9, 0x8E00)            # P=1 DPL=0 type=interrupt gate
        k.store_r32_abs(base + 4, R9)
        k.store_r32_abs(base + 8, RDX)
        k.xor_self(R10)
        k.store_r32_abs(base + 12, R10)

    gate(0x20, "irq0")
    gate(0x21, "irq1")

    k.store_word_abs(IDTR, 0x0FFF)
    k.store_qword_abs(IDTR + 2, IDT)
    k.lidt_abs(IDTR)

    # ================================================================ PIC
    for port, val in ((0x20, 0x11), (0xA0, 0x11),
                      (0x21, 0x20), (0xA1, 0x28),
                      (0x21, 0x04), (0xA1, 0x02),
                      (0x21, 0x01), (0xA1, 0x01),
                      (0x21, 0xFC), (0xA1, 0xFF)):
        k.mov_dx_imm16(port)
        k.mov_al_imm(val)
        k.out_dx_al()

    # ================================================================ banner + boot log
    k.lea("s_banner")
    k.call_label("puts")
    k.lea("s_log_idt")
    k.call_label("puts")
    k.mov_al_imm(2)
    k.call_label("log_evt")         # pic
    k.lea("s_log_pic")
    k.call_label("puts")
    k.sti()
    k.mov_al_imm(3)
    k.call_label("log_evt")         # keyboard
    k.lea("s_log_kbd")
    k.call_label("puts")
    k.lea("s_log_acpi")
    k.call_label("puts")
    k.call_label("print_prompt")

    # ================================================================ main loop
    k.label("main_loop")
    k.load_r32_abs(RAX, RING_HEAD)
    k.load_r32_abs(RBX, RING_TAIL)
    k.alu("cmp", RAX, RBX)
    k.jz("idle")
    k.mov_rr(RDX, RBX)
    k.alu_i("and", RDX, 0xFF)
    k.mov_r32i(RCX, RING_BUF)
    k.alu("add", RCX, RDX)
    k.ld8(RAX, RCX, 0)
    k.inc_dword_abs(RING_TAIL)
    k.call_label("handle_char")
    k.jmp("main_loop")
    k.label("idle")
    # If IRQ1 has never fired, PS/2 may not be delivering interrupts on this firmware.
    # Fall back to polling the controller so the keyboard still works.
    k.load_r32_abs(RAX, IRQFLAG)
    k.alu("test", RAX, RAX)
    k.jnz("idle_hlt")
    k.mov_dx_imm16(0x64)            # status port
    k.in_al_dx()
    k.test_al_imm(0x01)             # bit0 = output buffer full
    k.jz("idle_hlt")
    k.mov_dx_imm16(0x60)
    k.in_al_dx()
    k.call_label("enqueue_scan")
    k.jmp("main_loop")
    k.label("idle_hlt")
    k.hlt()
    k.jmp("main_loop")

    # ================================================================ IRQ handlers
    k.label("irq0")
    k.push_r(RAX)
    k.inc_dword_abs(TICKS)
    k.mov_al_imm(0x20)
    k.out_imm8_al(0x20)
    k.pop_r(RAX)
    k.iretq()

    k.label("irq1")                 # PS/2 keyboard
    k.push_r(RAX)
    k.mov_r32i(RAX, 1)
    k.store_r32_abs(IRQFLAG, RAX)   # interrupts really are being delivered
    k.mov_dx_imm16(0x60)
    k.in_al_dx()
    k.call_label("enqueue_scan")
    k.mov_dx_imm16(0x20)
    k.mov_al_imm(0x20)              # EOI
    k.out_dx_al()
    k.pop_r(RAX)
    k.iretq()

    k.label("enqueue_scan")         # al = raw scancode; all regs preserved
    k.push_r(RAX)
    k.push_r(RBX)
    k.push_r(RCX)
    k.push_r(RDX)
    k.test_al_imm(0x80)             # key release?
    k.jnz("enq_done")
    k.movzx_eax_al()
    mov_label(RDX, "scancode_map")
    k.emit(b"\x0f\xb6\x04\x02")     # movzx eax, byte [rdx+rax]
    k.emit(b"\x84\xc0")             # test al,al  (unmapped key -> ignore)
    k.jz("enq_done")
    k.load_r32_abs(RCX, RING_HEAD)
    k.mov_rr(RBX, RCX)
    k.alu_i("and", RBX, 0xFF)
    k.mov_r32i(RDX, RING_BUF)
    k.alu("add", RDX, RBX)
    k.st8(RDX, 0, RAX)
    k.inc_dword_abs(RING_HEAD)
    k.label("enq_done")
    k.pop_r(RDX)
    k.pop_r(RCX)
    k.pop_r(RBX)
    k.pop_r(RAX)
    k.ret()

    # ================================================================ line editing
    k.label("handle_char")          # al = char
    k.cmp_al_imm(0x0A)
    k.jz("hc_enter")
    k.cmp_al_imm(0x08)
    k.jz("hc_bs")
    k.cmp_al_imm(0x20)
    k.jb("hc_ret")
    k.load_r32_abs(RCX, LINELEN)
    k.alu_i("cmp", RCX, 120)
    k.jae("hc_ret")
    k.mov_r32i(RBX, LINE)
    k.alu("add", RBX, RCX)
    k.st8(RBX, 0, RAX)
    k.inc_dword_abs(LINELEN)
    k.call_label("putc")
    k.label("hc_ret")
    k.ret()
    k.label("hc_bs")
    k.load_r32_abs(RCX, LINELEN)
    k.alu("test", RCX, RCX)
    k.jz("hc_ret")
    k.alu_i("sub", RCX, 1)
    k.store_r32_abs(LINELEN, RCX)
    k.mov_al_imm(0x08)
    k.call_label("putc")
    k.mov_al_imm(0x20)
    k.call_label("putc")
    k.mov_al_imm(0x08)
    k.call_label("putc")
    k.ret()
    k.label("hc_enter")
    k.mov_al_imm(0x0D)
    k.call_label("putc")
    k.mov_al_imm(0x0A)
    k.call_label("putc")
    k.call_label("run_command")
    k.call_label("print_prompt")
    k.ret()

    # ================================================================ commands
    k.label("run_command")
    k.load_r32_abs(RCX, LINELEN)
    k.mov_r32i(RBX, LINE)
    k.alu("add", RBX, RCX)
    k.st8_imm(RBX, 0, 0)
    k.alu("test", RCX, RCX)
    k.jz("rc_done")

    for name, target in (("s_cmd_help", "c_help"), ("s_cmd_ticks", "c_ticks"),
                         ("s_cmd_clear", "c_clear"), ("s_cmd_shutdown", "c_shutdown"),
                         ("s_cmd_reboot", "c_reboot"), ("s_cmd_log", "c_log")):
        k.lea(name)
        k.call_label("streq")
        k.emit(b"\x84\xc0")          # test al,al
        k.jnz(target)

    k.mov_al_imm(13)
    k.call_label("log_evt")         # unknown command
    k.lea("s_unknown")
    k.call_label("puts")
    k.mov_r32i(RSI, LINE)
    k.call_label("puts")
    k.lea("s_nl")
    k.call_label("puts")
    k.label("rc_done")
    k.store_qword_abs(LINELEN, 0)
    k.ret()

    k.label("c_log")
    k.call_label("dump_log")
    k.jmp("rc_done")

    k.label("dump_log")                 # print every recorded event, oldest first
    k.mov_al_imm(0x0D)                  # start on a fresh line
    k.call_label("putc")
    k.push_r(RBX)
    k.push_r(R12)
    k.push_r(R13)
    k.push_r(R14)
    k.xor_self(RBX)
    k.mov_ri(R12, LOG_BASE)
    k.mov_ri(R13, 0)                    # placeholder, patched below to the name table
    k.abs_fixups.append((len(k.b) - 8, "evt_tbl"))
    k.label("dl_loop")
    k.load_r32_abs(RAX, LOG_COUNT)
    k.alu("cmp", RBX, RAX)
    k.jae("dl_done")
    k.mov_rr(RAX, RBX)
    k.shl_r64_imm(RAX, 3)
    k.mov_rr(RCX, R12)                  # -> ring entry
    k.alu("add", RCX, RAX)
    k.mov_rr(R14, RCX)                  # keep the entry address
    k.movzx8(RAX, RCX, 0)               # the stored EVENT ID (not the entry index)
    k.shl_r64_imm(RAX, 3)
    k.mov_rr(RCX, R13)                  # -> name table[id]
    k.alu("add", RCX, RAX)
    k.ld64(RSI, RCX, 0)
    k.call_label("puts")
    k.lea("s_tseg")
    k.call_label("puts")
    k.ld32(RDI, R14, 4)                 # tick
    k.call_label("print_u32")
    k.lea("s_nl")
    k.call_label("puts")
    k.inc_r(RBX)
    k.jmp("dl_loop")
    k.label("dl_done")
    k.pop_r(R14)
    k.pop_r(R13)
    k.pop_r(R12)
    k.pop_r(RBX)
    k.ret()

    k.label("c_help")
    k.mov_al_imm(8)
    k.call_label("log_evt")
    k.lea("s_help_text")
    k.call_label("puts")
    k.jmp("rc_done")

    k.label("c_ticks")
    k.mov_al_imm(9)
    k.call_label("log_evt")
    k.lea("s_ticks_pre")
    k.call_label("puts")
    k.load_r32_abs(RDI, TICKS)
    k.call_label("print_u32")
    k.lea("s_nl")
    k.call_label("puts")
    k.jmp("rc_done")

    k.label("c_clear")
    k.mov_al_imm(10)
    k.call_label("log_evt")
    k.call_label("draw_desktop")
    k.jmp("rc_done")

    k.label("c_reboot")
    k.mov_al_imm(12)
    k.call_label("log_evt")
    k.lea("s_reboot")
    k.call_label("puts")
    k.mov_dx_imm16(0x64)
    k.mov_al_imm(0xFE)
    k.out_dx_al()
    k.label("reboot_hang")
    k.hlt()
    k.jmp("reboot_hang")

    # ---- shutdown: ACPI FADT -> S5, with a safe halted fallback ----
    k.label("c_shutdown")
    k.mov_al_imm(11)
    k.call_label("log_evt")
    k.cli()
    k.mov_r32i(RBX, 0xE0000)         # scan BIOS ROM 0xE0000..0xFFFFF
    k.mov_r32i(R15, 0x100000)
    k.label("acpi_scan")
    k.alu("cmp", RBX, R15)
    k.jae("acpi_none")
    k.ld32(R8, RBX, 0)
    k.alu_i("cmp", R8, 0x20445352)   # "RSD " little-endian
    k.jnz("acpi_next")
    k.ld32(R8, RBX, 4)
    k.alu_i("cmp", R8, 0x20525450)   # "PTR "
    k.jnz("acpi_next")
    k.mov_rr(RDI, RBX)               # checksum 20 bytes == 0
    k.mov_r32i(RCX, 20)
    k.xor_self(RAX)
    k.label("acpi_sum")
    k.emit(b"\x02\x07")              # add al,[rdi]
    k.inc_r(RDI)
    k.dec_r(RCX)
    k.jnz("acpi_sum")
    k.emit(b"\x84\xc0")
    k.jnz("acpi_next")
    k.jmp("acpi_found")
    k.label("acpi_next")
    k.alu_i("add", RBX, 16)
    k.jmp("acpi_scan")

    k.label("acpi_none")
    k.mov_al_imm(5)
    k.call_label("log_evt")         # acpi table missing
    k.lea("s_acpi_none")
    k.call_label("puts")
    k.jmp("shutdown_halt")

    k.label("acpi_found")
    k.mov_al_imm(4)
    k.call_label("log_evt")         # acpi table found
    k.ld32(R12, RBX, 16)             # RSDT
    k.alu("test", R12, R12)
    k.jnz("acpi_have_rsdt")
    k.ld32(R12, RBX, 24)             # XSDT low half
    k.label("acpi_have_rsdt")
    k.alu("test", R12, R12)
    k.jz("acpi_none")
    k.ld32(R13, R12, 4)              # table length
    k.alu_i("sub", R13, 36)
    k.shr_r64_imm(R13, 2)            # entry count
    k.mov_rr(R14, R12)
    k.alu_i("add", R14, 36)
    k.label("acpi_walk")
    k.alu("test", R13, R13)
    k.jz("acpi_none")
    k.ld32(R15, R14, 0)
    k.ld32(R8, R15, 0)
    k.alu_i("cmp", R8, 0x50434146)   # "FACP"
    k.jz("acpi_fadt")
    k.alu_i("add", R14, 4)
    k.alu_i("sub", R13, 1)
    k.jmp("acpi_walk")

    k.label("acpi_fadt")
    k.ld32(R9, R15, 64)              # PM1a_CNT_BLK
    k.alu_i("and", R9, 0xFFFF)
    k.ld32(R10, R15, 0xB0)           # SLP_TYPa bits 10..12
    k.shr_r64_imm(R10, 10)
    k.alu_i("and", R10, 7)
    k.shl_r64_imm(R10, 10)
    k.alu_i("or", R10, 0x2000)       # SLP_EN
    k.mov_al_imm(6)
    k.call_label("log_evt")         # S5 issued
    k.lea("s_acpi_ok")
    k.call_label("puts")
    k.mov_r32i(RDX, 0x80)            # ACPI io delay
    k.xor_self(RAX)
    k.out_dx_al()
    k.mov_rr(RDX, R9)                # dx = PM1a_CNT
    k.mov_rr(RAX, R10)               # ax = SLP_TYP | SLP_EN
    k.outw_dx_ax()
    k.mov_r32i(RDX, 0x80)
    k.xor_self(RAX)
    k.out_dx_al()

    k.label("shutdown_halt")
    k.mov_al_imm(7)
    k.call_label("log_evt")         # halted
    k.call_label("dump_log")
    k.lea("s_halted")
    k.call_label("puts")
    k.cli()
    k.label("halt_loop")
    k.hlt()
    k.jmp("halt_loop")

    # ================================================================ string compare
    k.label("streq")                 # rsi = candidate; compares with LINE
    k.mov_r32i(RDI, LINE)
    k.label("streq_loop")
    k.movzx8(RAX, RSI, 0)
    k.movzx8(RCX, RDI, 0)
    k.alu("cmp", RAX, RCX)
    k.jnz("streq_no")
    k.alu("test", RAX, RAX)
    k.jz("streq_yes")
    k.inc_r(RSI)
    k.inc_r(RDI)
    k.jmp("streq_loop")
    k.label("streq_yes")
    k.mov_al_imm(1)
    k.ret()
    k.label("streq_no")
    k.xor_self(RAX)
    k.ret()

    # ================================================================ data
    def s(label, text):
        k.label(label)
        k.emit(text.encode() + b"\x00")

    s("s_banner", "DsOS v0.5  desktop console\r\n")
    s("s_title", " DsOS v0.5  -  keyboard + shell + ACPI  ")
    s("s_status", " help  ticks  clear  log  shutdown  reboot ")
    s("s_tick_lbl", "tick: ")
    s("s_log_idt", "[boot] idt: 256 gates, irq0/irq1 installed\r\n")
    s("s_log_pic", "[boot] pic: remapped to 0x20/0x28, irq0+irq1 unmasked\r\n")
    s("s_log_kbd", "[boot] keyboard: irq1 enabled (poll fallback armed)\r\n")
    s("s_log_acpi", "[boot] acpi: parser ready, run 'shutdown' to power off\r\n")
    s("s_prompt", "dsos> ")
    s("s_nl", "\r\n")
    s("s_unknown", "unknown: ")
    s("s_help_text",
      "commands:\r\n"
      "  help      show this\r\n"
      "  ticks     timer interrupt count\r\n"
      "  clear     clear the screen\r\n"
      "  log       show the event log\r\n"
      "  shutdown  ACPI power off\r\n"
      "  reboot    reset the machine\r\n")
    s("s_ticks_pre", "ticks=")
    s("s_cmd_help", "help")
    s("s_cmd_ticks", "ticks")
    s("s_cmd_clear", "clear")
    s("s_cmd_shutdown", "shutdown")
    s("s_cmd_reboot", "reboot")
    s("s_cmd_log", "log")
    s("s_tseg", " t=")
    s("s_reboot", "rebooting...\r\n")
    s("s_acpi_ok", "acpi: FADT found, S5 poweroff...\r\n")
    s("s_acpi_none", "acpi: no RSDP found\r\n")
    s("s_halted", "System halted. You can power off now.\r\n")

    k.label("evt_tbl")                  # 14 pointers, patched with abs fixups
    for _i in range(14):
        k.emit(b"\x00" * 8)
        k.abs_fixups.append((len(k.b) - 8, f"s_ev{_i}"))
    for _i, _t in enumerate(("boot", "idt ok", "pic ok", "keyboard ok",
                             "acpi table found", "acpi table missing", "S5 issued", "halted",
                             "cmd help", "cmd ticks", "cmd clear", "cmd shutdown",
                             "cmd reboot", "cmd unknown")):
        s(f"s_ev{_i}", _t)

    k.label("scancode_map")
    k.emit(bytes(SCAN.get(i, 0) for i in range(128)))

    blob = bytearray(k.b)

    # resolve relative call/jmp/jcc fixups (Asm.fix) — gen_boot does this inside stage2()
    for at, label, n in k.fix:
        target = k.labels[label]
        rel = target - (at + n)
        if n == 4:
            blob[at:at + n] = struct.pack("<i", rel)
        else:
            blob[at:at + n] = struct.pack("<h", rel)

    # resolve absolute-address fixups (mov reg, imm64 of a label address)
    for pos, label in k.abs_fixups:
        addr = ENTRY + k.labels[label]
        blob[pos:pos + 8] = struct.pack("<Q", addr)

    return bytes(blob), dict(k.labels)
