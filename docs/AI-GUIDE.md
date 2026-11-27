# DsOS 学习指南（面向 AI / 新接手者）

> 本文是给**没有任何上下文**的 AI 或工程师看的。读完它，你应该能：看懂代码结构、
> 复现构建、跑通验证、避开已知陷阱、知道哪些事不能做。

---

## 1. 一句话定位

**DsOS 是一个用 Ds 语言编写内核、从 USB 裸机引导运行的操作系统。**

不是虚拟机镜像，不是模拟器玩具，不是 Linux 发行版。插 U 盘 → BIOS 启动菜单 → 选它 → 屏幕出现自己的界面。

关键约束：**产品源码必须是 `.ds`，不得用 C / Rust / 汇编 / Python 生成入镜字节。**
（`AGENTS.md` 规则 9。当前唯一豁免是"编译器本体"，因为它必须自举后才能退役。）

---

## 2. 目录结构

```text
dsos-os/
├── ds/                        内核与引导链的 Ds 源码 + 镜像工具
│   ├── kernel.ds              内核唯一源码（约 540 行 Ds）
│   ├── mbr.ds                 MBR（Ds 写的 16 位引导扇区，实验性）
│   ├── stage2.ds              第二级引导（Ds 写的 16 位，实验性）
│   ├── thunk16.ds             16 位写盘 thunk（日志落盘用，已验证）
│   ├── bootchain.bin          冻结的 Python 版引导链存档（4608 B，真机可启动）
│   ├── build_dsos.py          构建镜像（编译内核 → 拼镜像 → 分区表）
│   ├── flash_dsos.py          写 U 盘（守卫 → 清零 → 写入 → 回读比对）
│   ├── logtool.py             日志分区读写工具（info/read/list/clear/selftest）
│   ├── verify_dsos.py         内核行为验收（unicorn，25 项断言）
│   ├── verify_qemu_boot.py    QEMU 全链路验收（读 VGA 缓冲区还原整屏）
│   └── dsos-ds.img            当前镜像产物
└── compiler/                  Ds → 机器码 编译器
    ├── mini.py                64 位后端（742 行 Python，bootstrap）
    ├── mini16.py              16 位后端（389 行 Python，bootstrap）
    ├── mcc10.ds               用 Ds 写的编译器（自举进行中）
    ├── verify_mini.py         mini.py 验收（17 项）
    ├── verify_selfhost.py     自举固定点验证（T2 == T3）
    └── HANDOFF-next.md        最新进展与未完成项（**接手先读这个**）
```

---

## 3. 运行原理

### 3.1 启动链

```text
BIOS
 └→ MBR (LBA0, 16 位实模式)
      · 设置段寄存器/栈
      · int 13h AH=02 读 32 扇区 (LBA 1..32) → 0x8000
      · 远跳到 0x8000
 └→ stage2 (0x8000, 16 位)
      · A20（端口 0x92 fast gate）
      · 写三层页表 0x1000/0x2000/0x3000（2 MiB 恒等映射）
      · 写 GDT（null / 16位代码 / 64位代码 / 数据）
      · CR3 → CR4.PAE → EFER.LME → CR0.PG|PE
      · 远跳 0x08 或 0x10:0x9000  ← 进入长模式
 └→ 内核 (0x9000, 64 位)
```

**镜像分区布局：**

| 分区 | 类型 | 起始 LBA | 大小 | 用途 |
|---|---|---|---|---|
| 1 | `0x0C` | 2048 | 2 MiB | 引导（含 VBR 副本，兼容"从活动分区启动"的 BIOS） |
| 2 | `0xDA` | 6144 | 8 MiB | 日志分区：256 槽 × 32 KiB |

### 3.2 内核内存布局（内核视角）

```text
0x0500          BIOS DAP（扩展读写参数块）
0x1000-0x3FFF   页表（stage2 写，内核不得改写）
0x4000-0x4EFF   内存日志环：60 槽 × 64 字节
0x4F00          u32 日志条数
0x4F08          u32 IRQ0 节拍计数
0x4F20          IDTR 描述符（10 字节）
0x5000-0x51FF   IDT（48 个门）
0x5EF0          GDTR 描述符
0x5F00          GDT
0x8000          stage2（377 字节）
0x9000-0xBFFF   内核槽（上限 12,288 字节）
0xB8000         VGA 文本缓冲区（80×25，每字符 2 字节）
```

### 3.3 内核结构（kernel.ds 的函数表）

```text
vga_put2(row,col,cp)   直接写 VGA（cp = 字符 | 颜色<<8）
vga_put(row,col,ch)    写字符（默认属性）
clear_row / clear      清屏
puts_at(row,col,s)     写字符串（s 是编译期字面量地址）
hexc(v)                半字节 → ASCII
logstore(s)            写进内存日志环
dump_log / scroll_log  翻页显示日志
log(row,s)             写屏幕 + 环，返回下一行
delay(k)               out8(0x80,0) 空转
heartbeat(n)           心跳计数显示
divider / status_bar   分隔线 / 底部状态栏
sc2ascii(sc)           键盘扫描码 → ASCII
idt_set / setup_idt    装 IDT（0..31 异常 + 32 IRQ0）
exc_common / exc_0..14 异常处理（命名 panic）
timer_irq              IRQ0 处理器：tick++ → EOI → iretq
pic_remap / pit_init   PIC 重映射 / PIT 50 Hz
is_rsdp/is_facp/find_* ACPI 表扫描
shutdown               ACPI S5 关机
fnaddr(fn)             内建：取函数地址（IDT 需要）
```

### 3.4 命令行

命令**靠哈希识别**，不用字符串比较：`h = h*33 + c`，取 `& 0xFFFF`。

```text
help=50025  shutdown=47452  off=58811  log=55842  irq=52684  exc=48512  savelog=14225
```

---

## 4. Ds 语言子集与编译器约束（**最容易踩坑的地方**）

`mini.py` / `mini16.py` 实现的是 Ds 的一个**严格子集**。写内核时必须遵守：

| 约束 | 说明 |
|---|---|
| **最多 3 个参数** | rdi / rsi / rdx。第 4 个参数会被忽略 |
| **没有 `/` 和 `%`** | 用 `>>` 和 `&` 替代 |
| **没有数组/全局变量** | 用固定内存地址 + `load8/load32/store8/store32` |
| **局部变量槽是 4 字节** | 但栈帧按 8 字节对齐；4 字节槽必须用 32 位存储指令 |
| **没有浮点** | 完全没有 |
| **`if` 是表达式不是语句** | 被包在 `ExprStmt` 里，后端要专门处理 |
| **字符串字面量是 `.rodata` 地址** | 可以作为函数参数传递 |
| **函数地址要用 `fnaddr(fn)`** | 只有 bare 目标（加载基址 0x9000）支持 |

**16 位后端（mini16）额外约束：**

| 约束 | 说明 |
|---|---|
| 大部分内建只接受**整数字面量**参数 | 因为省寄存器操作 |
| `[disp16]` 的 modrm 是 **0x06**，不是 0x05 | 0x05 是 `[DI]`，写错会写到 DS:DI |
| 32 位立即数必须带 **`66`** 前缀 | `mov ecx, imm32` 漏了 `66` 会变成 `mov cx, imm16` + 垃圾指令 |
| 保护模式下标记得用 **`67`** 地址前缀 | 16 位偏移装不下 `0xB8000` |
| `mov [disp16], imm` 默认用 **DS** 段 | 不是 ES！ |

---

## 5. 构建与验证流水线

```bash
cd dsos-os/ds

# 1) 构建（默认使用真机确认可启动的 Python 引导链）
python3 build_dsos.py

# 2) 内核行为验收（unicorn，25 项）
python3 verify_dsos.py

# 3) QEMU 全链路验收（启动 + 读 VGA 缓冲区还原整屏）
python3 verify_qemu_boot.py

# 4) 写 U 盘（守卫 → 清零 → 写入 → 回读比对）
python3 flash_dsos.py
```

### 验证三档口径（**绝不允许混淆**）

| 档 | 含义 | 工具 |
|---|---|---|
| **真机已验证** | 用户插 U 盘开机亲眼确认 | 用户的机器 |
| **指令级验证** | 每条指令在模拟器里跑通 | unicorn / QEMU |
| **未验证** | 明确标注，不冒充 | — |

### 模拟器的能力边界（关键知识）

**unicorn 做不到的事**：

```text
· CPU 模式切换（UC_MODE_* 创建时固定）
· IDT 中断投递（int 指令只触发 UC_HOOK_INTR，不执行处理器）
· iretq 特权级返回
· 硬件中断（PIT/PIC 不产生真实 IRQ）
```

**QEMU 什么都能做**：

```text
· 真实模式切换 / 中断投递 / iretq / 磁盘写入（落盘到镜像文件）
· 用 -display none + monitor 读 VGA 缓冲区 0xB8000 还原整屏
· 用 -d int,cpu_reset 日志 + info registers 看精确 CPU 状态
```

---

## 6. 已知陷阱表（机器码层面，全部踩过）

| # | 陷阱 | 症状 | 修法 |
|---|---|---|---|
| 1 | 标签跨函数重名 | 通配跳转、随机行为 | 每个函数用独立标签（`new_label()`） |
| 2 | 多参数压栈顺序 | 参数被交换（加法 commutative 掩盖了） | 反转 pop 顺序 |
| 3 | 嵌套块里的 `let` 不在栈帧 | 变量错位 | prescan 递归整棵语句树 |
| 4 | 4 字节槽用 8 字节存储 | 覆盖保存的 rbp | 用 32 位存储指令 |
| 5 | 顶层代码掉进函数体 | 执行错乱 | 每个函数前发 `jmp` 跳过并回填 |
| 6 | 宿主二进制与编译器数据区重叠 | "莫名回归" | 宿主放 0x10000，源码 0x20000，栈 0x30000 |
| 7 | `xor` 自身缺 REX.R | 写错寄存器 | 手动补 `44`/`4C` 前缀 |
| 8 | `test al,0` 恒 ZF | 条件永远成立 | 用 `test ax,ax` |
| 9 | `rep stosw` 需要 DF=0 | 内存越界 | 先 `cld` |
| 10 | 16 位远跳进 64 位段不生效 | 落在 fall-through 的 halt | 必须经 32 位兼容模式（三段式） |
| 11 | `pushaq`/`popaq` 在 64 位非法 | 一进处理器就崩 | 显式 14 条 push/pop，且不含 rbp |
| 12 | 输出缓冲区覆盖编译器自身 | 41,384 字节"确定性爆量" | 输出上限检测 |

---

## 7. 当前状态（诚实版）

```text
产品内核（跑在机器上的字节）：100% Ds 编译，真机确认可运行   ✅
引导链                     ：Python 版（真机可启动）
                             Ds 版为实验，卡在 16→64 远跳    ⏳
16 位写盘 thunk            ：QEMU 真写盘验证通过             ✅
日志落盘                   ：热复位方案被 QEMU 证伪           ❌
                             需改长模式→实模式回退
编译器自举                 ：mcc10 已能解析自身大部分源码      🔄
                             剩余根因：emit_cmp_bool 不支持
                             "函数调用做比较左值"
```

**Python 数量：dsos-os 内 29 个文件 / 3,256 行**

```text
编译器      2 个 / 1,131 行  ← 自举目标
构建烧盘     3 个 /   359 行
验证        24 个 / 1,766 行
```

---

## 8. 怎么安全地改代码

1. **先读** `compiler/HANDOFF-next.md`——最新进展、未完成项、刚踩的坑都在那
2. **只改一处**，立刻跑对应验收
3. **内核改动**：`verify_dsos.py`（25 项）必须全绿
4. **编译器改动**：`verify_mini.py`（17 项）+ 各 `verify_mcc*.py` 必须全绿
5. **引导链改动**：必须先在 QEMU 里 `verify_qemu_boot.py` 通过，**再考虑**刷盘
6. **刷盘前**：`Get-Disk 1 | Check BusType=USB, IsSystem=False, IsBoot=False`
7. **刷盘后**：回读比对哈希，确认与构建产物一致

**绝对不要**：

```text
· 把未在 QEMU 验证过的引导链刷进 U 盘（已经因此让用户两次开不了机）
· 声称"已验证"而实际只做了结构性检查
· 删除 bootchain.bin（唯一的真机可启动引导链存档）
```

---

## 9. 建议的阅读顺序

```text
1. compiler/HANDOFF-next.md          最新状态与坑
2. ds/kernel.ds                      内核全貌（540 行，通读）
3. AGENTS.md                         硬性规则（尤其规则 0/2/6/8/9）
4. docs/MANUAL.md                    用户手册
5. compiler/mini.py                  看编译器如何把 Ds 变成机器码
6. ds/verify_dsos.py                 看怎么验证内核行为
7. ds/verify_qemu_boot.py           看怎么用 QEMU 做全链路验证
8. compiler/mcc10.ds                 看自举编译器（进行中）
```

---

## 10. 设计哲学

```text
1. 失败隔离    高风险特性（模式切换、写盘）必须是可选命令，绝不放在启动路径上
2. 可诊断      每次启动都在屏幕上留日志；黑屏时靠进度标记定位
3. 诚实标注    未验证就说未验证，不把 69% 说成 100%
4. 单一版本    每个目录只有一份当前镜像，避免刷错
5. 自举为终    编译器最终必须用 Ds 写，Python 才能退出
```
