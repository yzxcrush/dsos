# DsOS Toolchain — Step 4：函数调用 + 栈帧

> **目标**：生成 SysV 风格 prologue/epilogue，支持局部变量、参数、用户函数调用。  
> **不经过** C / 汇编器 / 链接器 / libc。

## 1. 输入

```ds
# layer: Ds-
fn add1(x: i32) -> i32 {
    return x
}

fn _start() {
    let y = add1(41)
    sys_exit(y)
}
```

## 2. 输出

```bash
python3 dsos/toolchain/step4/dscc_step4.py \
  dsos/toolchain/step4/examples/call.ds --emit bin -o call.bin
python3 dsos/toolchain/step4/loader.py call.bin
echo $?      # 41
```

或走统一入口：

```bash
./dsos/bin/dsos --stage4 dsos/toolchain/step4/examples/call.ds
echo $?      # 41
```

`call.bin` 的反汇编（ELF 版）：

```asm
_start:
  push rbp
  mov  rbp, rsp
  sub  rsp, 16
  mov  edi, 41
  call add1
  mov  [rbp-8], rax
  mov  rax, [rbp-8]
  mov  rdi, rax
  mov  eax, 60
  syscall

add1:
  push rbp
  mov  rbp, rsp
  sub  rsp, 16
  mov  [rbp-8], rdi
  mov  rax, [rbp-8]
  leave
  ret
```

## 3. 栈帧规则

- prologue：`push rbp; mov rbp,rsp; sub rsp, frame`
- epilogue：`leave; ret`
- 参数槽：`[rbp-8]`、`[rbp-16]`…
- 局部变量槽：参数之后继续 `[rbp-8*n]`
- `frame` 按 16 字节对齐
- 调用参数：`rdi, rsi, rdx, rcx, r8, r9`
- 返回值：`rax`

## 4. 文件与标注

| 文件 | 层 | 说明 | 大小 |
|---|---|---|---|
| `dscc_step4.py` | Ds- | 编译器 + ELF 输出 | — |
| `machine.py` | Ds- | 栈帧/调用 VM | — |
| `loader.py` | Ds- | Step 4 加载器 | — |
| `examples/call.ds` | Ds- | 输入 | 11 行 |
| `examples/call.bin` | Ds- | 机器码 | 60 B |
| `examples/call.elf` | Ds- | ELF64 | 180 B |
| `test_step4.py` | — | 4 项回归 | — |

依赖：Step 2 的 SysV 寄存器/syscall 约定。

## 5. 验证

```bash
python3 -m unittest dsos/toolchain/step4/test_step4.py -v
./dsos/bin/dsos --stage4 dsos/toolchain/step4/examples/call.ds; echo $?
```

期望：

```text
41
```

静态反汇编：

```bash
readelf -h dsos/toolchain/step4/examples/call.elf
llvm-objdump -d --start-address=0x400078 --stop-address=0x4000b4 \
  dsos/toolchain/step4/examples/call.elf
```

## 6. 边界

- 只支持：无/有参数函数、`return`、`let` 初值、用户函数调用、`sys_exit`。
- 不支持：算术、`if/else`、循环、`sys_write` 变量消息。
- 参数最多 6 个。
- 无寄存器分配；参数/局部变量全部走栈槽。
- 无优化。

## 7. 下一步 Step 5

- `add/sub/cmp/je/jne/jl/jg`
- `if/else` 分支
- 在 VM 中扩展条件标志与跳转
