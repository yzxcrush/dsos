# DsOS — Ds 语言原生操作系统

> 用 **Ds / Ds/Cut** 从复位向量往上写，不经过 C、汇编器、链接器、libc。
> 本仓库是 [`yzxcrush/ds`](https://github.com/yzxcrush/ds) 中 `dsos/` 子树的下游镜像，外加**运行时验证工具链**与 **v0.5 桌面控制台**。

---

## 当前发行版

| 项 | 值 |
|---|---|
| 镜像 | `dsos/images/x86_64/dsos-x86_64-shell.img` |
| SHA256 | `781dd3c39c9bdb69a6b75d1b60bc40922c544c4b2fd23a26c4849af35c2d2465` |
| 大小 | 1,474,560 B（1.44 MiB） |
| 启动方式 | legacy BIOS / CSM，写入 USB 后从 MBR 引导 |
| 验收 | **11 项全 PASS**（`dsos/shell/verify_shell.py`） |

开机画面：

```text
┌────────────────────────────────────────────────────────┐
│ DsOS v0.5  -  keyboard + shell + ACPI                  │  ← 蓝底白字
├────────────────────────────────────────────────────────┤
│ DsOS v0.5  desktop console                             │
│ [boot] idt: 256 gates, irq0/irq1 installed             │
│ [boot] pic: remapped to 0x20/0x28, irq0+irq1 unmasked  │
│ [boot] keyboard: irq1 enabled (poll fallback armed)    │
│ [boot] acpi: parser ready, run 'shutdown' to power off │
│ dsos> █                                                │
│                                                        │
├────────────────────────────────────────────────────────┤
│ help   ticks   clear   shutdown   reboot               │  ← 灰底黑字
└────────────────────────────────────────────────────────┘
```

### 能力

| 能力 | 状态 |
|---|---|
| BIOS → MBR → 32 位 → 长模式启动 | ✅ 真机已验证 |
| 真实 `int 13h` 读盘（16 扇区） | ✅ 真机已验证 |
| VGA 文本输出 + **滚动** | ✅ 指令级验证（真机待验） |
| 标题栏 / 状态栏（颜色） | ✅ 指令级验证 |
| PS/2 键盘：IRQ1 中断 + **轮询兜底** | ✅ 指令级验证 |
| `dsos>` shell：`help` `ticks` `clear` `log` `shutdown` `reboot` | ✅ 指令级验证 |
| ACPI `RSDP → RSDT/XSDT → FADT` 解析 → S5 关机 | ✅ 指令级验证 |
| 启动日志（`[boot] …` + stage2 的 `S2 OK` 标记） | ✅ 指令级验证 |

### 明确未实现

- 文件系统、内存分配器、进程/调度、用户态、系统调用、网络、图形
- UEFI 启动（只有 legacy MBR）
- Multiboot 路径（`phase1/kernel.bin` 从未被加载执行）
- **内核直写 U 盘**：U 盘只能经 BIOS `int 13h` 访问，长模式下需自建 xHCI + USB 存储类 + FAT32 写入，属独立工程

---

## 源码比镜像新（请先读这条）

`dsos/shell/` 里的源码**领先于发行镜像**，包含一个**未完成**的事件日志子系统：

| 项 | 状态 |
|---|---|
| 事件环（32 × 8 字节，记录 event id + tick） | ✅ 记录正确 |
| `log` 命令回放 | ⚠️ **显示有缺陷**，验收用例 `[j]` **FAIL** |
| `shutdown` 前自动 dump 日志 | ⚠️ 同上 |

**因此这份源码重新构建会得到 `ed59378e…`，它不是发行版。**
发行镜像 `781dd3c3…` 是最后一个全部用例通过的构建，已写入 USB 并在真机上出过画面。

按 [`AGENTS.md`](AGENTS.md) 第 2 条，未通过验收的构建不烧盘 —— 所以仓库里"源码"与"镜像"暂时不一一对应，这是刻意的、有记录的差异。

---

## 目录

```text
dsos/
  images/x86_64/    boot_sector + stage2 + kernel 的生成器与产物
  phase1/           Multiboot 内核（未验证）
  toolchain/        step1..step5：手写机器码 → dscc 直出 x86_64
  shell/            v0.5 内核源码、验收器、发布流水线、详细报告
  arch/ boot/ bsp/  AArch64 / Thumb、RP2350、Zero 2 W
verify/             交接包校验、可复现性、ELF/Multiboot 静态检查、指令级执行
docs/               P0 验证报告
AGENTS.md           本仓库的操作规约（硬约束）
```

## 快速开始

```bash
# 一条命令：构建 → 全套验收 → （可选）带守卫烧盘 + 回读校验
cd dsos/shell
python3 release.py            # 只构建 + 验收
python3 release.py --flash    # 通过后才写 USB

# 单独跑验收（unicorn = QEMU TCG 核心）
python3 verify_shell.py
```

写入 U 盘（Linux/macOS）：

```bash
sudo dd if=dsos/images/x86_64/dsos-x86_64-shell.img of=/dev/sdX bs=4M conv=fsync status=progress && sync
```

Windows：先移除卷盘符，再对 `\\.\PhysicalDriveN` 前 1,474,560 字节做原始写入。**写错盘会毁数据**，务必先确认盘号、`BusType=USB`、`IsSystem=False`。

## 验证状态的三档口径

| 档 | 含义 |
|---|---|
| **真机已验证** | 在真实硬件上看到预期画面/行为，有照片或串口日志 |
| **指令级验证** | 在 unicorn（QEMU 的 TCG 核心）里逐指令执行并通过断言；**不等于**真机通过 |
| **未验证** | 只有源码，没跑过 |

[`docs/P0-VERIFICATION.md`](docs/P0-VERIFICATION.md) 记录了完整证据链，包括一次"真机首启断电"的根因复盘（stage2 → 内核的跳转位移少算了 `0x8000`）。

## 与上游的关系

- 上游：<https://github.com/yzxcrush/ds>（提交 `7c8b086`）
- Base 语言冻结为 `ds-base-v1`；DsOS 不冻结
- 本仓库由接任的 AI 工程代理维护，遵守 [`AGENTS.md`](AGENTS.md)
