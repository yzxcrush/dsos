"""compiler/diag_selfhost.py — 定位自举 codegen 异常

思路：把 mcc10.ds 按顶层函数/语句切块，逐块用
  T0（Python mini.py） 和 T1（Ds 写的 mcc10，已由 T0 编译）
编译，比对各块生成长度。长度差异大的块 = T1 的 codegen bug 所在。
"""
import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import *
from unicorn.x86_const import *
from mini import compile_source

HERE = pathlib.Path(__file__).resolve().parent
SRC_TEXT = (HERE / "mcc10.ds").read_text(encoding="utf-8")
T1 = compile_source(SRC_TEXT)
print(f"T1 = {len(T1)} 字节\n")

HOST, SRCBUF, OUTBUF, LENVAR, STACK = 0x10000, 0x20000, 0x6000, 0x3008, 0x30000


def t1_len(src: str):
    """用 T1 编译 src，返回生成长度。"""
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    uc.mem_map(0, 0x400000)
    uc.mem_write(HOST, T1)
    uc.mem_write(SRCBUF, src.encode("utf-8") + b"\x00")
    uc.reg_write(UC_X86_REG_RSP, STACK)
    uc.reg_write(UC_X86_REG_RBP, STACK)
    uc.reg_write(UC_X86_REG_RIP, HOST)
    st = {}

    def on_code(u, addr, size, ud):
        if addr == OUTBUF:
            st["stop"] = "outbuf"
            u.emu_stop()

    def on_sc(u, ud):
        if u.reg_read(UC_X86_REG_RAX) == 60:
            st["stop"] = "exit"
            u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_INSN, on_sc, None, 1, 0, UC_X86_INS_SYSCALL)
    try:
        uc.emu_start(HOST, 0, count=60000000)
    except UcError:
        pass
    n = int.from_bytes(bytes(uc.mem_read(LENVAR, 4)), "little")
    return n if 0 < n <= 0x30000 else -1


# 按顶层块切分：以 "fn " 开头到下一个顶层 "fn " 或文件尾
lines = SRC_TEXT.splitlines(keepends=True)
blocks, cur = [], []
for ln in lines:
    if re.match(r"^fn\s", ln) and cur and not any(c.startswith("fn ") for c in cur):
        pass
    if re.match(r"^fn\s", ln) and cur:
        blocks.append("".join(cur))
        cur = [ln]
    else:
        cur.append(ln)
if cur:
    blocks.append("".join(cur))

DUMMY = "\nfn _start() { sys_exit(0) }\n"
print(f"{'累积前缀':<22}{'T0':>7}{'T1':>8}{'dT0':>7}{'dT1':>7}  备注")
print("-" * 60)
prev0 = prev1 = None
bad_blk = None
for k in range(1, len(blocks) + 1):
    src = "".join(blocks[:k]) + DUMMY
    m = re.match(r"^\s*fn\s+([a-z_0-9]+)", blocks[k-1])
    name = m.group(1) if m else f"(注释块{k})"
    try:
        l0 = len(compile_source(src))
    except Exception as e:
        print(f"{name:<22}{'T0 异常: '+type(e).__name__:>7}")
        continue
    l1 = t1_len(src)
    d0 = l0 - prev0 if prev0 is not None else l0
    d1 = (l1 - prev1) if (prev1 is not None and l1 >= 0) else l1
    note = ""
    if prev1 is not None and l1 >= 0 and d1 > d0 * 1.4 + 16:
        note = "<<< 增量异常"
        if bad_blk is None:
            bad_blk = (name, blocks[k-1])
    print(f"{name:<22}{l0:>7}{l1:>8}{d0:>7}{d1:>7}  {note}")
    prev0, prev1 = l0, l1

if bad_blk:
    name, blk = bad_blk
    print(f"\n=== 首个增量异常函数: {name} ===")
    for ln in blk.splitlines()[:20]:
        print("   ", ln)
else:
    print("\n未发现单函数级异常，问题可能在语句级")
