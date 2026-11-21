# DsOS Phase 1 — 最小可启动裸机内核（冻结候选）

> Multiboot ELF32：32 位入口 → GDT → PAE 长模式 → 64 位内核。  
> 不经过 C、汇编器、链接器、libc；`build.py` 直接生成机器码。

## 1. 文件

| 文件 | 层 | 说明 |
|---|---|---|
| `boot.ds` | Ds- | 启动契约：32 位入口、GDT、长模式跳转 |
| `GDT.DS` | Ds- | flat 代码/数据段 + 长模式段 |
| `uart.ds` | Ds- | COM1：`init/putc/puts/getc/has_data` |
| `kernel.ds` | Ds- | `kernel_main` + 模块系统预埋 |
| `linker.ld` | — | 入口 `_start`、1 MiB 布局（构建器直接产 ELF） |
| `Makefile` | — | `make` → `kernel.bin` |
| `run.sh` | — | QEMU Multiboot 运行 |
| `build.py` | 工具 | 直接机器码后端（当前 Phase 1 编译器） |
| `kernel.bin` | Ds- | Multiboot ELF32，入口 `0x100020` |

## 2. 关键修正（相对原始草案）

| 原始要求 | 修正 | 原因 |
|---|---|---|
| 16→32→64 | **32→64**（Multiboot） | Multiboot 引导器已进入 32 位保护模式；16 位只属 legacy MBR |
| `@addr 0x3F8` MMIO | **端口 I/O** `in/out` | 0x3F8 是 COM1 端口，不是内存映射 |
| 中文标识符 / `@raw` / `&str` | ASCII 字段 + `*u8` | Base 只允许 ASCII；`@raw` 属 Ds+ |
| `@export` / `@syscall` | 只写注释 | 不在 77 关键字/16 @ token 中 |
| `[zeroed();64]` | `static mut modules: [Module;64]` | Base 无值级数组重复；由 `.bss` 清零 |

## 3. 构建

```bash
cd dsos/phase1
make            # → kernel.bin
```

或：

```bash
python3 build.py
```

## 4. 运行

```bash
./run.sh
```

等价：

```bash
qemu-system-x86_64 -kernel kernel.bin -nographic -serial mon:stdio
```

预期串口：

```text
DsOS alive
tick: 1
tick: 2
...
```

输入任意字符立即回显；回车输出：

```text
keys= N lines= M
```

## 5. 内核行为

- `uart_init`：COM1 115200 8N1
- `puts("DsOS alive\r\n")`
- 心跳：`rdtsc` 忙等约 1e9 cycles，打印 `tick: N`
- 回显：轮询 LSR bit0，收到即回
- 统计：按键数 `r12`、行数 `r13`；回车打印
- 死循环不退出

## 6. 模块系统预埋（Phase 2 不改签名）

```ds
struct Module {
    name: [u8; 32],
    entry: u64,
    calls: [u64; 8],
    state: u32,
}

static mut modules: [Module; 64]
static mut module_count: u32 = 0

fn module_load(bin: *u8, len: u64) -> i32 { return -1; }
fn module_unload(name: *u8) -> i32 { return -1; }
fn module_list() -> () { }
```

模块侧标准接口（Phase 2 实装，注释声明）：

```text
@export module_init() -> i32
@export module_exit() -> ()
```

预留 syscall：

```text
1 sys_write   2 sys_read   3 sys_alloc   4 sys_free   5 sys_yield
```

**冻结规则**：`kernel.ds` 中上述签名、`Module` 布局、syscall 编号永不修改；Phase 2 只能新增实现文件。

## 7. 验证状态

- `kernel.bin`：ELF32、Multiboot magic/checksum、entry `0x100020`、GDT/长模式地址静态校验通过。
- QEMU 执行验证：见当前环境说明；未验证前不宣称 “alive/tick/echo 全绿”。
- 冻结标签：`dsos-phase1-v1` 仅在 QEMU 验证后打。

## 8. QEMU 失败时的 GRUB 路径

```bash
# 需要 grub-mkrescue / xorriso 的机器
mkdir -p iso/boot/grub
cp kernel.bin iso/boot/
printf 'menuentry "DsOS" { multiboot /boot/kernel.bin\n boot }\n' > iso/boot/grub/grub.cfg
grub-mkrescue -o dsos.iso iso
qemu-system-x86_64 -cdrom dsos.iso -nographic
```
