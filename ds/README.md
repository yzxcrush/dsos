# ds/ — DsOS 内核源码

> **这里的内核 100% 由 Ds 源码编译而来。**
> 7001 字节机器码，一行 C、一行汇编都没有——全部由 Ds 编译器（`compiler/mini.py`）生成。

## 文件

| 文件 | 作用 |
|---|---|
| `kernel.ds` | 内核源码（9566 字节） |
| `build_dsos.py` | 编译 + 拼接冻结引导链 + 打 MBR 分区表 → `dsos-ds.img` |
| `verify_dsos.py` | 15 项断言（unicorn 执行，不需要硬件） |
| `flash_dsos.py` | 写 U 盘：守卫 → 清零 → 写入 → 回读比对 |
| `bootchain.bin` | 冻结引导链（MBR + stage2，32 扇区版，4608 字节） |
| `bootchain16.bin` | 原版引导链（16 扇区版，备用） |

使用说明见 [`../docs/MANUAL.md`](../docs/MANUAL.md)。

## 内核功能（v0.9）

```text
清屏 + 横幅
屏幕日志区（第 4–19 行，满则上滚）
内存日志环（0x4000，60 槽 × 64 字节）—— log 命令可回放
心跳（第 21 行，[beat NNNN] + 旋转字符，每拍 30ms）
命令行（第 22 行）：help / log / shutdown / off
ACPI S5 真关机（RSDP → RSDT → FADT → PM1a_CNT，写 (5<<10)|0x2000）
ESC 停机（cli; hlt）
状态栏（第 24 行，反显）
```

## 构建与验证

```bash
python3 build_dsos.py     # → dsos-ds.img（1,474,560 B）
python3 verify_dsos.py    # → RESULT: PASS (15 项)
python3 flash_dsos.py     # → 写 U 盘（先确认 DISK 号！）
```

实测输出：

```text
kernel.ds 编译: 7001 字节（上限 12288）
[image] 引导签名 0x55AA:        PASS
[image] 内核槽字节 == Ds 输出:   PASS
[image] MBR 分区项(0x0C):        PASS
[image] 分区起点有引导扇区副本:   PASS
sha256: d2f24a183b9a033956c0ece413dfd5d9f5a1d063faf2225895a87a4160411fc5
```

## 内存布局（内核视角）

```text
0x1000–0x3FFF  stage2 建立的页表（内核不得写）
0x4000–0x4EFF  日志环形缓冲（60 槽 × 64 字节）
0x4F00         日志计数
0x6000–        代码缓冲（编译器用）
0x9000–        内核本体（本文件编译产物）
0xB8000        VGA 文本缓冲区
```

## 边界

| 项 | 状态 |
|---|---|
| 内核源码 = Ds | ✅ 100% |
| 内核字节 = Ds 工具链产出 | ✅ 真机已验证（v0.9） |
| 引导链 = Ds | ❌ 仍是 Python 发射器（规则 9 的冻结豁免） |
| 中断 / 文件系统 / 日志落盘 | ❌ 未实现 |
