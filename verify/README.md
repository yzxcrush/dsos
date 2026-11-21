# verify/ — DsOS 指令级验证工具链

这些脚本用于在**没有 QEMU 的机器上**给出尽可能强的运行时证据。它们只读 `dsos/`，不修改产物。

## 依赖

```bash
pip install unicorn      # 2.1.4+；unicorn 就是 QEMU 的 TCG CPU 核心
```

`01` 需要一份交接包目录结构（含 `SHA256SUMS` / `MANIFEST.json`）；`02`–`05` 只需要本仓库。

## 脚本

| 脚本 | 作用 | 期望结果 |
|---|---|---|
| `01_verify_package.py` | 校验交接包 34 项 SHA256 与 MANIFEST 尺寸 | `ok=34 bad=0 missing=0` |
| `02_check_reproducible.py` | 删掉产物 → 重跑生成器 → 逐字节比对 | 6 个产物全部 `IDENTICAL` |
| `03_inspect_artifacts.py` | ELF 头 / Multiboot magic / 引导扇区 `0x55AA` | `kernel.bin` ELF32 + magic@0x1000 checksum ok |
| `04_run_16bit_and_syscall.py` | unicorn 跑 `syscall.bin`、`bare_serial.bin`、`dsos-bios.img` | `DsOS booted.` ×3 |
| `05_run_long_mode.py` | unicorn 以 64 位模式从 stage2 的 `jmp far 0x18:` 目标起跑 | `DsOS alive` + `tick: 1..5` |

## 它们证明了什么 / 没证明什么

**证明**：机器码编码正确、寄存器/ABI 映射正确、串口初始化与轮询正确、`print_u32` 十进制转换正确、
心跳循环的 TSC 差值比较正确、引导链的 16 位部分能执行到 `CR0=0x80000011`。

**没证明**：真实 BIOS 加载、真实 `int 13h`、**真实的 16→32→64 位模式切换**、分页生效后的地址翻译、
真实 TSC 节拍、真实 UART 时序、Multiboot 路径。

`05` 的两处刻意妥协，必须在引用结果时一起说明：

1. 直接以 **64 位模式**起跑（unicorn 无法在运行中切换译码模式），绕过 mode switch；
2. **合成 TSC**（每次 `rdtsc` +5e8），否则 1e9 周期的忙等要跑几十亿条指令；
   心跳次数因此不可当真，只验证"循环会递增并打印"。

> 结论口径：**"指令级已验证" ≠ "已启动"**。把前者说成后者违反本仓库红线第 1 条。

## 已知跨平台差异

在 Windows 上跑 `02_check_reproducible.py`，`syscall.hex` 会显示 `DIFFERS`：
生成器用文本模式写出的是 CRLF，而仓库里是 LF。**内容完全一致，仅换行符不同**。
其余 6 个产物在所有平台都应逐字节相同。
