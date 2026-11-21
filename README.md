# DsOS — Ds 语言原生操作系统

> **一句话**：用 Ds 语言家族的三个层，从复位向量一路写到用户态；不经过 C、汇编器、链接器、libc。
> 本仓库是 [`yzxcrush/ds`](https://github.com/yzxcrush/ds) 中 `dsos/` 子树的下游镜像，外加**运行时验证工具链**与 **v0.5 桌面控制台**。

---

## DsOS 是什么

**它不是一个"用 Ds 写点裸机代码"的演示，而是 Ds 语言家族的最终自证**：同一套语言、同一套语义，从
`jmp 0x7c00` 的位置开始，一路构建出可引导镜像、中断系统、交互终端，中间不引入第二门语言。

传统 OS 是「C + 汇编启动 + C 内核 + C 驱动 + libc + 用户程序」；
DsOS 的目标结构是：

```text
Ds/Cut   （16 token 裸机子语言）   启动、异常向量、最底层驱动
   ⊂
Ds Base  （77 关键字，已冻结）     内核主体：内存、调度、模块、shell
   ⊂
Ds+      （77 + 16 个 @ 令牌）     硬件能力：端口 IO / MSR / MMIO / 内存区域
```

**为什么值得做**：换成 C 写，这套东西只是又一个 hobby OS；用 Ds 写，它同时是
「语言可用性的压力测试」——语言在哪里不够用，内核会立刻暴露出来。

## 它现在真正能做什么

```text
┌────────────────────────────────────────────────────────┐
│ DsOS v0.5  -  keyboard + shell + ACPI                  │  ← 蓝底白字标题栏
├────────────────────────────────────────────────────────┤
│ DsOS v0.5  desktop console                             │
│ [boot] idt: 256 gates, irq0/irq1 installed             │
│ [boot] pic: remapped to 0x20/0x28, irq0+irq1 unmasked  │
│ [boot] keyboard: irq1 enabled (poll fallback armed)    │
│ [boot] acpi: parser ready, run 'shutdown' to power off │
│ dsos> help                                             │
│   help  ticks  clear  log  shutdown  reboot            │
│ dsos> █                                                │
├────────────────────────────────────────────────────────┤
│ help   ticks   clear   shutdown   reboot               │  ← 灰底黑字状态栏
└────────────────────────────────────────────────────────┘
```

| 能力 | 说明 |
|---|---|
| 启动 | legacy BIOS → MBR → 实模式 → 保护模式 → **PAE 长模式**，全程字节由 Python 生成 |
| 中断 | IDT 256 门、PIC 重映射到 `0x20/0x28`、IRQ0 计时、IRQ1 键盘 |
| 键盘 | PS/2 扫描码 → ASCII → 环形缓冲；**IRQ1 不投递时自动降级轮询** |
| 显示 | VGA 文本 80×25，双缓冲游标，**滚动**，标题栏/状态栏 |
| 终端 | `dsos>` 提示符、回显、退格、120 字符行缓冲 |
| 命令 | `help` `ticks` `clear` `log` `shutdown` `reboot` |
| 关机 | 解析 ACPI `RSDP → RSDT/XSDT → FADT`，取 `PM1a_CNT_BLK` 与 `SLP_TYPa`，发 **S5** 真断电；失败则安全停机 |
| 串口 | 所有屏幕输出同步写 COM1（115200 8N1） |

**关键工程约束**：内核是**手写机器码**，由 `dsos/shell/kernel.py`（指令发射器）+ `kernel_body.py`（内核逻辑）
逐字节生成，当前 2,096 字节，预算 4,096 字节。

## 它现在还不能做什么

诚实地列出来，避免被当成"能用的操作系统"：

| 缺什么 | 后果 |
|---|---|
| 文件系统 | 不能读写文件；只有启动时的那一次读盘 |
| 内存分配器 | 固定地址布局，不能动态申请 |
| 进程 / 调度 | 只有一个主循环 + 中断 |
| 用户态 / 系统调用 | 全部跑在内核态 |
| 时间 | 没读 RTC，没有日期时间 |
| 网络 / 图形 | 纯文本模式 |
| UEFI | 只有 legacy MBR，UEFI-only 机器起不来 |
| 内核直写 U 盘 | 需要自建 xHCI + USB 存储类 + FAT32，属独立工程 |
| Multiboot 路径 | `phase1/kernel.bin` 从未被加载执行 |

## 路线图

| 段 | 内容 | 状态 |
|---|---|---|
| P0 | 可引导镜像 + 心跳 | ✅ 真机已验证 |
| P0.5 | 长模式内核 + 键盘 + shell + ACPI 关机 | ✅ 真机已验证（v0.4） |
| P1 | 桌面控制台（滚动 + 标题栏/状态栏） | ✅ 指令级验证，真机待验（v0.5） |
| P1.5 | 事件日志（记录 + `log` 回放） | ⚠️ 进行中，回放有缺陷 |
| **P2** | **从 U 盘读 Ds 脚本** | 🚧 B1 已完成：stage2 从 LBA 630 读 32 扇区到 `0x20000` |
| P2.5 | 内核执行 Ds 脚本（字节码 VM） | ⏳ 未开始 |
| P3 | 文件系统 + 存储驱动 → 任意脚本 | ⏳ 独立工程 |

> **长期目标：让 DsOS 完全由 Ds 家族语言编写。** 完整路线（自举三段式、五个架构契约、阶段 A–G 与验收标准）
> 见 [`ROADMAP.md`](ROADMAP.md)。

---

## 当前发行版

| 项 | 值 |
|---|---|
| 镜像 | `dsos/images/x86_64/dsos-x86_64-shell.img` |
| SHA256 | `781dd3c39c9bdb69a6b75d1b60bc40922c544c4b2fd23a26c4849af35c2d2465` |
| 大小 | 1,474,560 B（1.44 MiB） |
| 启动方式 | legacy BIOS / CSM，写入 USB 后从 MBR 引导 |
| 验收 | **11 项全 PASS**（`dsos/shell/verify_shell.py`） |

### 源码比镜像新（请先读这条）

`dsos/shell/` 源码**领先于发行镜像**，包含两个未完成的子系统：

| 项 | 状态 |
|---|---|
| 事件日志：事件环记录 | ✅ 记录正确（`boot/idt/pic/keyboard/cmd *` 逐条对） |
| 事件日志：`log` 回放 | ⚠️ **缺陷**：回放只输出一行并重复，验收 `[j]` **FAIL** |
| 从 U 盘读脚本槽（B1） | ✅ 已验证：`verify_slot.py` 显示 `int13 lba=630 n=32 -> 0x20000`，magic `DSSC` |

**因此这份源码重新构建得到的镜像不是发行版。**
发行镜像 `781dd3c3…` 是最后一个全绿构建，已写入 USB 并在真机上出过画面。

按 [`AGENTS.md`](AGENTS.md) 第 2 条，未通过验收的构建不烧盘 —— 仓库里"源码"与"镜像"暂时不一一对应，
这是刻意的、有记录的差异。

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

# B1：把 .ds 脚本写进 U 盘的脚本槽
python3 put_script.py hello.ds --device 1
python3 put_script.py --show --device 1

# 单独跑验收（unicorn = QEMU TCG 核心）
python3 verify_shell.py
python3 verify_slot.py
```

写入 U 盘（Linux/macOS）：

```bash
sudo dd if=dsos/images/x86_64/dsos-x86_64-shell.img of=/dev/sdX bs=4M conv=fsync status=progress && sync
```

Windows：先移除卷盘符，再对 `\\.\PhysicalDriveN` 前 1,474,560 字节做原始写入。
**写错盘会毁数据**，务必先确认盘号、`BusType=USB`、`IsSystem=False`。

## 磁盘布局（脚本槽）

```text
LBA 0            MBR（stage1：读 16 扇区到 0x8000）
LBA 1..16        stage2（A20 / GDT / 页表 / 长模式 / 跳内核）
LBA 9..           kernel（加载到 0x9000）
LBA 630..661      DSSCRIPT 槽：32 扇区 = 16 KiB → 加载到 0x20000
                 格式：b"DSSC" + u32 长度 + UTF-8 源码
```

选 LBA 630 是因为 `630 = cyl0 / head10 / sector1`，32 扇区正好落在一条磁道内，不会踩 BIOS 的 CHS 边界。

## 验证状态的三档口径

| 档 | 含义 |
|---|---|
| **真机已验证** | 在真实硬件上看到预期画面/行为，有照片或串口日志 |
| **指令级验证** | 在 unicorn（QEMU 的 TCG 核心）里逐指令执行并通过断言；**不等于**真机通过 |
| **未验证** | 只有源码，没跑过 |

[`docs/P0-VERIFICATION.md`](docs/P0-VERIFICATION.md) 记录了完整证据链，包括一次"真机首启断电"的根因复盘
（stage2 → 内核的跳转位移少算了 `0x8000`，跳到空白页 → 三重故障 → 固件断电）。

## 与上游的关系

- 上游：<https://github.com/yzxcrush/ds>（提交 `7c8b086`）
- Base 语言冻结为 `ds-base-v1`；DsOS 不冻结
- 本仓库由接任的 AI 工程代理维护，遵守 [`AGENTS.md`](AGENTS.md)
