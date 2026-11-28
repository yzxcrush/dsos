"""compiler/verify_selfhost.py — 自举固定点验证

链条：
  T0 = Python 的 mini.py（bootstrap 编译器）
  mcc10.ds --T0--> T1
  mcc10.ds --T1--> T2
  mcc10.ds --T2--> T3

若 T2 == T3，说明 Ds 编译器已经能完整编译自己，达到自举固定点。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
SRC = (HERE / "mcc10.ds").read_bytes()
print(f"mcc10.ds 源码: {len(SRC)} 字节")

# T0：Python 编译器
T1 = compile_source(SRC.decode("utf-8"))
print(f"T1 = T0(mcc10.ds): {len(T1)} 字节")

HOST = 0x10000      # 编译器自身入口
SRCBUF = 0x20000    # 源码缓冲（mcc10 约定）
OUTBUF = 0x6000     # 生成代码缓冲（mcc10 约定）
LENVAR = 0x3008     # 生成长度变量
STACK = 0x800000


def compile_with(compiler, label):
    """mcc10 是纯编译器：运行到 sys_exit 即完成发射，产物在 OUTBUF。"""
    """用 compiler 编译 mcc10.ds，返回生成的机器码。"""
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x1000000)
    uc.mem_write(HOST, compiler)
    uc.mem_write(SRCBUF, SRC + b"\x00")
    uc.reg_write(UC_X86_REG_RSP, STACK)
    uc.reg_write(UC_X86_REG_RBP, STACK)
    uc.reg_write(UC_X86_REG_RIP, HOST)
    st = {"halt": None, "syscall": None}

    def on_code(u, addr, size, ud):
        # 生成代码入口：停住，不要执行它（否则会递归编译）
        if addr == OUTBUF:
            st["halt"] = addr
            u.emu_stop()

    def on_sc(u, ud):
        if u.reg_read(UC_X86_REG_RAX) == 60:
            st["syscall"] = u.reg_read(UC_X86_REG_RDI)
            u.emu_stop()

    def on_wr(u, access, addr, size, value, ud):
        if addr == 0x3008 and value > 80000:
            st["overflow"] = True
            u.emu_stop()

    uc.hook_add(UC_HOOK_MEM_WRITE, on_wr, None, 0x3008, 0x300B)
    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_INSN, on_sc, None, 1, 0, UC_X86_INS_SYSCALL)
    err = None
    try:
        uc.emu_start(HOST, 0, count=300000000)
    except UcError as e:
        err = e
    n = int.from_bytes(bytes(uc.mem_read(LENVAR, 4)), "little")
    out = bytes(uc.mem_read(OUTBUF, n)) if 0 < n <= 0x40000 else b""
    if st.get("overflow"):
        print(f"  {label}: !! 输出超 80000，已强制停止（pos={int.from_bytes(bytes(uc.mem_read(0x3000,4)),'little')}）")
    print(f"  {label}: 生成 {n} 字节  stop={'outbuf' if st['halt'] else st['syscall']}  err={err}")
    return out


print("\nT2 = T1(mcc10.ds) …")
T2 = compile_with(T1, "T1 编译自身")
print("T3 = T2(mcc10.ds) …")
T3 = compile_with(T2, "T2 编译自身") if T2 else b""

print(f"\nT1 长度: {len(T1)}")
print(f"T2 长度: {len(T2)}")
print(f"T3 长度: {len(T3)}")

ok2 = len(T2) > 0
ok3 = len(T3) > 0
fixed = ok2 and ok3 and T2 == T3
print(f"\n[{'PASS' if ok2 else 'FAIL'}] T2 生成成功")
print(f"[{'PASS' if ok3 else 'FAIL'}] T3 生成成功")
print(f"[{'PASS' if fixed else 'FAIL'}] 固定点 T2 == T3")

if ok2 and ok3 and not fixed:
    for i in range(min(len(T2), len(T3))):
        if T2[i] != T3[i]:
            print(f"  首个差异 @ {i}: T2={T2[i]:#04x} T3={T3[i]:#04x}")
            print(f"  T2 上下文: {T2[max(0,i-8):i+8].hex(' ')}")
            print(f"  T3 上下文: {T3[max(0,i-8):i+8].hex(' ')}")
            break

print("\nRESULT:", "PASS" if fixed else "FAIL")
sys.exit(0 if fixed else 1)
