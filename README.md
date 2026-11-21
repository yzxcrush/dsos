# DsOS — Ds 语言原生操作系统（最小可启动版本）

> 用 **Ds / Ds/Cut** 从复位向量往上写，不经过 C、汇编器、链接器、libc。
> 本仓库是 [`yzxcrush/ds`](https://github.com/yzxcrush/ds) 中 `dsos/` 子树的下游镜像，外加 **P0 运行时验证工具链**。

## 状态（请先读这一段，不要跳）

| 能力 | 状态 | 证据 |
|---|---|---|
| 产物可复现（字节级） | ✅ **已验证** | `verify/02_check_reproducible.py`：四个生成器重跑后 `syscall.bin` / `syscall.elf` / `bare_serial.bin` / `dsos-x86_64.img` / `dsos-bios.img` / `kernel.bin` 全部 **IDENTICAL** |
| 46B x86_64 syscall 代码 | ✅ **已执行验证** | `write(1,"DsOS booted.\n",13)` + `exit(0)`，退出码 0 |
| 16 位 COM1 串口输出 | ✅ **已执行验证** | 14 次 `out 0x3F8`，抓到 `DsOS booted.` |
| A20 / GDT / 页表 / PAE / EFER / CR0.PG 指令序列 | ✅ **已执行验证** | 执行到 `CR0 = 0x80000011`（PE+PG） |
| 长模式内核 | ✅ **已执行验证** | 串口输出 `DsOS alive` + `tick: 1..5` 单调递增 |
| **真实 BIOS → MBR → 长模式完整引导** | ❌ **未验证** | 见下方「未验证」 |
| Multiboot（`phase1/kernel.bin`） | ❌ **未验证** | 从未被 `-kernel` 加载过 |
| Shell / 模块加载 / 文件系统 / 进程 / 网络 / GUI | ❌ **未实现** | 空接口 |

**一句话**：代码层面已经"跑起来了"（在 QEMU 的 TCG CPU 核心上逐指令执行并产出正确串口输出），
但**还没有在真实 BIOS/固件或完整 QEMU 系统模拟下完成一次从引导扇区到长模式的启动**。
这两件事不能混为一谈——详见 [`docs/P0-VERIFICATION.md`](docs/P0-VERIFICATION.md)。

## 目录结构

```text
dsos/
  images/x86_64/     1.44MiB 裸机镜像 + 512B 兜底扇区 + 纯 Python 生成器
  phase1/            Multiboot 内核（boot/GDT/UART/kernel + 模块接口预埋）
  toolchain/step1..5 手写机器码 → dscc 直出 x86_64（纯 Python，无外部工具链）
  arch/ boot/ bsp/   AArch64 / Thumb 上下文切换、RP2350 / Zero 2 W 启动
verify/
  01_verify_package.py        交接包 SHA256 / MANIFEST 校验
  02_check_reproducible.py    删产物→重跑生成器→逐字节比对
  03_inspect_artifacts.py     ELF / Multiboot header / 引导扇区签名静态检查
  04_run_16bit_and_syscall.py unicorn 执行 16 位扇区与 syscall.bin
  05_run_long_mode.py         unicorn 以 64 位模式执行长模式内核
docs/P0-VERIFICATION.md       完整的验证报告（含边界与自我批评）
```

## 快速开始

需要 **x86_64 Linux**（本机若是 Windows/macOS，用 WSL2、虚拟机或云主机）。

```bash
# 1) 重新生成（纯 Python，无 C/汇编器/链接器）
python3 dsos/images/x86_64/gen_boot.py
python3 dsos/toolchain/step1/gen_step1.py
cd dsos/phase1 && python3 build.py && cd -

# 2) 真机/模拟器启动（这一步本仓库尚未完成验证）
qemu-system-x86_64 \
  -drive format=raw,file=dsos/images/x86_64/dsos-x86_64.img,if=floppy \
  -serial stdio -display none
# 期望： DsOS alive / tick: 1 / tick: 2 ...

# 3) 无需 QEMU 的指令级验证（Linux/macOS/Windows 均可）
pip install unicorn
python3 verify/04_run_16bit_and_syscall.py
python3 verify/05_run_long_mode.py
```

烧录到 U 盘（**危险，先确认设备名**）：

```bash
sudo dd if=dsos/images/x86_64/dsos-x86_64.img of=/dev/sdX bs=4M conv=fsync status=progress && sync
```

## 未验证 / 未实现（明确清单）

- ❌ 真实 BIOS 把 MBR 载入 `0x7C00`；真实 `int 13h` 磁盘服务
- ❌ **16 → 32 → 64 位模式切换的真机语义**（当前证据是"直接以 64 位起跑"，绕过切换）
- ❌ 分页生效后的真实地址翻译副作用
- ❌ 真实 TSC 驱动的 ~1 秒心跳节拍（验证时合成了 TSC 以避免 1e9 周期忙等）
- ❌ 真实 UART 时序/流控
- ❌ Multiboot 加载路径
- ❌ IDT/PIT、页分配器、调度器、syscall、VFS、驱动、网络、用户态、GUI
- ⚠️ `dsos-bios.img` 与 `toolchain/step1/bare_serial.bin` **字节相同**，只输出 `DsOS booted.`；
  旧文档曾声称它输出 `DsOS alive` 并递增 tick——那是错的，已在此更正

## 红线（贡献者与后续 AI 必须遵守）

1. **不把"能编译"说成"已运行"**；不把"指令级验证"说成"真机启动成功"。
2. 不把 Android 虚拟硬件说成真实裸机验证。
3. Phase1 构建路径不引入 C 源码、不引入 nasm/gcc。
4. 任何"冻结/已验证"标签必须附可复现命令 + 日志。
5. 不要提交 token、私钥、未脱敏日志。

## 来源

- 上游：<https://github.com/yzxcrush/ds>（提交 `7c8b086`，`dsos/` 子树）
- Base 语言已冻结为 `ds-base-v1`；DsOS 不冻结，仍在演进
- 验证工具与报告由接任的 AI 工程代理补充（见 `docs/P0-VERIFICATION.md`）
