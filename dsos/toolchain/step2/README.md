# DsOS Toolchain — Step 2：dscc 最小机器码生成器

> **输入**：受限 Ds 源码（无参数、无局部变量、sys_write/sys_exit）  
> **输出**：x86_64 `.bin` / `.elf`  
> **不经过**：C、汇编器、链接器、libc。

## 1. 文件与标注

| 文件 | 层 | 说明 | 大小 |
|---|---|---|---|
| `x86_64.py` | Ds- | 纯 Python 机器码后端 | — |
| `dscc_x86.py` | 工具 | Step 2 CLI | — |
| `examples/hello.ds` | Ds- | 输入示例 | 5 行 |
| `examples/hello.bin` | Ds- | 机器码，入口 offset 0 | 47 B |
| `examples/hello.elf` | Ds- | 最小 ELF64 | 167 B |
| `test_step2.py` | — | 5 项回归 | — |

依赖：无。

## 2. 输入 Ds 源码

```ds
@unsafe fn _start() {
    sys_write(1, "DsOS booted.\n")
}
```

Step 2 限制：

- 入口函数 `_start`
- 无参数、无局部变量
- 只允许 `sys_write(fd, "字面量")` 和 `sys_exit(code)`
- 单个 `sys_write`

## 3. 编译

```bash
# 从仓库根目录
./dscc dsos/toolchain/step2/examples/hello.ds --emit bin -o hello.bin
./dscc dsos/toolchain/step2/examples/hello.ds --emit elf -o hello.elf
```

或直接调用后端：

```bash
python3 dsos/toolchain/step2/dscc_x86.py \
  dsos/toolchain/step2/examples/hello.ds --emit bin -o hello.bin
```

## 4. 生成结果

`hello.bin`（47 bytes）：

```text
b8 01 00 00 00          mov eax, 1
bf 01 00 00 00          mov edi, 1
48 8d 35 11 00 00 00    lea rsi, [rip+0x11]
ba 0d 00 00 00          mov edx, 13
0f 05                   syscall
b8 3c 00 00 00          mov eax, 60
31 ff                   xor edi, edi
0f 05                   syscall
c3                      ret
44 73 4f 53 20 62 6f 6f 74 65 64 2e 0a  "DsOS booted.\n"
```

完整十六进制：

```text
b8 01 00 00 00 bf 01 00 00 00 48 8d 35 11 00 00 00 ba 0d 00 00 00 0f 05 b8 3c 00 00 00 31 ff 0f 05 c3 44 73 4f 53 20 62 6f 6f 74 65 64 2e 0a
```

`hello.elf`：ELF64、机器 `0x3E`、entry `0x400078`、单个 RX `PT_LOAD`。

## 5. 验证

```bash
qemu-x86_64 dsos/toolchain/step2/examples/hello.elf
# 期望：
# DsOS booted.
```

无 QEMU 时静态验证：

```bash
readelf -h dsos/toolchain/step2/examples/hello.elf
llvm-objdump -d --start-address=0x400078 --stop-address=0x4000a7 \
  dsos/toolchain/step2/examples/hello.elf
python3 -m unittest dsos/toolchain/step2/test_step2.py -v
```

## 6. 指令覆盖

本步生成：

- `mov eax/edi/edx, imm32`
- `lea rsi, [rip+disp32]`
- `syscall`
- `xor edi, edi`
- `ret`
- `jmp rel8/rel32`（编码器已支持，Step 5 分支使用）

后续 Step 4 会加 `push/mov rbp,rsp/sub rsp/pop rbp`，Step 5 加 `add/sub/cmp/je/jne/jl/jg`。

## 7. Step 3 契约

`load_and_run(code: @raw u8, len: u64) -> !`：

1. 分配可执行页；
2. 拷贝 `hello.bin`；
3. 跳转到 offset 0；
4. DsOS 必须提供 syscall 入口（Step 1 的 Linux 号 1/60 可直接采用）。

> 本机为 aarch64 Termux，未安装 `qemu-x86_64`；已用 `readelf/objdump` 校验编码，QEMU 执行命令已给出。
