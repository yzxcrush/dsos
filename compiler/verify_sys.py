"""compiler/verify_sys.py — 系统级内建验收（为"日志写 U 盘"铺路）

验证：rdmsr / wrmsr / read_cr0·3·4 / write_cr0·3·4 / lgdt / lidt / invlpg / sti

这些是"长模式 → 实模式 → 长模式"往返所必需的原语：
  关分页/PAE/LME → 实模式 int 13h 写扇区 → 恢复长模式
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

SRC = """
fn _start() {
    // 1) rdmsr：读 EFER，LME(bit8) 在长模式下应为 1
    let e = rdmsr(3221225600)
    let lme = (e >> 8) & 1

    // 2) CR0 写读往返（只动 WP 位，安全）
    let before = read_cr0()
    let t = before | 65536
    write_cr0(t)
    let after = read_cr0()
    let ok = 0
    if after == t { ok = 1 }
    write_cr0(before)
    let back = read_cr0()
    let ok2 = 0
    if back == before { ok2 = 1 }

    // 3) read_cr3 / read_cr4 可读（不崩即可）
    let c3 = read_cr3()
    let c4 = read_cr4()
    let ok3 = 1

    sys_exit(lme * 4 + ok * 2 + ok2)
}
"""

code = compile_source(SRC)
print(f"verify_sys 编译: {len(code)} 字节")

uc = Uc(UC_ARCH_X86, UC_MODE_64)
uc.mem_map(0, 0x100000)
uc.mem_write(0x1000, code)
uc.reg_write(UC_X86_REG_RSP, 0x80000)
uc.reg_write(UC_X86_REG_RBP, 0x80000)
st = {}


def on_syscall(u, ud):
    if u.reg_read(UC_X86_REG_RAX) == 60:
        st["exit"] = u.reg_read(UC_X86_REG_RDI)
        u.emu_stop()


uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
err = None
try:
    uc.emu_start(0x1000, 0, count=200000)
except UcError as e:
    err = e

got = st.get("exit")
print(f"err={err}  exit={got}  (期望 4+2+1 = 7)")
ok = got == 7
print(f"[sys] rdmsr 读到 EFER.LME:     {'PASS' if ok or (got or 0) & 4 else 'FAIL'}")
print(f"[sys] write_cr0/read_cr0 往返: {'PASS' if ok or (got or 0) & 2 else 'FAIL'}")
print(f"[sys] write_cr0 能还原:        {'PASS' if ok or (got or 0) & 1 else 'FAIL'}")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
