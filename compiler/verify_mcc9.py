"""compiler/verify_mcc9.py — ⑤ 第十一圈：&& / ||，并做自举可行性探测。

两部分：
  A. 功能验收：&& / || 的条件与表达式
  B. 自举探测：把 mcc9.ds 自己的源码喂给 mcc9，报告它卡在第几字节/哪一行
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
MCC = (HERE / "mcc9.ds").read_text(encoding="utf-8")
code = compile_source(MCC)
print(f"mcc9.ds 编译: {len(code)} bytes\n")

CASES = [
    ("let a = 1 let b = 0 if a == 1 && b == 0 { a = 42 } a = a + 0", 42),
    ("let a = 1 let b = 1 if a == 1 && b == 0 { a = 42 } else { a = 7 } a = a + 0", 7),
    ("let a = 0 let b = 5 if a == 1 || b == 5 { a = 42 } a = a + 0", 42),
    ("let a = 0 let b = 0 if a == 1 || b == 5 { a = 42 } else { a = 7 } a = a + 0", 7),
    ("let i = 0 while i < 3 && i < 9 { i = i + 1 } i = i + 0", 3),
    ("let i = 0 while i < 0 || i < 4 { i = i + 1 } i = i + 0", 4),
]


def run(src, count=12000000):
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x60000)
    # 宿主二进制放 0x8000：0x3000 起是编译器自己的全局数据区（放 0x1000 会自覆盖）
    HOST = 0x10000
    uc.mem_write(HOST, code)
    uc.mem_write(0x20000, src.encode() + b"\x00")
    uc.reg_write(UC_X86_REG_RSP, 0x30000)
    uc.reg_write(UC_X86_REG_RBP, 0x30000)
    st = {}

    def on_syscall(u, ud):
        if u.reg_read(UC_X86_REG_RAX) == 60:
            st["exit"] = u.reg_read(UC_X86_REG_RDI)
            u.emu_stop()

    uc.hook_add(UC_HOOK_INSN, on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
    err = None
    try:
        uc.emu_start(0x10000, 0, count=count)
    except UcError as e:
        err = e
    n = int.from_bytes(bytes(uc.mem_read(0x3008, 4)), "little")
    pos = int.from_bytes(bytes(uc.mem_read(0x3000, 4)), "little")
    return st.get("exit"), err, n, pos


ok_all = True
print("--- A. 功能验收 ---")
for src, want in CASES:
    got, err, n, _ = run(src)
    ok = got == want
    ok_all &= ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {src[:50]!r:54} want={want:<3} got={got}  ({n}B)")
    if err:
        print(f"          stopped: {err}")

print("\n--- B. 自举探测：mcc9 编译自己 ---")
got, err, n, pos = run(MCC, count=2000000)
lines = MCC[:pos].count("\n") + 1
line_text = MCC.splitlines()[lines - 1] if lines - 1 < len(MCC.splitlines()) else "?"
print(f"  完成: {'是' if err is None and got is not None else '否'}  错误: {err}")
print(f"  已生成代码: {n} 字节；停在源码 pos={pos}（第 {lines} 行）")
print(f"  该行: {line_text.strip()[:70]!r}")

print("\nRESULT:", "PASS" if ok_all else "FAIL")
sys.exit(0 if ok_all else 1)
