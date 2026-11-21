# spec/ABI-v1.md — x86_64 ABI v1（Ds+ 编译器与 DsOS 共用）

> 状态：**契约草案，待冻结**（freeze 后任何改动需 RFC + major 版本）
> 适用范围：Ds+ 编译器生成的代码、DsOS 内核、内核模块、跨模块调用。

---

## 1. 数据类型

| 类型 | 大小 | 对齐 | 说明 |
|---|---|---|---|
| `bool` | 1 | 1 | 0 / 1 |
| `u8` `i8` | 1 | 1 | |
| `u16` `i16` | 2 | 2 | |
| `u32` `i32` | 4 | 4 | |
| `u64` `i64` | 8 | 8 | |
| `usize` `isize` | 8 | 8 | 指针宽度 |
| `ptr[T]` / `*T` | 8 | 8 | 同一表示 |
| `[T; N]` | `size_of(T)*N` | `align_of(T)` | 数组，按元素对齐 |
| `struct` | 见 §2 | 最大成员对齐 | |
| 枚举 / `res[T,E]` | 见 §2.3 | 最大成员对齐 | 带 tag |

**禁止隐式数值转换**（Base 语义 B1/D1 已冻结）：不同宽度/符号的整数之间必须显式 `as`。

## 2. 布局

### 2.1 struct / 数组

```text
offset(field_0) = 0
offset(field_i) = align_up(offset(field_{i-1}) + size(field_{i-1}), align_of(field_i))
size(struct)    = align_up(offset(last) + size(last), align_of(struct))
align_of(struct)= max(align_of(field_i))
```

- 字段顺序**必须**保持声明顺序（不做重排）。
- `@packed` 结构体：`align = 1`，字段无填充；对未对齐成员的访问必须由编译器生成"拆分访问"或拒绝编译（v1 选择**拒绝编译**，避免隐式慢路径）。

### 2.2 数组

- 元素紧密排列，`size = elem_size * N`。
- `arr[i]` 的地址 = `arr + i * elem_size`（无边界检查；`--checked` profile 下生成检查）。

### 2.3 枚举 / `res` / `opt`

```text
tag:  u32（第一个字段，4 字节，位于 offset 0）
payload: 紧跟 tag，按最大成员的 align 对齐
size = align_up(4 + size(payload), align(payload))
```

## 3. 调用约定（SysV 兼容子集）

| 角色 | 寄存器 |
|---|---|
| 参数 1..6 | `rdi, rsi, rdx, rcx, r8, r9` |
| 参数 7+ | 栈（右到左压栈，每参数 8 字节对齐） |
| 返回值（标量） | `rax` |
| 返回值（≤16 字节结构体） | `rax:rdx` |
| 返回值（>16 字节） | 调用者分配，指针作隐藏第 0 参数（`rdi`） |
| 栈指针 | `rsp`，**调用点必须 16 字节对齐** |
| 调用者保存 | `rax, rcx, rdx, rsi, rdi, r8-r11` |
| 被调用者保存 | `rbx, rbp, r12-r15` |
| 方向标志 | `DF` 必须为 0（入口 `cld`，返回前保持 0） |
| 浮点 | v1 不使用（无 SSE 约定；内核禁用浮点） |

### 3.1 栈帧

```text
[高地址]
  ...调用者栈...
  参数 7+
  返回地址            ← rsp 进入函数时指向此处
  [被调用者保存的 rbp]
  局部变量 / 临时区
[低地址]              ← rsp（16 字节对齐）
```

- prologue：`push rbp; mov rbp, rsp; sub rsp, N`（N 为 16 的倍数）。
- epilogue：`mov rsp, rbp; pop rbp; ret`。
- **红区**不使用（中断可在任意时刻发生）。

## 4. 段与放置

| 段 | 内容 | 属性 |
|---|---|---|
| `.text` | 代码 | 只读、可执行 |
| `.rodata` | 字符串字面量、常量表 | 只读、不可执行 |
| `.data` | 有初值的全局 | 可读写 |
| `.bss` | 零初值全局 | 可读写、不占文件空间 |

语言层属性：`@section("…")`、`@at(addr)`、`@align(n)`、`@static`。

- `@at` 只能用于 `bare` profile（绝对地址放置）。
- 默认起始地址：`bare` profile 由 `--image-base` 决定；`linux` profile 由链接器决定。

## 5. 符号与重定位

```text
symtab entry: name, section, offset, size, kind(local|global|weak), type(func|object)
relocation:   where(section,offset), kind(ABS64|ABS32|PC32|GOT?), symbol, addend
```

v1 只要求三种：

| 类型 | 用途 |
|---|---|
| `ABS64` | `@at` 绝对地址、模块头 |
| `ABS32` | 小镜像内的绝对地址（`bare`） |
| `PC32` | 函数调用、字符串字面量（RIP 相对） |

## 6. Profile

| profile | 目标 | 运行时 | 入口 | 允许的段 |
|---|---|---|---|---|
| `bare` | 裸机镜像 | 无（无 GC、无 panic 展开，`panic` → `abort`） | `_start` | 全部 |
| `linux` | Linux 用户态 ELF | 最小（用户 allocator） | `_start` | 全部 |
| `dsos-module` | DsOS 可加载模块 | 由内核提供 | `module_init` | `.text/.rodata/.data`（`.bss` 由内核清零） |

`bare` 下额外约束：
- 不使用 SSE / x87；
- 不使用红区；
- `alloc/free` 由用户提供 `ds_raw_alloc` / `ds_raw_free`（`@raw` 区域语义）。

## 7. 入口点

| profile | 入口符号 | 进入时的状态 |
|---|---|---|
| `bare` | `_start` | 由 bootloader 决定；`rsp` 有效且 16 字节对齐，`DF=0`，未开中断 |
| `linux` | `_start` | SysV 进程入口（`argc/argv` 已在栈上） |
| `dsos-module` | `module_init` | 见 §8 |

## 8. DsOS 模块头（v1）

```text
offset  size  field
0       4     magic   = "DSM1"
4       2     abi     = 1
6       2     flags   (bit0: 需要 @unsafe)
8       4     text_off
12      4     text_size
16      4     rodata_off
20      4     rodata_size
24      4     data_off
28      4     data_size
32      4     bss_size
36      4     entry_off        (相对 text_off)
40      8     module_name[16]  (NUL 填充)
56      4     header_crc32
60      4     reserved
64            .text ...
```

`module_init(ctx: *ModuleCtx) -> i32`：成功返回 0，失败返回负错误码。

## 9. Syscall 编号（DsOS v1）

| # | 名称 | 参数 | 返回 |
|---|---|---|---|
| 0 | `exit` | `code` | 不返回 |
| 1 | `write` | `fd, buf, len` | 写入字节数 |
| 2 | `read` | `fd, buf, len` | 读到字节数 |
| 3 | `open` | `path, flags` | fd |
| 4 | `close` | `fd` | 0 |
| 5 | `yield` | — | 0 |
| 6 | `sleep_ms` | `ms` | 0 |

**当前 DsOS 状态**：0–1 未实现（无系统调用接口），此表为 ABI v1 契约，先冻结编号，实现延后。

## 10. 冻结检查清单

- [ ] 结构体/数组布局与 §2 一致（用例：嵌套 struct、数组、`@packed` 拒绝编译）
- [ ] 调用约定与 §3 一致（用例：6 参数、7 参数、结构体返回）
- [ ] `bare` profile 能产可引导镜像
- [ ] 模块头字段与 §8 一致（用例：解析自身模块头）
- [ ] 与现有 `dsos/shell/kernel.py` 的 Python Stage-0 行为等价（作为 oracle 对照）
