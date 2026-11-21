# DsOS Toolchain — Step 1：手写 x86_64 机器码

> **目标**：不经过 C、汇编器、链接器、libc，直接得到可加载的机器码。  
> **本步只做最小 sys_write + exit**；Step 2 才把它们变成 dscc 的代码生成器。

## 0. 一个必须先说清的设计决定

`sys_write` 是**系统调用**：它必须有一个内核/异常入口来接收。  
纯裸机 QEMU 没有 DsOS 内核，直接执行 `syscall` 不会输出任何东西。  
所以 Step 1 提供两条路径：

| 路径 | 用途 | 验证方式 |
|---|---|---|
| **x86_64 Linux 用户态 raw syscall** | 验证指令编码、SysV 寄存器、syscall 序列 | `qemu-x86_64 syscall.elf` |
| **16 位裸机串口引导扇区** | 无内核也能在 QEMU 裸机输出，作为 Step 3 前的兜底 | `qemu-system-x86_64 -drive ... -serial stdio` |

DsOS 的最终路径是第一条：Step 3 的加载器分配可执行页、拷贝 `syscall.bin`，再由 DsOS 提供 syscall 入口。  
第二条只验证“裸机确实能输出”，不冒充 x86_64 OS。

## 1. 文件与模块标注

| 文件 | 层 | 说明 | 行数/大小 |
|---|---|---|---|
| `step1.ds` | Ds- | 语义对照源码 | 10 行 |
| `syscall.bin` | Ds- | 扁平 x86_64 机器码，入口 offset 0 | 46 bytes |
| `syscall.elf` | Ds- | 最小静态 ELF64，供 qemu-x86_64 | 166 bytes |
| `bare_serial.bin` | Ds- | 16 位引导扇区，COM1 输出 | 512 bytes |
| `gen_step1.py` | 工具 | 纯 Python 字节生成器，无 C/汇编器 | — |

依赖：无。

## 2. syscall 机器码（46 bytes）

```text
b8 01 00 00 00          mov eax, 1          ; SYS_write
bf 01 00 00 00          mov edi, 1          ; fd = stdout
48 8d 35 10 00 00 00    lea rsi, [rip+16]   ; buf = msg
ba 0d 00 00 00          mov edx, 13         ; count
0f 05                   syscall
b8 3c 00 00 00          mov eax, 60         ; SYS_exit
31 ff                   xor edi, edi        ; code = 0
0f 05                   syscall
44 73 4f 53 20 62 6f 6f 74 65 64 2e 0a      ; "DsOS booted.\n"
```

对应汇编语义：

```asm
_start:
    mov eax, 1
    mov edi, 1
    lea rsi, [rip + msg]
    mov edx, 13
    syscall

    mov eax, 60
    xor edi, edi
    syscall

msg:
    .ascii "DsOS booted.\n"
```

## 3. 对应的 Ds 语义源码

```ds
@unsafe fn _start() {
    sys_write(1, "DsOS booted.\n")
    sys_exit(0)
}
```

`sys_write/sys_exit` 是 DsOS syscall ABI 的语义入口；Step 2 会将受限形式编译为上面的机器码。

## 4. 生成

```bash
cd dsos/toolchain/step1
python3 gen_step1.py
```

产物：

```text
syscall.bin       46 bytes
syscall.elf      166 bytes
bare_serial.bin  512 bytes
syscall.hex       机器码十六进制
```

## 5. 验证命令

### 5.1 x86_64 Linux 用户态（sys_write 路径）

```bash
qemu-x86_64 dsos/toolchain/step1/syscall.elf
# 期望：
# DsOS booted.
```

没有 qemu 时，至少做静态校验：

```bash
readelf -h dsos/toolchain/step1/syscall.elf
llvm-objdump -d --start-address=0x400078 --stop-address=0x400099 \
  dsos/toolchain/step1/syscall.elf
```

### 5.2 QEMU 裸机串口（兜底）

```bash
qemu-system-x86_64 \
  -drive format=raw,file=dsos/toolchain/step1/bare_serial.bin,if=ide \
  -boot c -serial stdio -display none
# 期望串口：
# DsOS booted.
```

## 6. Step 2 的接口契约

Step 2 的 `dscc` 后端至少需要生成：

- `mov eax, imm32`
- `mov edi, imm32`
- `lea rsi, [rip+disp32]`
- `mov edx, imm32`
- `syscall`
- `xor edi, edi`
- `jmp/ret`（后续步骤）

寄存器固定映射（Phase 1 不做分配）：

| 角色 | 寄存器 |
|---|---|
| 第 1 参数 | `rdi` |
| 第 2 参数 | `rsi` |
| 第 3 参数 | `rdx` |
| syscall 号 | `rax` |
| 返回值 | `rax` |

栈：调用前 RSP 16 字节对齐（Step 2 无调用，Step 4 强制）。

## 7. 本步不做

- 不生成 C
- 不调用 gcc/clang/nasm
- 不链 libc
- 不做 ELF 段解析（只做单 PT_LOAD）
- 不做寄存器分配/优化
