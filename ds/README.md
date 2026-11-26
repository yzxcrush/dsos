# dsos-os/ds — 最小可运行的 DsOS（全 Ds 源码）

> **这是 DsOS 第一次由 `.ds` 源码编译出内核字节。**
> 之前所有能跑的镜像，内核都是 Python 发射器生成的机器码；这里的 1201 字节，全部由 Ds 工具链生成。

## 组成

| 文件 | 作用 |
|---|---|
| `kernel.ds` | 内核源码（纯 Ds）：清屏、打印横幅、轮询 PS/2 键盘回声扫描码、ESC 停机 |
| `verify_dsos.py` | 把 `kernel.ds` 编译成裸机机器码，在 unicorn 里执行并断言屏幕内容 |
| `build_dsos.py` | 编译 → 写入冻结引导链的内核槽（0x9000 / 文件偏移 4608）→ 产出 `dsos-ds.img` |

## 构建与验证

```bash
cd compiler
python3 ../ds/verify_dsos.py     # 内核跑通（3 项断言）
python3 ../ds/build_dsos.py      # 产出可引导镜像 dsos-ds.img
```

实测输出：

```text
kernel.ds 编译: 1201 字节（内核区上限 4096）
屏幕内容:
  | DsOS v0.6 - kernel compiled from Ds source
  | Ds toolchain -> x86-64 machine code
  | keys echo scancodes; ESC halts
  | 1e20
[dsos] 横幅由 Ds 编译的内核打印: PASS
[dsos] 键盘扫描码回显 1e/20:     PASS
[dsos] ESC 触发停机:              PASS
RESULT: PASS
```

镜像构建：

```text
[image] 引导签名 0x55AA:        PASS
[image] 内核槽字节 == Ds 输出:   PASS
[image] 镜像大小未变:            PASS
sha256: d516ab270ea82bcddf85ef1cf2c3ae0c3034b9e399a6e2a72529660f6e735db2
```

## 内核做了什么

```text
_start
  ├─ clear()                     2000 个单元写空格 + 属性 0x07
  ├─ puts(0, "...")              横幅三行（字符串在 .rodata，RIP 相对寻址）
  └─ 循环
       ├─ in8(0x64) & 1          轮询键盘控制器状态
       ├─ in8(0x60)              读扫描码
       ├─ ESC(0x01) → halt()     cli; hlt; jmp $
       └─ 否则按十六进制回显       hexc(sc >> 4), hexc(sc & 15)
```

## 边界（标注纪律）

| 项 | 状态 |
|---|---|
| 内核源码 = Ds | ✅ 100% |
| 内核字节 = Ds 工具链产出 | ✅ 1201 B，指令级验证通过（unicorn） |
| 镜像可引导（MBR + stage2） | ✅ 引导链沿用已验证的 v0.5（未改动半字节） |
| **真机启动** | ❌ **未验证**（需要写 U 盘，属需要放行的操作） |
| 键盘（真机 PS/2） | ❌ 仅模拟器注入扫描码验证 |
| 引导链是否 Ds 编写 | ❌ 仍是 Python 发射器（规则 9 的冻结豁免），是 ⑥ 的剩余工作 |

**因此：这不是"DsOS 已完全用 Ds 写成"，而是"内核已经是 Ds 编译的，引导链还不是"。**

## 下一跳

1. 用 Cut/Ds 重写 stage1 + stage2（需要 16 位实模式代码生成，当前工具链没有）
2. 或：先把 stage2 的功能（读盘、进长模式）做成 Ds 可表达的形式
3. 内核功能补齐：IDT/中断、shell、ACPI 关机

目前的状态是"能上屏、能响应键盘、能停机"的最小 OS 内核，且全部由 Ds 源码编译而来。
