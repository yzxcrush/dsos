# DsOS Toolchain — Step 5：算术 + 条件跳转

> **目标**：生成 `add/sub/cmp/je/jne/jl/jg/jmp`，支持 `if/else`，在 DsOS 加载器中执行分支。  
> **不经过** C / 汇编器 / 链接器 / libc。

## 1. 输入

```ds
# layer: Ds-
fn add(a: i32, b: i32) -> i32 {
    return a + b
}

fn _start() {
    let x = add(20, 22)
    if x == 42 {
        sys_exit(42)
    } else {
        sys_exit(1)
    }
}
```

## 2. 运行

```bash
./dsos/bin/dsos --stage5 dsos/toolchain/step5/examples/branch.ds
echo $?      # 42
```

或：

```bash
python3 dsos/toolchain/step5/dscc_step5.py \
  dsos/toolchain/step5/examples/branch.ds --emit bin -o branch.bin
python3 dsos/toolchain/step4/loader.py branch.bin
echo $?      # 42
```

## 3. 生成指令

```asm
_start:
  push rbp
  mov  rbp, rsp
  sub  rsp, 16
  mov  edi, 20
  mov  esi, 22
  call add
  mov  [rbp-8], rax
  mov  rax, [rbp-8]
  push rax
  mov  eax, 42
  pop  rcx
  cmp  rcx, rax
  je   then
  jmp  else
then:
  mov  eax, 42
  mov  rdi, rax
  mov  eax, 60
  syscall
  jmp  end
else:
  mov  eax, 1
  mov  rdi, rax
  mov  eax, 60
  syscall
end:
  mov  eax, 0
  leave
  ret

add:
  push rbp
  mov  rbp, rsp
  sub  rsp, 16
  mov  [rbp-8], rdi
  mov  [rbp-16], rsi
  mov  rax, [rbp-8]
  push rax
  mov  rax, [rbp-16]
  pop  rcx
  add  rax, rcx
  leave
  ret
```

## 4. 覆盖的指令

| 类别 | 指令 |
|---|---|
| 算术 | `add rax, rcx`、`sub rcx, rax` |
| 比较 | `cmp rcx, rax`、`cmp rax, 0` |
| 条件跳转 | `je`、`jne`、`jl`、`jg` |
| 无条件跳转 | `jmp rel32` |
| 布尔化 | `sete/setne/setl/setg`、`movzx` |

## 5. 文件与标注

| 文件 | 层 | 说明 | 大小 |
|---|---|---|---|
| `dscc_step5.py` | Ds- | Step 5 编译器入口 | — |
| `examples/branch.ds` | Ds- | 输入 | 13 行 |
| `examples/branch.bin` | Ds- | 机器码 | 138 B |
| `examples/branch.elf` | Ds- | ELF64 | 258 B |
| `test_step5.py` | — | 4 项回归 | — |

依赖：Step 4 的栈帧/函数调用、Step 2 的 syscall ABI。

## 6. 验证

```bash
python3 -m unittest dsos/toolchain/step5/test_step5.py -v
./dsos/bin/dsos --stage5 dsos/toolchain/step5/examples/branch.ds; echo $?
```

期望 `42`。

静态反汇编：

```bash
readelf -h dsos/toolchain/step5/examples/branch.elf
llvm-objdump -d --start-address=0x400078 --stop-address=0x400110 \
  dsos/toolchain/step5/examples/branch.elf
```

## 7. 边界

- 不支持：循环、`*`/`/`、`&&`/`||`、字符串变量、数组。
- 条件只支持 `== != < >` 和整数真值。
- VM 覆盖当前生成指令；Step 6 再加循环/更多运算。

## 8. 当前 DsOS 能力

```text
Ds .ds
  → dscc_step5
  → x86_64 .bin/.elf
  → DsOS loader
  → 函数调用 / 栈帧 / 局部变量 / 算术 / if-else / syscall
  → 输出或退出码
```

这是当前最小可运行 DsOS 工具链的完整闭环。
