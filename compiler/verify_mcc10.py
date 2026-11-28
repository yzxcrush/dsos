"""compiler/verify_mcc10.py — 自举预备：Ds 写的编译器开始支持它自己需要的内建

链条：
  mcc10.ds  --(T0: Python mini.py)-->  T1
  T1 编译一段使用 store8/load8/sys_exit 的源码 → 生成机器码 → harness 执行 → 断言结果

注：mcc10 现在是"纯编译器"（只发射、不执行产物，见 sys_exit(0)），
    执行产物由本脚本负责（两阶段）。
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
MCC_SRC = (HERE / "mcc10.ds").read_text(encoding="utf-8")
T1 = compile_source(MCC_SRC)
print(f"mcc10.ds 由 T0(Python) 编译 → T1: {len(T1)} 字节")

HOST = 0x10000
SRCBUF = 0x20000
OUTBUF = 0x6000
LENVAR = 0x3008
STACK = 0x800000

CASES = [
    ("store8 + load8", """
    store8(32768, 65)
    let x = load8(32768)
    sys_exit(x)
""", 65),
    ("store32 + load32", """
    store32(32768, 4242)
    let x = load32(32768)
    sys_exit(x)
""", 4242),
    ("内建 + 算术", """
    store8(32768, 40)
    store8(12289, 2)
    let a = load8(32768)
    let b = load8(12289)
    sys_exit(a + b)
""", 42),
]


def run_t1(src):
    """两阶段：① 用 T1 编译 src（纯发射）；② 执行发射出的代码并取返回值。"""
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x1000000)
    uc.mem_write(HOST, T1)
    uc.mem_write(SRCBUF, src.encode() + b"\x00")
    uc.reg_write(UC_X86_REG_RSP, STACK)
    uc.reg_write(UC_X86_REG_RBP, STACK)
    uc.reg_write(UC_X86_REG_RIP, HOST)
    st = {}

    def on_sc(u, ud):
        if u.reg_read(UC_X86_REG_RAX) == 60:
            st["exit"] = u.reg_read(UC_X86_REG_RDI)
            u.emu_stop()

    uc.hook_add(UC_HOOK_INSN, on_sc, None, 1, 0, UC_X86_INS_SYSCALL)
    err = None
    # 阶段 ①：编译
    try:
        uc.emu_start(HOST, 0, count=60000000)
    except UcError as e:
        err = f"compile: {e}"
    n = int.from_bytes(bytes(uc.mem_read(LENVAR, 4)), "little")
    gen = bytes(uc.mem_read(OUTBUF, min(max(n, 0), 48))) if 0 < n <= 0x40000 else b""
    if err or not gen:
        return None, err, n, gen
    # 阶段 ②：执行产物
    st.pop("exit", None)
    uc.reg_write(UC_X86_REG_RSP, STACK)
    uc.reg_write(UC_X86_REG_RBP, STACK)
    uc.reg_write(UC_X86_REG_RIP, OUTBUF)
    try:
        uc.emu_start(OUTBUF, 0, count=20000000)
    except UcError as e:
        err = f"exec: {e}"
    return st.get("exit"), err, n, gen


ok_all = True
for name, src, want in CASES:
    got, err, n, gen = run_t1(src)
    ok = got == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:16} want={want:<5} got={got}  "
          f"生成={n}B {gen.hex(' ')[:46]}")
    if err:
        print(f"          stopped: {err}")

print("\nRESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
