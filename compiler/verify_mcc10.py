"""compiler/verify_mcc10.py — 自举预备：Ds 写的编译器开始支持它自己需要的内建

链条：
  mcc10.ds  --(T0: Python mini.py)-->  T1（10803 字节）
  T1 编译一段使用 store8/load8/sys_exit 的源码 → 生成机器码 → 执行 → 断言结果

这一步的意义：编译器的"能力集"开始覆盖"它自己源码要用到的东西"，
是自举固定点（T2 == T3）的前置条件。
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
    """用 T1 编译 src，并执行它生成的代码。"""
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x200000)
    uc.mem_write(0x10000, T1)
    uc.mem_write(0x20000, src.encode() + b"\x00")   # mcc10 的源码缓冲在 0x20000
    uc.reg_write(UC_X86_REG_RSP, 0x30000)
    uc.reg_write(UC_X86_REG_RBP, 0x30000)
    uc.reg_write(UC_X86_REG_RIP, 0x10000)
    st = {}

    def on_syscall(u, ud):
        if u.reg_read(UC_X86_REG_RAX) == 60:
            st["exit"] = u.reg_read(UC_X86_REG_RDI)
            u.emu_stop()

    uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
    err = None
    try:
        uc.emu_start(0x10000, 0, count=20000000)
    except UcError as e:
        err = e
    n = int.from_bytes(bytes(uc.mem_read(0x3008, 4)), "little")
    gen = bytes(uc.mem_read(0x6000, min(max(n, 0), 48)))
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
