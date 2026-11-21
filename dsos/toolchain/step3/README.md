# DsOS Toolchain — Step 3：最小加载器 / 最小可运行 DsOS

> **目标**：加载 Step 2 生成的机器码，分配可执行内存、拷贝、跳入口，由 DsOS 提供 syscall。  
> **当前形态**：宿主加载器（VM + x86_64 native），不是完整裸机内核；它是 DsOS/0 的最小运行环境。

## 1. 两个加载器

| 文件 | 平台 | 行为 |
|---|---|---|
| `loader_native.py` | x86_64 Linux | `mmap RWX` → 拷贝 → 跳入口，真实 CPU 执行 |
| `dsos_loader.py` | 任意主机 | 最小 x86_64 子集 VM，解释 Step 2 指令并分发 syscall |
| `dsos/bin/dsos` | 任意主机 | 统一入口：`.ds` 自动编译，`.bin` 直接加载 |

`dsos_loader.py` 是本机（aarch64 Termux）可运行的版本；`loader_native.py` 是 DsOS 在 x86_64 上的真实路径。

## 2. 接口契约

`loader.ds`：

```ds
@unsafe fn load_and_run(code: *u8, len: u64) -> ! {
    # 分配可执行页 -> 拷贝 code -> 跳到入口 offset 0
    # syscall 入口由 DsOS 提供
    loop { }
}
```

真实实现由 Cut/内核完成；Step 3 的 Python 加载器验证同一语义。

## 3. 运行

```bash
# 从 Ds 源码直接跑（自动 dscc --emit bin）
./dsos/bin/dsos dsos/toolchain/step2/examples/hello.ds

# 直接跑已经生成的 bin
./dsos/bin/dsos dsos/toolchain/step2/examples/hello.bin

# x86_64 上真实 mmap+跳转
./dsos/bin/dsos --native dsos/toolchain/step2/examples/hello.bin
```

期望输出：

```text
DsOS booted.
```

本机实测：

```text
$ ./dsos/bin/dsos dsos/toolchain/step2/examples/hello.ds
DsOS booted.
```

## 4. syscall 分发

| rax | 语义 | 参数 |
|---|---|---|
| 1 | `sys_write` | `rdi=fd, rsi=buf, rdx=len` |
| 60 | `sys_exit` | `rdi=code` |

`rsi` 是绝对地址；Step 2 用 RIP-relative `lea` 指向代码后的消息字节。

## 5. 文件与模块标注

| 文件 | 层 | 说明 |
|---|---|---|
| `loader.ds` | Ds- | 加载器契约 |
| `dsos_loader.py` | Ds- | 可移植 VM 加载器 |
| `loader_native.py` | Ds- | x86_64 mmap 加载器 |
| `dsos/bin/dsos` | 工具 | 最小 DsOS CLI |
| `test_step3.py` | — | 4 项回归 |

依赖：Step 2 `dscc --emit bin`。

## 6. 验证

```bash
python3 -m unittest dsos/toolchain/step3/test_step3.py -v
./dsos/bin/dsos dsos/toolchain/step2/examples/hello.ds
```

## 7. 边界

- 这不是完整裸机 DsOS：没有 bootloader、GDT/IDT、页表、中断。
- `loader_native.py` 依赖 Linux syscall；DsOS 的 syscall 入口在后续裸机阶段实现。
- VM 只覆盖 Step 2 指令；Step 4/5 会扩展栈帧、函数调用、算术和条件跳转。

## 8. 下一步 Step 4

- 函数 prologue/epilogue：`push rbp; mov rbp,rsp; sub rsp,N; leave; ret`
- 局部变量 `[rbp-8]`、`[rbp-16]`
- 两函数互调，验证结果
