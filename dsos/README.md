# DsOS（v0.1 架构骨架）

DsOS 是用 Ds+ 写内核、Ds/Cut 写启动/异常的实验性 OS。
**状态**：架构 + 启动代码 + 上下文切换 + 链接脚本；内核主体为路线图。

- 架构：[docs/DSOS.md](../docs/DSOS.md)
- Cut 规范：[spec/DS-CUT.md](../spec/DS-CUT.md)
- 编译器原型：[cut/cutc.py](../cut/cutc.py)

## 双目标

| 目标 | 架构 | 后端 | 产物 |
|---|---|---|---|
| RP2350 / Pico 2 | Cortex-M33 (ARMv8-M) | Thumb-2 | ELF → UF2 |
| Raspberry Pi Zero 2 W | Cortex-A53 | AArch64 | ELF → kernel8.img |

**注意**：Zero 2 W 不是 Thumb/.uf2；任务原文的“Zero 2 W + Thumb + .uf2”已在本设计中纠正。

## 构建（RP2350）

```bash
python3 cut/cutc.py dsos/boot/rp2350_start.ds --cut --emit asm -o build/start.s
clang --target=thumbv8m.main-none-eabi -c build/start.s -o build/start.o
ld.lld -T dsos/bsp/rp2350.ld -o build/dsos.elf build/start.o
llvm-objcopy -O binary build/dsos.elf build/dsos.bin
# UF2 需要 uf2conv.py 与 RP2350 family id
```

## 目录

```text
dsos/
├── boot/    rp2350_start.ds、zero2w_start.ds
├── arch/    context_switch_thumb.ds、context_switch_aarch64.ds
├── bsp/     rp2350.ld、zero2w.ld
└── kernel/  调度/内存/中断/syscall（Ds+，路线图）
```
