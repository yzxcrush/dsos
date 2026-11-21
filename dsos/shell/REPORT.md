# DsOS v0.4 — 键盘 + Shell + ACPI 关机

纯 Python 生成机器码，**不经过 C / 汇编器 / 链接器**。产物 `dsos-x86_64-shell.img`（1,474,560 B）。

## 1. 新增能力

| 能力 | 实现 |
|---|---|
| 屏幕 | VGA 文本 `0xB8000`，自己的 `vga_putc`（行/列游标，`\r` 换行） |
| 键盘 | **双路径**：优先 PS/2 IRQ1 真实中断（IDT 256 门 → PIC 重映射）；**若 IRQ1 从未触发，自动退回轮询 `0x64`/`0x60`** |
| 定时 | IRQ0 递增 tick 计数（不打印，避免刷屏） |
| 行编辑 | 回显、退格（`\b \b`）、回车提交、120 字符上限 |
| 命令 | `help` `ticks` `clear` `shutdown` `reboot` |
| **关机** | **ACPI FADT 解析** → S5 → `outw(PM1a_CNT, SLP_TYPa<<10 \| SLP_EN)`；失败则 `System halted.` + `cli;hlt` |
| 重启 | 键盘控制器复位 `out 0x64,0xFE` |
| 串口 | 所有屏幕输出同时写 COM1，保留原有证据链 |

## 2. 内存映射

| 地址 | 用途 |
|---|---|
| `0x001000 / 0x002000 / 0x003000` | PML4 / PDPT / PD（**从 `0x9000/0xA000/0xB000` 挪走**，给内核腾地方） |
| `0x003FF0` | **已废弃**（IDTR 移走；PD 占 `0x3000..0x3FFF`，此处不可用） |
| `0x005000` | 行缓冲（256 B） |
| `0x005080` | 行长度（dword） |
| `0x005100 / 0x005104 / 0x005110` | 键盘环：head / tail / 数据 |
| `0x005200` | tick 计数 |
| `0x005210` | `IRQFLAG`：IRQ1 首次真正触发时置 1 |
| `0x005FF0` | IDTR（10 B） |
| `0x004000` | IDT（256 × 16 = 4096 B） |
| `0x007F00 / 0x007F04` | VGA 游标：行基址 / 列偏移 |
| `0x009000` | 内核（2124 B，预算 4096） |
| `0x070000` | 栈 |

> 早期版本把缓冲区放在 `0x3100+`，与 PD（`0x3000..0x3FFF`）重叠。虽然那些 PD 项（虚拟 64/128/256 MiB）从不使用、
> 实测无害，但已全部迁到 `0x5000+`，消除这个隐患。

## 3. 镜像布局

```text
offset 0     boot_sector(512)         reads 16 sectors (sector 2..17) -> 0x8000
offset 512   stage2 + pad(4096)       A20 / GDT / 页表 / PAE / EFER / CR0.PG -> jmp 0x9000
offset 4608  kernel + pad(4096)       IDT / PIC / 键盘 / shell / ACPI
offset 8704  0x00 ... 到 1.44 MiB
```

## 4. 关机路径（真机能断电的关键）

猜端口（`0x604/0xB004/0x4004`）只在 QEMU/Bochs 有效，真机上端口由固件给出。所以实现了完整解析：

```text
扫描 0xE0000..0xFFFFF 找 "RSD PTR "（8 字节签名 + 20 字节校验和）
  -> RSDP+16 = RSDT（若为 0 则取 RSDP+24 的 XSDT 低 32 位）
  -> 遍历表项找 "FACP" (FADT)
  -> FADT+64  = PM1a_CNT_BLK
  -> FADT+0xB0 的 bit10..12 = SLP_TYPa
  -> io_wait(out 0x80) ; outw(PM1a_CNT, SLP_TYPa<<10 | 0x2000) ; io_wait
```

失败时打印 `System halted. You can power off now.` 并停机 —— **在任何机器上都有安全结果**。

## 5. 验收结果（unicorn，QEMU TCG 核心）

按键是**通过 IDT 里登记的 IRQ1 handler** 注入的（构造 `pushfq/CS/RIP` 栈帧后跳转），不是直接调函数。

| 用例 | 结果 |
|---|---|
| [a] 启动 + 横幅 + 提示符 | **PASS** |
| [b] `help` | **PASS** |
| [c] `ticks` | **PASS** |
| [d] ACPI FADT 解析（伪造 RSDP→RSDT→FADT 链） | **PASS** |
| [e] S5 `outw` 到 `0x604`，值 `0x3400` | **PASS** |
| [f] 旧镜像哈希不变 | **PASS** |
| [g] **轮询兜底**：模拟 IRQ1 完全不投递，仅靠 `0x64`/`0x60` 轮询 | **PASS**（`help` 正常输出） |
| 16 位阶段：int13 读 16 扇区 → `0x8000`，stage2/内核落位逐字节一致 | **PASS** |

屏幕实录：

```text
DsOS v0.4  (keyboard + shell)
dsos> help
commands:
  help      show this
  ticks     timer interrupt count
  clear     clear the screen
  shutdown  ACPI power off
  reboot    reset the machine
dsos> ticks
ticks=0
dsos> shutdown
acpi: FADT found, S5 poweroff...
System halted. You can power off now.
```

## 6. 未验证（如实说明）

- **真机键盘**：IDT/PIC 的真实中断投递未在硬件上验证（模拟器是手工注入的）。
- **真机 ACPI**：解析逻辑用伪造表验证过，真机 FADT 分布未验证；即使解析对，固件也可能拒绝 S5。
- **真机 IRQ0 计时**：`ticks=0` 是模拟器里没有定时器中断导致的，真机应递增。
- **Multiboot 路径**仍未验证。

## 7. 过程中修掉的 4 个真实缺陷（都是手写机器码的典型坑）

| 缺陷 | 现象 | 根因 |
|---|---|---|
| 相对跳转全为 0 | 一启动就跳飞 | `Asm.fix` 的收尾循环只存在于 stage2 内，内核没跑 |
| `_start` 掉进子程序 | 执行完清屏就 `ret` | 子程序内联排布，缺一条跳过它们的 `jmp` |
| `cmp rcx,120` 变成 `jl` | 执行路径乱跳 | 误用寄存器版 `alu()`，立即数被当寄存器号算出 `REX=0x7C` |
| `xor r9d, ecx` | 数字打印成一长串 0 | `xor_self` 没置 REX.R，高寄存器塌成低寄存器 |

前三个会让机器直接黑屏/重启，第四个会让 `ticks` 刷屏——都在烧盘前被模拟器拦住了。


## 8. 键盘双路径（为什么这样设计）

真机上有个不确定因素：**BIOS 是否把 USB 键盘转成 PS/2 legacy 并投递 IRQ1**。如果不投递，
纯中断方案会表现为「屏幕正常、敲键毫无反应」——这不是崩溃，但等于整盘作废。

所以内核同时装了中断与轮询：

```text
IRQ1 handler 触发时：置 IRQFLAG=1 → 之后只走中断，绝不重复读端口
main_loop 空闲时：若 IRQFLAG==0 → 读 0x64 状态位0 → 有数据则读 0x60 并解析
```

两条路径共用同一个 `enqueue_scan`（扫描码 → ASCII → 环形缓冲），不会重复入队。
效果：**中断能用的机器走中断；不能用的机器自动降级，键盘照样能用。**
