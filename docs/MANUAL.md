# DsOS 说明书

> 适用版本：**v0.9**（内核 7001 字节，全部由 Ds 源码编译）
> 这份文档面向"想把它跑起来"和"想看懂它在干什么"的人。

---

## 一、你需要什么

| 项 | 要求 |
|---|---|
| 一台 PC | x86-64，支持 **Legacy / CSM 启动**（纯 UEFI 机器需要先开 CSM） |
| U 盘 | 任意 USB 存储设备，**≥ 16 MB** 即可（镜像只用 1.44 MB） |
| 键盘 | PS/2 或"BIOS 模拟成 PS/2"的 USB 键盘（见 §6 故障排查） |
| 显示器 | 能显示 80×25 文本模式（VGA 兼容） |

> ⚠️ **U 盘上的数据会被全部覆盖**。请用一块空盘，或者先备份。

## 二、把系统写进 U 盘

### 方式 A：Windows（推荐，带守卫与校验）

```bash
cd ds
python3 flash_dsos.py
```

脚本会依次做五件事，任何一步失败都会中止：

```text
1. 检查镜像大小是 512 的整数倍，且 @510 == 0x55AA
2. 把目标盘前 16 MiB 清零（抹掉旧分区表与旧镜像残留）
3. 写入 1,474,560 字节
4. 回读逐字节比对
5. 抽样确认镜像之后是 0
```

写之前请自己确认盘号（脚本里是 `DISK = 1`）：

```powershell
Get-Disk | Format-Table Number, FriendlyName, BusType, IsSystem, IsBoot, Size
```

必须满足：`BusType = USB`、`IsSystem = False`、`IsBoot = False`、容量 < 64 GB。

### 方式 B：Linux / macOS

```bash
sudo dd if=dsos-ds.img of=/dev/sdX bs=4M conv=fsync status=progress && sync
```

> 写错盘会毁数据。用 `lsblk` 确认设备名，看清楚容量再动手。

## 三、从 U 盘启动

1. 插上 U 盘，重启
2. 开机第一屏就开始按**启动菜单键**（不同品牌不同）：

| 品牌 | 按键 |
|---|---|
| 华硕 / 技嘉 / 微星 | `F8` / `F11` / `F12` |
| 联想 / 惠普 / 戴尔 | `F12` / `F9` / `F12` 或 `Esc` |
| 通用 | `F11`、`F12`、`Esc` 轮流试 |

3. 在菜单里选 **`Generic Flash Disk`** 或 **`USB HDD`**
4. **不要选带 `UEFI:` 前缀的那一项**——本系统是 legacy MBR

### 如果启动菜单里看不到它

进 BIOS 改三项：

| 设置项 | 改成 |
|---|---|
| CSM / Legacy Boot / Launch CSM | **Enabled** |
| Secure Boot | **Disabled** |
| USB Legacy Support / XHCI Hand-off | **Enabled** |

### 进不去 BIOS？

Windows 里：`设置 → 系统 → 恢复 → 高级启动 → 立即重新启动 → 疑难解答 → 高级选项 → UEFI 固件设置`

## 四、屏幕上有什么

```text
DsOS v0.9  -  kernel compiled from Ds source      ← 标题：内核由 Ds 编译
Ds toolchain -> x86-64 machine code               ← 副标题
--------------------------------------------------
[boot] clear screen .................. ok         ┐
[boot] VGA 80x25 text mode ........... ok         │
[boot] heartbeat timer (port 0x80) ... armed      │ 启动日志
[boot] keyboard polling (0x64/0x60) .. armed      │ （同时进内存日志环）
[boot] memory log ring 0x4000 ....... 60 slots    │
[boot] ACPI S5 shutdown ............. ready       │
[boot] type 'help' then Enter                     │
[boot] entering main loop                         ┘

[beat 0042] /                                     ← 心跳
cmd>                                              ← 命令行
 DsOS v0.9 | help log shutdown off | ESC = halt    ← 状态栏（反显）
```

### 心跳

```text
[beat 0001] /   →   [beat 0002] -   →   [beat 0003] \   →   [beat 0004] |
```

- 方括号里的十六进制数**每 30 ms 递增一次**
- 末尾的 `| / - \` 每拍换一个

**这就是"系统活着"的证据**：只要它在动，就说明 CPU 在正常执行主循环，
没有三重故障、没有死锁。如果画面停住而心跳不动，就是卡住了。

## 五、命令参考

在 `cmd>` 后输入命令，按 **回车** 执行。当前只支持不带空格的英文小写命令。

| 命令 | 作用 |
|---|---|
| `help` | 列出所有命令 |
| `log` | 把内存日志环里的完整历史回放到屏幕（见下） |
| `shutdown` | ACPI S5 关机 |
| `off` | 同 `shutdown`（快捷键） |
| （按 `ESC`） | 立即停机 `cli; hlt`，画面冻结 |

| 按键 | 作用 |
|---|---|
| 字母 | 输入到命令行 |
| 回车 | 执行命令 |
| 退格 | 清空当前输入 |
| `ESC` | 停机 |

### `log` 命令

屏幕只有 16 行日志区（第 4–19 行），写满就往上滚，旧记录会看不见。
内核因此同时把每条日志写进**内存环形缓冲**（0x4000 起，60 个槽，每槽 64 字节）。

敲 `log` 回车，会把环形缓冲里**最近 60 条**全部回放到屏幕上：

```text
---- memory log ring --------------------------------
[boot] clear screen .................. ok
[boot] VGA 80x25 text mode ........... ok
...
[cmd] help ------------------------
[cmd]   help      this text
[cmd]   log       dump memory log ring
[cmd]   shutdown  ACPI S5 power off
[cmd]   off       same as shutdown
[cmd]   ESC       halt CPU
---- end of log -------------------------------------
```

> 注意：这是**内存日志**，关机就丢。落盘需要模式切换（见 §8）。

## 六、故障排查

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 直接进了原来的系统 | U 盘没被选为启动设备 | 重进启动菜单；确认选的是不含 `UEFI:` 的那项 |
| 启动菜单里根本看不到 U 盘 | 分区表无效 / CSM 关闭 / Secure Boot 开启 | 开 CSM、关 Secure Boot；确认镜像里有 0x0C 分区项（v0.9 已含） |
| 黑屏 + 光标停住 | 引导链读盘失败 | 检查 BIOS 是否限制单次读取扇区数；可换用 16 扇区版引导链（`bootchain16.bin`） |
| 有横幅，但心跳不动 | 内核主循环卡住 | 记录下横幅停在第几行，对照 §4 的日志判断卡在哪个初始化步骤 |
| 心跳在跳，但敲键盘没反应 | 键盘没有走 PS/2 模拟 | 换 PS/2 键盘，或在 BIOS 开 `USB Legacy Support` / `XHCI Hand-off` |
| 能打字，但 `help` 没反应 | 只映射了命令需要的字母 | 确认只用了小写字母；回车键是否正常 |
| `off` 后没断电 | 机器 ACPI 不支持 S5 或 FADT 结构不同 | 内核会退化为停机（画面冻结），属正常降级 |

## 七、自己构建

```bash
cd ds

python3 build_dsos.py     # Ds 源码 → 裸机机器码 → 可引导镜像
python3 verify_dsos.py    # 完整验证（不需要硬件，用 unicorn）
```

`build_dsos.py` 做的事：

```text
kernel.ds  --(Ds 编译器 mini.py, target=bare)-->  裸机 x86-64 机器码
          +  bootchain.bin（冻结引导链，4608 字节）
          →  在 0x1BE 写入合法 MBR 分区项（类型 0x0C）
          →  在分区起点 LBA 2048 放一份引导扇区副本
          →  dsos-ds.img（1,474,560 字节）
```

`verify_dsos.py` 覆盖 15 项断言：

```text
A 启动      横幅 / 日志 8 行 / 心跳推进 / ESC 停机
B help      帮助文本落屏 / 命令行回显
C shutdown  ACPI 写 0x604 = 0x3400 / 停机
E log       内存日志环回放 / 结束标记
F off       off 命令 / ACPI 写 0x3400 / 停机
D           未知命令提示
```

## 八、当前能力边界

| 有 | 没有 |
|---|---|
| 启动、长模式、VGA 文本输出 | 中断 / IDT（键盘靠轮询） |
| 键盘轮询与命令行 | 文件系统、内存分配器 |
| 屏幕日志 + 内存日志环 | 日志落盘（需模式切换 thunk，无法用 unicorn 验证） |
| 心跳计时（端口 0x80） | 时钟中断、多任务 |
| ACPI S5 真关机 | 用户态、系统调用 |
| | UEFI 启动 |

## 九、文件清单

```text
ds/
├─ kernel.ds          内核源码（9566 字节 → 编译出 7001 字节机器码）
├─ build_dsos.py      构建：编译 + 拼接 + 打分区表
├─ verify_dsos.py     验证：15 项断言（unicorn 执行）
├─ flash_dsos.py      烧盘：守卫 + 清零 + 写入 + 回读
├─ bootchain.bin      冻结引导链（32 扇区版，4608 字节）
├─ bootchain16.bin    原版引导链（16 扇区版，备用）
└─ dsos-ds.img        生成的可引导镜像
```

内核源码结构：

```text
kernel.ds
├─ VGA 驱动      文本模式写字符（字符与颜色打包成一个整数）
├─ 日志系统      屏幕上滚 + 内存环形缓冲
├─ 心跳          端口 0x80 延迟 + 计数 + 旋转字符
├─ 键盘驱动      轮询 0x64/0x60，扫描码映射
├─ 命令行        哈希识别（h = h*33 + c）
├─ ACPI S5       RSDP → RSDT → FADT → PM1a_CNT
└─ 状态栏
```

## 十、想要更多

- 项目路线：[`ROADMAP.md`](../ROADMAP.md)
- 操作规约：[`AGENTS.md`](../AGENTS.md)（先验收再烧盘、三档标注、单一现行版本）
- 编译器谱系：[`compiler/HANDOFF-next.md`](../compiler/HANDOFF-next.md)
