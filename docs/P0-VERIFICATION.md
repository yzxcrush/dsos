# P0 交接验收与运行时证据

> 交接包：`D:\下载\交接.zip` → 解压于 `D:\文档\deepseek-harness\default-workspace\交接\交接\`
> 执行者：接任的 AI 工程代理
> 时间：2026-11-21 18:30–19:10（Asia/Shanghai）
> 环境：Windows 11 / AMD64（i5-12400F，VT-x 已在固件启用）/ Python 3.13

**结论先说**：交接文档指定的第一步（QEMU 实跑）**没有完成**，因为本机装不上 QEMU（详见 §5）。
但我用 **unicorn（QEMU 的 TCG CPU 核心）** 把产物真正执行了一遍，拿到了第一份**运行时证据**：
`DsOS alive` 与 `tick: 1..5` 是**真实机器码跑出来的**，不是静态推断。

---

## 1. 交接包完整性（通过）

| 检查 | 结果 |
|---|---|
| `SHA256SUMS` 34 项 | **34/34 匹配**，0 缺失 |
| `MANIFEST.json` 声明 | 1516 文件 / 84,002,006 字节 / `redacted: true` |
| 实测磁盘 | 1521 文件 / 84,365,707 字节，**0 处尺寸不符** |
| 多出的 5 个文件 | `MANIFEST.json`、`SHA256SUMS`、子目录同名两份、`最后的话.txt` —— 自引用条目，合理 |

复现命令：

```powershell
$py = <bundled python>
& $py 交接\_verify_pkg.py     # 见本目录脚本
```

## 2. 构建可复现性（通过）

把四个生成器的产物删掉后重新生成，与提交版本逐字节比对：

| 生成器 | 产物 | 结果 |
|---|---|---|
| `dsos/toolchain/step1/gen_step1.py` | `syscall.bin` (46B) | **IDENTICAL** |
| | `syscall.elf` (166B) | **IDENTICAL** |
| | `bare_serial.bin` (512B) | **IDENTICAL** |
| | `syscall.hex` | 内容相同，**仅换行符不同**（Windows 文本模式写出 CRLF） |
| `dsos/images/x86_64/gen_boot.py` | `dsos-x86_64.img` (1,474,560B) | **IDENTICAL**，sha256 `32669f00…` 与 README 一致 |
| | `dsos-bios.img` (512B) | **IDENTICAL**，sha256 `870cd07c…` |
| `dsos/phase1/build.py` | `kernel.bin` (4731B) | **IDENTICAL**，sha256 `2feeceaa…` |

结论：**“纯 Python 生成器直接产机器码，无 C/汇编器/链接器”这条主张是可复现的**，不是一次性手工产物。

## 3. 指令级执行证据（本报告的核心）

工具：`unicorn 2.1.4` —— 即 QEMU 的 TCG CPU 核心，**真实 x86_64 指令译码与执行**，不是模拟语义而是执行机器码。
串口通过 hook COM1 端口捕获；`int 13h` 磁盘读由宿主按镜像内容模拟。

### 3.1 `syscall.bin`（Step 1，46 字节，x86_64 用户态）— PASS

```text
write(fd=1, 13B) -> b'DsOS booted.\n'
exit code seen: 0
```

说明：手写机器码的 `mov/lea/syscall` 编码正确，SysV 参数寄存器（rdi/rsi/rdx）与 syscall 号映射正确，`lea rsi,[rip+disp32]` 的 RIP 相对寻址算对。

### 3.2 `bare_serial.bin`（Step 1 兜底，16 位实模式）— PASS

```text
out-hook calls: 14  ports={'0x3f8': 14}
serial captured: 'DsOS booted.\r\n'
```

### 3.3 `dsos-bios.img`（512B 兜底引导扇区）— PASS（但见 §4 的文档问题）

```text
serial captured: 'DsOS booted.\r\n'
```

### 3.4 `dsos-x86_64.img` 的 16 位启动链 — 跑到长模式入口

```text
int13 read lba=1 n=8 -> 0x8000     ← stage1 按设计读 8 个扇区到 0x8000
final CR0 = 0x80000011             ← PE=1 且 PG=1
```

即：MBR → `int 13h` 读盘 → 跳 `0x0000:0x8000` → stage2 的 **A20 / GDT / 页表 / CR3 / CR4.PAE / EFER.LME / CR0.PG** 全部执行到位，`CR0` 最终为 `0x80000011`（PE|ET|PG）。
unicorn 的译码模式在实例创建时固定，无法在运行中从 16 位切到 64 位，所以这条链路到此为止（这是工具限制，不是代码问题）。

### 3.5 长模式内核（从 stage2 的 `jmp far 0x18:0x8095` 目标直接起跑）— PASS

```text
started at 0x8095
  GDTR installed: base=0x8400 limit=39
  out calls 69, in calls 63, rdtsc calls 19
  ports: {'0x3f8': 64, '0x3f9': 2, '0x3fa': 1, '0x3fb': 2, '0x3fd': 63}
  serial (64 bytes): '\x01DsOS alive\r\ntick: 1\r\ntick: 2\r\ntick: 3\r\ntick: 4\r\ntick: 5\r\ntick: '
  FINAL RIP: 0x8154
  'DsOS alive' present: True
```

逐项对应到它验证了什么：

| 观察到的现象 | 证明了什么 |
|---|---|
| `uart_init` 写 `0x3F9/0x3FB/0x3F8/0x3FA` | COM1 初始化序列执行（首字节 `\x01` 是 DLAB=1 时写 DLL 的除数，属正常） |
| 63 次读 `0x3FD` 且拿到 `0x20` | `putc` 的“等发送保持寄存器空”轮询逻辑正确 |
| `DsOS alive\r\n` | `puts` + `lodsb` + RIP 相对寻址 + 串口输出链路全通 |
| `tick: 1` … `tick: 5` 单调递增 | `print_u32` 十进制转换正确；`rdtsc` 拼接（`EDX:EAX`）+ 比较 + 分支正确 |
| `rdtsc calls 19` | 心跳循环的 TSC 差值逻辑被执行（为免 1e9 周期忙等，宿主把 TSC 合成加速，见 §6 声明） |

**这是 DsOS 第一次有运行时输出证据。** 但它不等于“在真机/QEMU 里启动成功”——边界见 §6。

## 4. 发现的问题（3 项，按严重度）

### 4.1 `dsos-bios.img` 的文档把能力说大了

- `dsos/images/x86_64/README.md` §3 写：兜底镜像「期望串口打印 `DsOS alive` 并持续递增 `tick: N`」。
- 实际：`dsos-bios.img` 与 `dsos/toolchain/step1/bare_serial.bin` **字节完全相同**（sha256 均为 `870cd07c…`），只打印 `DsOS booted.`，**没有 `alive`，没有 tick**。
- 生成器 `gen_boot.py::simple_bios_sector()` 里写死的字符串就是 `b"DsOS booted.\r\n"`，所以是**文档错，不是镜像错**。
- 影响：任何照 README 验证兜底镜像的人会以为心跳没跑起来。按交接文档 §9「不把未验证说成已运行」的红线，这条应改。

### 4.2 216 项测试在本机 18 项失败，全部是跨平台缺口

```text
Ran 216 tests → 197 通过 / 18 失败
```

| 组 | 数量 | 根因 | 是否语言缺陷 |
|---|---|---|---|
| `test_driver` | 5 | 直接 `Popen(["./ds"])`，而 `ds`/`dscc` 是 POSIX shebang 脚本 | 否 |
| `test_dspm` | 13 / 14 | 依赖 `file://` URL + `tar` + 类 UNC 路径语义 | 否 |
| （另）解码 | 6 | `subprocess.run(text=True)` 未指定 `encoding`，用系统 GBK 解 UTF-8 中文输出；置 `PYTHONUTF8=1` 后消失 | 否 |

语言层（parser / checker / interpreter / 整数宽度 / Unicode 策略 / 0.1c / Flow / 指针 / 错误 / 控制流）**197 项全绿**。
建议修法（不碰 Base 语义）：补 `encoding="utf-8"`、给 POSIX-only 用例加 `skipUnless(os.name=="posix")`、`file://` 用 `Path.as_uri()` 构造。

### 4.3 `syscall.hex` 在 Windows 上生成 CRLF

内容与仓库版本完全一致，只差换行符。属生成器在 Windows 文本模式下写出的副作用；若要参与校验应显式 `newline="\n"`。

## 5. QEMU 为何没装成（阻塞项，需要你决策）

| 尝试 | 结果 |
|---|---|
| `qemu-w64-setup-20260811.exe`（197MB，SHA-512 校验**通过**） | 静默安装 `/S` 与 `/S /D=D:\qemu` **均退出码 2**，无任何文件产出 |
| 7-Zip 9.20 / 23.01 / 25.01 解包该安装器 | 全部「Cannot open as archive」——不是标准 NSIS 可解析结构 |
| 手动解析 NSIS 尾部头 | 偏移字段指向垃圾数据，确认非标准 NSIS 布局 |
| WSL | `wsl.exe` 存在但**没有任何发行版**；`wsl --install` 需下载+可能重启 |
| Virtualization | CPU 支持（`VirtualizationFirmwareEnabled=True`），但 `HypervisorPresent=False` |

所以“QEMU 实跑”这一步**没有替代方案能在本机立刻完成**，除非安装 WSL2 发行版（大概率要重启）。

## 6. 必须说清的边界（不要把上面的 PASS 读过头）

| 已验证（运行时） | **未验证** |
|---|---|
| 产物字节与生成器一致（可复现） | 真实 BIOS/固件把 MBR 载入 0x7C00 |
| 46B syscall 代码执行并写 stdout | 真实 `int 13h` 磁盘服务（我用宿主模拟） |
| 16 位 COM1 输出 | **真实的 16→32→64 位模式切换**（我用“直接以 64 位起跑”绕过） |
| A20/GDT/页表/PAE/EFER/CR0.PG 指令序列执行到 `CR0=0x80000011` | 分页真正生效后的地址翻译副作用 |
| 长模式内核输出 `DsOS alive` + `tick: N` | **真实 TSC 驱动的 ~1 秒节拍**（宿主合成了 TSC 以避免 1e9 周期忙等） |
| `print_u32` / `puts` / `putc` 逻辑 | 真实 UART 时序与硬件流控 |
| — | **Multiboot 路径**（`phase1/kernel.bin` 用 `-kernel` 加载）从未执行 |

一句话：**代码正确性有了第一份证据；启动链的物理真实性仍然空白。**

## 7. 复现命令

```powershell
$py = 'C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py 交接\_verify_pkg.py        # §1 完整性
& $py 交接\_regen.py             # §2 可复现性
& $py 交接\_inspect_artifacts.py # ELF/Multiboot/引导签名静态检查
& $py 交接\_emulate.py           # §3.1–3.4
& $py 交接\_emulate64.py         # §3.5
```

依赖：`pip install unicorn`（2.1.4）。全部脚本在 `交接\` 下，只读交接包，不修改它。

---

## 8. 真机验证记录（2026-11-21）

这一节补上了本报告 §6 里标为"未验证"的绝大部分。

### 方法与结果

1. 用 `gen_boot.py --vga` 生成 `dsos-x86_64-vga.img`（VGA + 串口双通道，1,474,560 B，
   sha256 `7559cead34556b03476ff3349a6537fcc6f8c0591ece8b6ba86ae9cf4f725c4e`）。
2. 写入一块 7.5 GB USB（`\\.\PhysicalDrive1`，legacy MBR），写入后回读 **逐字节一致**，
   扇区 0 首字节 `fa 31 c0 8e d8…`，签名 `55aa`，分区表全 0。
3. 在真机上以 **legacy BIOS / CSM** 方式启动该 USB。

**观察结果**：屏幕出现**持续递增的数字**（心跳计数）。

### 这一结果证明了什么

| 项 | 为什么被证明 |
|---|---|
| 真实 BIOS 把 MBR 载入 `0x7C00` 并执行 | 没有这一步，后面什么都跑不出来 |
| 真实 `int 13h` 读盘成功 | stage1 读盘失败会 `hlt` 停机，绝不会进内核 |
| **真实的 16 → 32 → 64 位模式切换** | tick 输出由 64 位代码产生；能持续输出即已在长模式 |
| A20 / GDT / 页表 / PAE / EFER / `CR0.PG` | 长模式必须全部正确才可能执行 64 位指令 |
| 真实 TSC 心跳 | 数字持续递增 |
| VGA 文本输出（`0xB8000`） | 屏幕可见 |

### 仍未证明

- 真机 **COM1 串口**输出（验证机无串口线，未肉眼确认；代码路径与 VGA 同源）
- **Multiboot 路径**（`phase1/kernel.bin` 从未被 `-kernel` 加载）
- 键盘输入、中断、Shell、文件系统、进程、网络、GUI（均未实现）

### 一个已知的显示行为（不是 bug）

VGA 光标不做滚动：写满 25 行（4000 字节）后回到第 0 行覆盖。
因此心跳跑一阵之后，首行 `DsOS alive` 会被 `tick: N` 覆盖——屏幕上"只剩数字"是预期行为。

### 尚未采集的证据

验证时未取得屏幕照片。按本仓库红线第 4 条，正式打"已验证"标签时应附照片或串口日志；
当前状态记为 **真机观察确认，证据形式为口头报告**，照片待补。
