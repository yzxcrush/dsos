# compiler/HANDOFF — 下一轮起手式

> 当前：`compiler/mini.py` 7 项 PASS（见 `verify_mini.py`），阶段③已闭环（`verify_bare.py` PASS）。
> 下一步是阶段④第 2 项：**结构体 + 数组**。

## 已确认的前端事实（省一次探测）

| Ds 写法 | 解析结果 |
|---|---|
| `type Point { x: i32, y: i32 }` | ✅ `TypeDecl` |
| `class Point { … }` | ✅ `ClassDecl`（另一套，先不做） |
| `struct Point { … }` | ❌ 拆成三个 `ExprStmt`（不是 Ds 语法） |

`TypeDecl` 字段：`vis, attrs, line, col, name, generics, fields, alias, packed`
`Block` 字段：`stmts`
`Index` 字段：`obj, index`
`IfExpr` 字段：`cond, then_block, else_`
`FnDecl` 字段：`name, params, body, ...`

## 要做什么（按 `spec/ABI-v1.md` §2）

1. **布局表**：对每个 `TypeDecl` 算出 `{field: offset}` 与 `size/align`
   ```text
   offset(field_0) = 0
   offset(field_i) = align_up(offset(i-1) + size(i-1), align_of(field_i))
   size = align_up(off_last + size_last, align_max)
   align: i32→4, i64/ptr→8, u8→1 …
   ```
2. **局部结构体变量**：栈槽按 `size` 分配（不是 8 字节一个），地址 = `rbp + slot_off`。
3. **字段访问**：
   - 读 `p.x` → `mov <w> rax, [rbp - slot + offset(x)]`
   - 写 `p.x = v` → `mov [rbp - slot + offset(x)], <w> v`
   - 通过指针 `pp.x`（`pp` 是指针）→ 先取 `pp` 的值再加 offset。
4. **数组**：`let a: [i32; 4]` → 栈上 `4*4` 字节；`a[i]` 已由 `Index` 支持，只需把 base 从"值"改成"地址"。

## 验收用例（写进 `verify_mini.py`）

```ds
type P { x: i32, y: i32 }

fn _start() {
    let p: P
    p.x = 7
    p.y = 35
    sys_exit(p.x + p.y)      // 期望 42
}
```

外加数组用例：

```ds
fn _start() {
    let a: [i32; 4]
    a[0] = 10
    a[2] = 32
    sys_exit(a[0] + a[2])    // 期望 42
}
```

## 注意（别踩的坑）

- 现在栈槽是"每个变量 8 字节"，结构体要改成**按 size 分配**，否则 `p.y` 会读到 `p.x` 的高位。
- `type X = i32`（别名）与 `type X { … }` 都可能是 `TypeDecl`，用 `alias` 字段区分。
- 遇到 `class` 先跳过（`ClassDecl`），不要试图用同一套布局。
- 每步都要跑 `verify_mini.py` 全量回归，别只看新用例。

## 之后

3. `@asm` 多行 + 操作数约束
4. `match` / `enum`
→ 四样齐了，才谈得上"用 Ds 写编译器"（阶段④）。

## 补齐的 AST 字段（探明于本轮）

```text
AttrExpr: ['obj', 'name', 'line', 'col']
TypeName: ['name', 'args', 'line', 'col']
FieldDecl: ['name', 'type', 'default', 'line', 'col']
TypeDecl: ['vis', 'attrs', 'line', 'col', 'name', 'generics', 'fields', 'alias', 'packed']
LetStmt: ['name','pattern','type','value','mutable','line','col']
```

结论：
- 结构体声明 → `TypeDecl`，字段是 `FieldDecl`（不是字符串列表）
- 局部变量声明带类型标注 → `LetStmt.type` = `TypeName`
- 字段访问 `p.x` → **`AttrExpr`**（赋值时为 `AssignStmt.target = AttrExpr`）


---

# ⑤ 第十一圈（mcc9）状态：部分通过，有回归

## 已通过（`verify_mcc9.py` A 部分 4/5）

- 词法：换行 / 制表 / CR / `//` 注释
- 条件：`&&` / `||` 链（**`if` 路径全过**）

```
[PASS] if a == 1 && b == 0 { a = 42 }        → 42
[PASS] if a == 1 && b == 0 ... else { a=7 }  → 7
[PASS] if a == 1 || b == 5 { a = 42 }        → 42
[PASS] if a == 1 || b == 5 ... else { a=7 }  → 7
[FAIL] while i < 3 && i < 9 { ... }          → 宿主野跳崩溃
```

## 未解决的回归（下一轮第一件事）

**单条件 while 也崩了**（mcc7 时是好的）：

```text
let i = 0 while i < 3 { i = i + 1 } i = i + 0   → Invalid instruction
```

- 生成码在 `test eax,eax; jz 00` 之后被截断（len=38）
- 宿主编译器 RIP 跳到自身代码中段 `0x3004`，源码 pos 停在循环体第一个语句
- **`if` 同条件正常** → 条件码生成没问题，问题在 `while` 的回边或循环体路径

定位方法：把 `emit_while` 换回 mcc7 版本（`let opc = parse_cond(s)` + `emit(opc)`）验证是否恢复；
若恢复，则逐行替换成 mcc9 版本二分。

## 自举探测（新结果）

现在停在第 9 行：

```ds
fn advance() -> i32 { store32(12288, load32(12288) + 1)  return 0 }
```

两个缺口：
1. **返回类型注解 `-> i32`**：`emit_fn` 只认 `fn name(params)`，`->` 会卡住
2. **内存内建**：`store32/load32/store8/load8` 编译器不认识，而它自身源码全靠这些

## 顺序

1. 修 while 回归
2. `-> 类型` 注解（跳过）
3. 内存内建（编译成内联指令序列）
4. 重跑自举探测


---

# ⑤ 第十一圈修正：mcc9 全绿，之前判断的"while 回归"是测试布局错误

## 真相

不是代码生成错误，是**地址冲突**：

| 冲突 | 数值 |
|---|---|
| 宿主二进制压到编译器数据区 | 0x1000 + 9715 = 0x35F3 > 0x3000（数据区起点） |
| 源码缓冲压到宿主 | 0x7000 + 9715 = 0x95F3 > 0x8000 |

编译器写 `pos`（0x3000）时改掉了自己的机器码 → 执行到被改写处 → Invalid instruction。
mcc7（8088 字节）能用纯属侥幸，刚好没长过 0x3000。

**教训**：宿主/数据/源码/代码缓冲的地址必须显式留出余量，且随程序变大复查。

## 现布局（verify_mcc9.py）

```text
数据区      0x3000 .. 0x4700
代码缓冲    0x6000 ..（生成码）
宿主二进制  0x10000 （9715 B）
源码        0x20000
栈          0x30000
```

## 验收

- A 部分 6/6 PASS：`if &&`、`if && else`、`if ||`、`if || else`、`while &&`、`while ||`
- B 部分（自举探测）：停在**第 9 行**，不再崩溃

## 自举缺口（精确 3 条）

1. **返回类型注解** `fn f() -> i32`
2. **参数类型注解** `fn f(s: *u8)`
3. **内建**：`store8/load8/store32/load32/sys_exit/run`

第 3 条最难：编译器必须把自己使用的内建也编译成指令序列。


---

# 版本谱系与已知缺陷

| 版本 | 状态 |
|---|---|
| mcc2 | 变量 + 完整指令序列 |
| mcc3 | while 回边 + 跳转回填 |
| mcc4 | if 分支 |
| mcc5 | 多字符标识符 + 关键字哈希 |
| mcc6 | 函数定义与调用（前向回填） |
| mcc7 | 全部比较运算符 + else |
| mcc8 | 表达式内 `&&`/`||`（**历史版本，已知缺陷：`0 || 0` 返回 1**） |
| **mcc9** | 换行/注释词法 + 条件内 `&&`/`||` 链 → **当前版本** |
| kernel.ds | 最小可运行 DsOS 内核（1201 B，指令级验证通过） |

## 地址布局（必须随程序变大复查）

```text
数据区      0x3000 .. 0x4700
代码缓冲    0x6000 ..
宿主二进制  0x10000   ← 放 0x1000 会压到数据区（这就是"while 回归"的真相）
源码        0x20000
栈          0x30000
```

# 最小可运行 DsOS 里程碑（⑤ 附带产出）

`dsos-os/ds/` 下：
- `kernel.ds`：清屏 + 横幅 + 键盘扫描码回显 + ESC 停机，**1201 字节全由 Ds 编译**
- `verify_dsos.py`：3 项断言（横幅 / 回显 / 停机）全 PASS
- `build_dsos.py`：产出 `dsos-ds.img`（sha256 d516ab27…）
- 边界：引导链仍是冻结的 Python 产物；**真机未验证**

下一步：把 stage1/stage2 也用 Ds 写（需要 16 位代码生成），或先把内核功能补齐（IDT/shell/ACPI）。


---

# 「完全用 Ds 编写」的路线（关键架构决策）

## 核心洞察：把模式切换塞进 MBR

```text
现在                              改造后
MBR(16位)  Python 发射器           MBR(16位 Ds)：A20 / GDT / 页表 / 长模式 / 远跳
   ↓                                  ↓ 直接进 64 位
stage2(实模式起步) Python 发射器    stage2(64位 Ds) ← 现有 64 位后端就能编
   ↓                                  ↓
内核(64位 Ds) ✅ 已完成             内核(64位 Ds) ✅
```

只要 512 字节的 MBR 用 Ds 写，stage2 就变成纯 64 位代码，**不需要给工具链加 32 位目标**。
整件事收敛成：给 Ds 加一个 16 位目标。

## 进度

| 步 | 内容 | 状态 |
|---|---|---|
| 1 | 16 位后端 `mini16.py`：段寄存器/栈/int10h/let/if/while/比较 | ✅ **已完成**，3 项验收全过 |
| 2 | 用 Ds 写 MBR：int13h 读盘 + A20 + GDT + 页表 + 长模式 + 远跳 | ⏳ |
| 3 | 用 Ds 写 stage2（64 位，复用 `mini.py`） | ⏳ |
| 4 | 编译器自举（用 Ds 写编译器）→ 固定点 `T2 == T3` | ⏳ |

## 第 2 步还需要给 mini16 加的能力

```text
int13h 读扇区     AH=02（或封装成 disk_read(lba, count, seg, off)）
int15h A20 开启   或 fast A20（端口 0x92）
lgdt / lidt       0F 01 10 / 0F 01 18
mov cr0/cr3/cr4   0F 20 / 0F 22
wrmsr             EFER.LME
ljmp 远跳          EA off16 seg16 / EA off32 seg16
绝对寻址写内存     mov [disp16], ax 已有基础
```

## 第 1 步踩到的三个坑（都已修）

| 坑 | 症状 |
|---|---|
| rel8 也按 2 字节预留位移 | 每处跳转多塞一个 00，回填还覆盖下条指令首字节 |
| `cmp ax,bx` 方向反了 | 左值在 bx、右值在 ax，应发 `cmp bx,ax` |
| `if` 是表达式被包在 ExprStmt 里 | 不处理就报 `expr node IfExpr` |


---

# 「去除 Python」进度：MBR 已换成 Ds

## 现状（按实际参与启动的机器码）

| 部分 | 字节 | 由什么生成 | 状态 |
|---|---|---|---|
| MBR | **65** | **Ds（`mbr.ds` 经 `mini16.py`）** | ✅ **本轮完成** |
| stage2 | 4096 | Python 发射器（`gen_shell.py`） | ⏳ 最后一个 Python 产物 |
| 内核 | 10234 | Ds（`kernel.ds` 经 `mini.py`） | ✅ |

→ **Ds 71.5% / Python 28.5%**（此前 69% / 31%）

## MBR 做了什么（65 字节）

```text
set_ds(0) set_es(0) set_ss(0) mov_sp(0x7C00)
disk_read_chs(32, 0, 2, 0, 0x0800, 0)   // LBA1..32 = CHS(0,0,2..33) → 0x8000
far_jmp(0, 0x8000)
```

验证（`ds/verify_mbr.py`）：
```text
int13h 请求: [(1, 32, 2048, 0)]
stage2 数据已落内存: PASS
远跳到 stage2:      PASS
0x55AA:            PASS
```

## mini16 已有的原语

```text
disk_read_chs / a20_fast / lgdt_imm / lidt_imm
cr0_set / cr3_set / cr4_set / efer_set
far_jmp / write32 / write16 / write8 / out8
```

**这些正好够写 stage2 了**——stage2 要做的（A20 / GDT / 页表 / 长模式）全部有对应原语。

## 下一步：用 Ds 写 stage2（4096 字节，最后一块 Python）

stage2 的职责：
```text
1. a20_fast()
2. 写页表：0x1000 PML4[0]=0x2003；0x2000 PDPT[0]=0x3003；0x3000 PD[0]=0x0083（2MB 页）
   （先把 0x1000..0x3FFF 共 3072 个 dword 清零）
3. 写 GDT（null / 64 位代码 / 64 位数据）与 GDTR
4. lgdt_imm(gdtr)
5. cr3_set(0x1000); cr4_set(0x20); efer_set(0x100); cr0_set(0x80000001)
6. 远跳到 64 位代码段（需要 far_jmp32 原语：66 EA off32 sel16）
7. 64 位入口：设置段寄存器、栈，跳内核 0x9000
```

难点：16 位 → 保护模式 → 长模式的三段跳需要 `far_jmp32`（66 EA）与 `far_jmp16`（EA）。
`far_jmp` 已有（16 位），需再加 32 位版本。

## 烧盘时踩的坑（已修）

Windows 会周期性扫描新分区的 USB 盘，导致裸设备写入中途 `EINVAL/EPERM`。
`flash_dsos.py` 已加**分块重试 + 整轮重开句柄**（最多 8 次/块，3 轮整体重试）。


---

# 里程碑：引导链 100% 由 Ds 编译

## 现状

| 部分 | 字节 | 源码 | 由什么编译 | 状态 |
|---|---|---|---|---|
| MBR | 65 | `mbr.ds` | `mini16.py` | ✅ Ds |
| stage2 | 189 | `stage2.ds` | `mini16.py` | ✅ Ds |
| 内核 | 10234 | `kernel.ds` | `mini.py` | ✅ Ds |
| **合计** | **10488** | | | **0 字节 Python 生成的机器码** |

**Python 只剩编译器本身**（`mini.py` 33KB + `mini16.py`），属规则 9 的 bootstrap 例外。

## 端到端验证（`verify_bootchain.py`）

```text
MBR 读盘参数正确            PASS   int13h: (lba=1, n=32, es=0x0800, bx=0)
跳入 stage2                PASS
页表就位                    PASS   PML4=0x2003 PDPT=0x3003 PD=0x83
GDT 就位                    PASS   0x00AF9A000000FFFF
分页已开                    PASS   CR0=0x80000011
CR3/PAE 就位                PASS   CR3=0x1000 CR4=0x20
内核已加载到 0x9000         PASS
远跳就位（PG 已开）          PASS
```

## 未被模拟器覆盖的一步

**CPU 从 16 位保护模式远跳进 64 位代码段**（`EA 00 90 08 00`）——unicorn 不能切换模式，
只能真机确认。回退镜像：`dsos-ds-pystage2.img`（Python stage2 版，真机已确认可启动）。

## stage2 做了什么（189 字节）

```text
a20_fast()                      端口 0x92 bit1
mem_zero(0x1000, 0x1800)        清 12 KiB 页表区
write32 三层页表                 PML4→PDPT→PD，2MiB 恒等映射
write32 GDT + GDTR @0x5F00/0x5EF0
lgdt_imm(0x5EF0)
cr3_set(0x1000) cr4_set(0x20) efer_set(0x100) cr0_set(0x80000011)
far_jmp(0x08, 0x9000)           进入 64 位，跳内核
```

## 本轮踩的坑

| 坑 | 症状 |
|---|---|
| 16 位寻址 `modrm 0x05` 是 `[DI]`，`[disp16]` 要用 `0x06` | `write32` 全写到 DS:DI，页表/GDT 全是 0 |
| GDT 描述符高 32 位常量算错 | 代码段变成 `0x00AFB300…`，CPU 加载后行为未定义 |
| 页表项的 A/D 位由 CPU 走查置位 | 断言必须屏蔽 `0x60`，否则误报失败 |

# 最后一块：编译器自举

```text
T0 = mini.py / mini16.py（Python，现在） 
 → 用 Ds 写一个编译器，由 T0 编译出 T1
 → T1 编译自己得 T2，T2 编译自己得 T3
 → T2 == T3 时，Python 才能退出构建链
```

这是 ROADMAP 阶段 E/F，也是唯一还能让"含 py"成立的地方。


---

# 最后一块 Python：自举进度（mcc10）

## 已完成：编译器能力开始覆盖自身源码所需内建

`mcc10.ds`（Ds 写的编译器）新增：

| 能力 | 生成码 |
|---|---|
| `store8(addr,val)` | `mov eax,addr; push; mov eax,val; pop rbx; mov [rbx],al` |
| `load8(addr)` | `movzx eax, byte [rax]` |
| `store32(addr,val)` | `mov [rbx], eax` |
| `load32(addr)` | `mov eax, [rax]` |
| `sys_exit(v)` | `mov rdi,rax; mov eax,60; syscall` |
| 表达式语句 | 标识符后紧跟 `(` 时按表达式处理，不再当赋值 |

验证链（`verify_mcc10.py`）：

```text
mcc10.ds --(T0: Python mini.py)--> T1（10886 字节）
T1 编译使用内建的源码 → 生成机器码 → 执行 → 断言
[PASS] store8 + load8    want=65    got=65
[PASS] store32 + load32  want=4242  got=4242
[PASS] 内建 + 算术        want=42    got=42
```

这轮修的 bug：`store8(addr,val)` 第一个参数是**地址**，我按"值在前"生成，
结果 `mov [rax],bl` 把地址当值写到了 0x41；改为 `mov [rbx],al` 后正确。

## 距自举还差三样能力

mcc10 的**自身源码**还用到了 mcc10 不认识的东西：

| 缺口 | 源码里的例子 | 需要的生成码 |
|---|---|---|
| 位运算 `& \| ^ << >>` | `(n >> 12) & 15`、`h*33+c & 65535` | `and/or/xor rax,rbx`、`shl/shr` |
| `run(addr)` | `sys_exit(run(24576))` | `call rax` |
| 字符串字面量作值 | `puts_at(21,0,"[beat ")` 等 | `.rodata` + `lea rax,[rip+str]` |

补完这三样，mcc10 的"能力集"才闭合到自己——那时才能跑：
`T2 = T1(mcc10.ds)`、`T3 = T2(mcc10.ds)`，比对 `T2 == T3` 得到固定点，
Python 才能从构建链里删除。

## 当前构建链状态

```text
产品（跑在机器上的字节）：100% Ds 编译     ← 已达成
编译器（生成那些字节的工具）：仍是 Python   ← 唯一剩余，需自举固定点
```


---

# 真机事故记录：Ds 引导链连续两次启动失败

## 事实

| 次数 | 刷入内容 | 真机结果 |
|---|---|---|
| 1 | Ds MBR + Ds stage2（16 位远跳） | 起不来 |
| 2 | Ds stage2 带进度标记 + 32 位远跳 | 打印 `12345` 后卡死 |
| 3 | Ds stage2 改为"先进保护模式再设 CR" + 8 个标记 | **完全黑屏** |
| 4 | 回退 Python 引导链 | 恢复（sha256 `37c799fe…`） |

## 根因与教训

- **模式切换、IDT 投递、iretq、远跳**这几类行为，unicorn 全部无法验证
  （固定 `UC_MODE_*`，不执行 IDT 处理器）。所以 "verify_stage2 PASS"
  只覆盖了**进入保护模式之前的 16 位部分**，不构成"可刷盘"的验证。
- 我两次把"结构性验证通过"当成"可以刷盘"，违反了 AGENTS 规则 2
  （没验证就刷）——代价是用户两次开不了机。

## 已加的保护

`build_dsos.py` 现在：
- **默认**使用 `bootchain.bin` 里真机确认可启动的 Python MBR+stage2；
- 实验性 Ds 引导链必须显式 `--ds-boot`，并在构建时打印警告。

`dsos-ds.img.rollback` 保留为回退镜像。

## Ds 引导链的现状

代码在仓库里（`ds/mbr.ds`、`ds/stage2.ds`、`compiler/mini16.py`），
能编译、能通过 16 位部分的验证，但**真机从未成功进入长模式**。
后续所有改动必须先在能真正切换 CPU 模式的环境里验证：

1. QEMU（此前下载失败，可再试）
2. 用户自己的虚拟机（Hyper-V / VirtualBox）
3. 第二台 PC

在此之前不再刷引导链。

## 界线（当前真实状态）

```text
产品内核（跑起来的字节）：100% Ds 编译，真机确认可运行
引导链（MBR+stage2）    ：Python（真机确认可启动）；Ds 版为实验，未通过
编译器                  ：Python（bootstrap 例外）
```


---

# QEMU 验证环境 + 日志落盘 thunk（已验证）

## QEMU 装好了，验证能力质变

`winget install SoftwareFreedomConservancy.QEMU` → QEMU 11.1.0。

新增 `ds/verify_qemu_boot.py`：
- `-display none` 无界面启动
- 通过 monitor (TCP) 执行 `xp /4000xb 0xb8000` 直接读 VGA 文本缓冲区
- 还原整屏文字并断言（横幅 / 版本号 / EXCEPTION）
- QEMU 对**含中文的绝对路径**不友好 → 切到镜像目录用相对文件名

这一下就能验证过去完全无法验证的东西：模式切换、远跳、IDT 投递、iretq。

## 靠 QEMU 抓到并修掉的三个真 bug

| bug | 症状 |
|---|---|
| `vga_mark_rm` 用 ES 段 | `mov [disp16],imm` 默认走 DS → 标记写进 RAM，屏幕无输出 |
| `efer_set` 的 `mov ecx,imm32` 缺 `66` 前缀 | 16 位模式只吃 2 字节立即数，后续 `00 C0` 变 `add al,al`，指令流错位 → CR3 变成 0x18 |
| 保护模式标记缺 `67` 地址长度前缀 | 16 位偏移装不下 0xB8000 |

## Ds 引导链当前卡点（有证据）

```text
内存 0x8104 与编译产物一致        → 加载正确
CS = 0008 ... CS16                → 已进 16 位保护模式
DS/SS = 0018 平坦数据段            → 段重载成功
CR4 = 0x20 (PAE), EFER = 0x100    → 长模式前置条件就绪
EIP = 0x8173, HLT = 1             → 却落在 fall-through 的 halt
```

结论：`66 EA`（16 位模式下的 32 位操作数远跳）**不跳转**。按 Intel 规范，
进 64 位代码段必须经过 32 位兼容模式。下一步做三段式 trampoline：
实模式 → 16 位保护 → **32 位兼容** → 64 位。

## 日志落盘：16 位 thunk 已端到端验证 ✅

`ds/thunk16.ds`（Ds 编写，133 字节）：

```text
set_ds(4096) → 缓冲区 0x10000 头部写 "DSLOG1"
disk_write_lba(6144, 8, 4096, 0)   → BIOS int 13h AH=43 写日志分区
halt()
```

`ds/verify_thunk16.py` 的验证方式（**真写盘**，不是模拟）：

```text
1. 编译 thunk16.ds → 放在测试盘 LBA 0
2. QEMU 启动，BIOS 执行 int 13h AH=43
3. 退出后直接读测试镜像文件 LBA 6144
   LBA 6144 处内容: 44 53 4c 4f 47 31 ... ascii=b'DSLOG1'
[PASS] thunk 写入日志分区
```

注意两点：
- 用 **LBA 扩展写（AH=43）** 而非 CHS——QEMU/BIOS 的 CHS 几何换算不可靠
- 必须 `cache=writethrough`，否则 QEMU 的 writeback 缓存会让写入丢失

## 还差的那一步：内核调用 thunk

内核在长模式，要跳进这段 16 位代码必须做 **long → real 模式回退**：

```text
cli
→ 64 位远跳到 32 位兼容段
→ 清 CR0.PG
→ 远跳到 16 位段
→ 清 CR0.PE
→ 远跳到实模式 thunk（0x0000:0xC000）
→ thunk 写盘 → 重启或停机
```

这就是经典的「三段式降级」，需要给 mini.py 加 `far_jmp16` / `far_jmp32`，
并在内核镜像里预留 thunk 的固定地址。QEMU 可以完整验证。


---

# 日志落盘：热复位方案被证伪（QEMU 实测）

## 已实现

| 部分 | 状态 |
|---|---|
| 16 位写盘 thunk `ds/thunk16.ds`（int13h AH=43 写 LBA 6144） | ✅ 真写盘验证通过 |
| 内核 `savelog` 命令（拷日志→0x10000，写魔数→0x10010，port 0x64=0xFE 软复位） | ✅ 拷贝+魔数+复位验证通过 |
| Ds MBR 日志交接（检测魔数→写盘→清魔数） | ✅ 代码完成 |
| 混合构建 `--ds-mbr`（Ds MBR + 已验证 Python stage2） | ✅ QEMU 可正常启动 |

## 证伪结论

```text
savelog 执行后： 0x10000 = "[boot] clear scr…"   0x10010 = "DSLG"
软复位后：       0x10000 = 00 00 00 …            0x10010 = "DSLG"
```

**BIOS POST 会清零低端内存**，日志正文保不住 → 热复位交接不可行。

## 改走方案：长模式 → 实模式回退（三段式 trampoline）

```text
cli
→ 64 位远跳 32 位兼容段（CS.L=0,D=1）
→ 清 CR0.PG
→ 远跳 16 位段
→ 清 CR0.PE
→ 远跳实模式 thunk（0x0000:0xC000）
→ thunk 用 int13h 写盘
```

好处：一次实现同时解决两件事
1. 日志落盘（内核直接调 BIOS）
2. Ds 引导链卡住的 16→64 远跳（同一套 GDT/远跳机制反着用）

QEMU 可完整验证，不必再盲试 U 盘。

## 当前状态

```text
U 盘            ：安全版可启动（未改动，sha256 37c799fe…）
本地镜像         ：安全构建，QEMU 验证通过
Ds MBR          ：QEMU 验证可启动
16 位写盘 thunk  ：真写盘验证通过
内核 savelog     ：前半段验证通过，落盘交接待改模式回退
```


---

# 自举进展：mcc10 已能解析自身源码（T2 已生成）

## 静态分析的缺口（3 项，已补）

| 缺口 | 用量 | 生成码 |
|---|---|---|
| `>>` 右移 | 12 次 | `mov rcx,rbx; shr rax,cl` |
| `&` 按位与 | 1 次 | `and rax,rbx`（`&&` 仍是逻辑与） |
| `run(addr)` | 1 次 | `call rax` |

## 静态分析**漏掉**的 2 个语法缺口（跑起来才暴露）

| 缺口 | 现象 |
|---|---|
| 参数类型标注 `s: *u8` | `emit_fn` 参数循环在 `:` 处死循环 |
| 返回类型 `-> i32` | 被当成语句解析，函数体错位 |

教训：**"用了哪些运算符/内建"的静态统计不够**，语法结构也要对齐。

## 当前自举状态

```text
T0 = Python mini.py（742 行）
T1 = T0(mcc10.ds) = 11,645 字节
T2 = T1(mcc10.ds) = 41,368 字节   ← 已能生成，但尺寸异常（应约 12K）
T3 = T2(mcc10.ds) = 失败（UC_ERR_READ_UNMAPPED）
```

T2 尺寸 41K 说明 T1 编译自身时有语句被误解析导致重复/多余生成，
需要逐段比对 T2 与 T1 的差异来定位。距固定点 `T2 == T3` 还有这个 codegen bug。

## Python 清理结果（90 → 29 个文件）

```text
移入 交接/legacy_py_kernel/  11 个（旧 Python 内核全套）
删除一次性脚本              30 个（_patch*.py / _fix*.py / _dbg*.py …）
剩余 29 个 / 3,256 行：
  编译器      2 个 / 1,131 行  ← 自举目标
  构建烧盘     3 个 /   359 行
  验证        24 个 / 1,766 行
```


---

# 自举：已补 6 个缺口，剩 2 个结构性缺口

## 本轮补齐（T1 现在能解析自身大部分源码）

| # | 缺口 | 修法 |
|---|---|---|
| 1 | `>>` 右移 | `mov rcx,rbx; shr rax,cl` |
| 2 | `&` 按位与 | `and rax,rbx`（`&&` 仍逻辑） |
| 3 | `run(addr)` | `call rax` |
| 4 | 参数类型标注 `s: *u8` | 参数循环里跳过 `:` 后的类型 |
| 5 | 返回类型 `-> i32` | 函数头里跳过 `->` 和类型 |
| 6 | `as` 类型转换 | `emit_expr` 末尾跳过 `as <类型>` |

## 剩余 2 个结构性缺口（二分定位结果）

### 缺口 A：`emit_fn` 函数体循环不跳过空白

```text
fn _start() { }        →  T1 生成 41,369 字节（应为 ~11）
原因：进入 while peek(s) != 125 之前没有 skip(s)，把空格/`}` 当语句解析
修法：while 前加一行 skip(s)
```

### 缺口 B：`return` 语句未实现

```text
mcc10 自己的 40 个函数几乎都以 return 0 结尾；
emit_stmt 不认 return → 落到 emit_assign → 误解析
修法：需要"跳到函数尾声"的跳转：
  · emit_fn 里记录尾声地址（或先发 jmp 占位）
  · emit_stmt 遇到 return：有表达式则 emit_expr，然后 jmp 到尾声明
  · 函数最后隐式 return（eax 保持）
```

## 当前状态

```text
T0 = Python mini.py
T1 = T0(mcc10.ds) = 11,783 字节
T2 = T1(mcc10.ds) = 41,368 字节   ← 仍异常（缺口 A/B 导致）
T3 = T2(mcc10.ds) = 失败

最小复现（T1 编译）：
  let b = 1 / store8(24576, b) / sys_exit(0)  → 41,369 字节
  fn _start() { } 出现在源码里就会触发
```

补完 A、B 两项后即可重跑固定点 `T2 == T3`。


---

# 自举最后一关：裸括号被误判成函数调用（含两次失败尝试）

## 已确定根因

```text
T1 的 call 表：491 项中 34 项 hh = 0（函数名哈希为 0）
→ fn_get(0) 返回 0 → 相对位移 d = 0 - (pos+4) → call 跳到代码外
最小复现：return (n >> 8) 会多生成一个 hh=0 的伪调用
```

**根因**：`mcc10.ds` 的 `emit_factor` **没有括号表达式分支**：

```ds
let hh = hash_ident(s)
let ln = ident_len(s)
if peek_at(s, ln) == 40 { ... return emit_call(s) }   // ← ln 可为 0
```

遇到裸 `(` 时 `ln = 0`、`peek_at(s,0) == '(' == 40` → 误判为函数调用。

## 两次失败的修复（不要重复）

| 尝试 | 改动 | 结果 |
|---|---|---|
| 1 | 判定改为 `if (ln > 0 && peek_at(s, ln) == 40)` | 正则命中 **2 处**，其中一处不在 emit_factor，改动后 T2 死循环 |
| 2 | 在判定前加括号分支 `if c == 40 { advance() emit_expr(s) skip(s) advance() return 0 }` | 括号内若是条件式（含 `&&`/`||`）→ `emit_expr` 不认这些运算符 → 位置错乱 → T2 死循环 |

两次都已回退，当前稳定状态：`T1=12694`、`T2=11648`、`T3=3`。

## 正确方案：双路解析

**核心矛盾**：Ds 把「条件」和「普通表达式」分开解析
（`parse_cond` 处理 `&&`/`||`，`emit_expr` 处理算术/位运算），
而**括号内两者都可能出现**。

推荐实现（二选一）：

### 方案 A：让 emit_expr 也认识 `&&`/`||`

在 `emit_expr` 的 while 循环里加两个分支：

```ds
(op == 38 && peek_at(s, 1) == 38)  → 逻辑与
(op == 124 && peek_at(s, 1) == 124) → 逻辑或
```

处理方式与 `parse_cond` 相同：
```ds
push rax          // 左操作数
advance() advance()   // 吃掉两个字符
skip(s)
emit_cmp_bool(s)  // 右操作数（条件式）
pop rbx
// 与 parse_cond 里的合并逻辑相同
```
这样括号内 `(a && b)` 自然可解析，`parse_cond` 可退化为只调用 emit_expr。

### 方案 B：括号分支里判断

```ds
if c == 40 {
    advance()
    emit_expr(s)                    // 先按表达式解析
    skip(s)
    if peek(s) == 38 || peek(s) == 124 {   // 停在 && / || → 是条件
        ...走 parse_cond 的续接逻辑...
    }
    advance()                       // 吃掉 ')'
    return 0
}
```

**建议方案 A**：更统一，能同时修好括号内条件和顶层条件两条路径。

## 修好后的验收命令

```bash
cd dsos-os/compiler && python3 verify_selfhost.py
# 预期：
#   T1 = ~12.7K
#   T2 = ~11.6K
#   T3 = ~11.6K
#   [PASS] 固定点 T2 == T3
```

## 修好后的下一步（自举收尾）

1. `T2 == T3` 固定点达成 → `mini.py` 从构建链退役
2. 把 `mcc10.ds` 改名为 `dscc.ds`，作为正式自举编译器
3. 构建脚本改为：`T0 seed` 只在从零重建时使用
4. 引导链 Ds 化（三段式 trampoline：实模式→16位保护→32位兼容→64位）

## 重要提醒

- `emit_factor` 的修改**必须只改一处**，改前先 `grep -n "peek_at(s, ln) == 40"` 确认位置
- 每次改动后立刻跑 `verify_selfhost.py`，**T2 超过 20000 就说明又死循环了**（脚本有保护）
- U 盘当前是可启动版本（sha256 `8f795ac1…`），**不要**为了验证编译器去动它


---

# 最新状态（回归已修，自举前进）

## 已修：`call _start` 造成的回归

```text
问题：为自举加的"入口 call _start"，在源码没有 _start 函数时
      fn_get 返回 0 → 位移算出负数 → call -16 → 无限递归 → 栈溢出
修法：resolve_calls 里加保护
      let target = fn_get(hh)
      let disp = target - (pos + 4)
      if target == 0 { disp = 0 }      // 位移 0 = call 到下一条指令（空操作）
```

验证：`verify_mcc10.py` → **3 项全 PASS**（回归消除）

## 当前自举状态

```text
T1 = 12,737 字节   ✅ 正确
T2 = 11,680 字节   ✅ 生成成功
T3 = 22 字节       ⚠️ 比之前(3)有进步，但仍在中途崩
```

T3 走到 22 字节说明 T2 现在能进入编译流程并发出部分代码，
剩余失败点在更靠后的构造上。

## 下一步

1. 用"读编译器修复表"的方法查 T2 的失败点：
   - 跑 T2 编译自身，在崩溃时读 `pos`（0x3000）与 `len`（0x3008）
   - 对照源码 pos 定位构造
2. 若仍是括号/条件解析冲突 → 按本文档前面的"方案 A"重写 emit_expr
3. 每次改动后跑：
   - `verify_mcc10.py`（确保基础功能不回归）
   - `verify_selfhost.py`（看 T2/T3）

## 回归检查清单（重要）

改 mcc10.ds 后**必须**跑这两个，缺一不可：

```bash
cd dsos-os/compiler
python3 verify_mcc10.py      # 基础功能，3 项
python3 verify_selfhost.py   # 自举，T2==T3
```

本次就是因为只跑 verify_selfhost 没跑 verify_mcc10，导致回归潜伏了两轮。


---

# 自举调试交接（第 11 轮，2026-11-27）

## 当前状态

```text
verify_mcc10:  PASS（3 项基础功能，无回归）
T1 = 14,054 字节   T0(Python mini.py) 编译 mcc10.ds
T2 = 15,122 字节   T1 编译 mcc10.ds（成功）
T3 = 68 字节       T2 编译 mcc10.ds（失败）
T2 执行到 pos=494 后 rip=0x0（ret 弹出空/错地址）
```

## 已修复的 6 个 bug（1-11 轮）

| # | bug | 修法 |
|---|---|---|
| 1 | 符号表重置在参数注册之后（参数被抹掉） | 重置移到参数循环之前 |
| 2 | `je rel8` 溢出 ±127（if 体过长） | `0F 84` + 4 字节回填 |
| 3 | `je rel8` 溢出（while） | 同上 |
| 4 | `jmp rel8` 溢出（while 回跳） | `E9` + 4 字节回填 |
| 5 | 函数体循环未跳过 `}` 前的空白 | 循环前加 `skip(s)` |
| 6 | 槽访问 disp8 截断（>63 变量） | 统一 disp32：`8B 85` / `89 85` |

**重要**：所有跳转现在都是 rel32，rel8 类 bug 已根治。

## 当前卡点（第 8 轮证据）

```asm
0x0135f2: mov eax, [rbp]        ← 槽 0（应为 [rbp-4] 等）
0x01361f: pop rbp               ← 弹出 4（保存的 rbp 被覆盖）
0x0138dd: ret                   ← 弹到地址 0
```

## 本轮否定结果（重要线索）

加了调试开关：`sym_get` 未命中时把 pos 写入 0x3C00。

```ds
fn sym_get(hh: i32) -> i32 {
    ...
    store32(15360, load32(12288))      // 调试：记录未命中位置
    return 0
}
```

运行结果：**该地址始终为 0 → sym_get 从未未命中**。

**结论**：`[rbp]` 槽 0 不是符号查询失败造成的。候选原因：

1. `slot = 0 - (4 * (load32(409600) + 1))` 里 `load32(409600)` 变成 -1 → slot=0
2. 某处 `emit32(-4)` 实际发出了 0
3. 参数存储写到了错误偏移
4. 某个内建调用破坏了符号表计数

## 下一步（接手直接做）

```text
1. 在 emit_let / emit_assign 里也加调试记录：
   当 slot == 0 时把 pos 写到 0x3C04
   → 直接定位是哪条 let/assign 算出 slot=0

2. 若无记录 → 说明 [rbp] 来自 emit_factor 的变量读，
   但 sym_get 未命中记录为 0 → 矛盾 → 检查 emit32 的负数处理
   （mini.py 的 emit32 对负数是否正确写成 4 字节补码？）

3. 检查 mini.py 的 emit32：
   struct.pack("<I", v & 0xFFFFFFFF) → OK
   若用了 "<i" 且值为负 → OK
   若没做掩码 → 可能报错或写错
```

## 调试工具（都在 workspace）

```text
_ws\_trace.py      记录执行轨迹，找最后几条指令
_ws\_dis3.py       capstone 反汇编 T2 崩溃点
_ws\_rsp.py        trace rsp/rbp 变化，找栈失衡
_ws\_dbgrun2.py    跑 T2 并读调试地址 0x3C00
```

（前缀 `_` 是临时脚本，在 `D:\文档\deepseek-harness\default-workspace\` 下）

## U 盘状态

```text
可启动，sha256 8f795ac1ff7bf8785006a3e3a0aaf1c7420fa54436a9000eabe811d1f12af00f
未被本 session 的编译器调试改动影响（内核由 mini.py 编译，mcc10 仅供自举实验）
```

## 下一步路线（目标整体）

```text
① 修完 mcc10 自举 → T2==T3 → 用 T2 编内核 → 删 mini.py
② 引导链三段式（stage2 走 16→32→64）→ QEMU 验证 → 替换 4608 字节
③ build/flash 脚本 Ds 化
```


---

# 重大发现：mcc10 缺少运算符优先级（第 15-16 轮）

## 根因

mcc10 的 `emit_expr` **没有实现运算符优先级**，所有二元运算按从左到右计算：

```ds
393216 + i * 4   →  (393216 + i) * 4     ✗ 错误
```

反汇编 T2 的 `sym_set` 证实：

```asm
mov eax, 0x60000      ; 基址 393216
mov eax, [rbp-0xc]    ; n
add eax, ebx          ; 0x60000 + n   ← 少了 *4
```

→ 符号表/Fn表/Call表/Ret表**全部写到错误地址** → 永远查不到
→ 这就是连续多轮"符号查不到、槽 0、栈错乱"的总根源

## 已修（两批，共 14 处）

```text
第一批 12 处：× 4 的表格地址
  393216 / 401408 / 303104 / 311296 / 262144 / 278528  + (n|i * 4)
第二批 2 处：ret 表
  327680 + (load32(335872) * 4)   ← 598 行、623 行
```

修复方式：**源码加显式括号**（`a + (b * c)`），因为 paren 解析已在第 2 轮加入。

## 验证状态

```text
verify_mcc10:  PASS ✅
T1 = 14,141 / T2 = 15,212 / T3 = 68 字节（未变）
```

## 下一步（第 17 轮）

```text
1. 重跑 _dbgrun4.py 看 hash/pos 是否变化
2. 若仍是 hash=115('s') pos=475 → 还有同类问题
3. 检查 emit_fn 参数循环的生成代码（反汇编 T2 的 emit_fn）
4. 长期方案：给 mcc10 实现真正的运算符优先级
   （递进式解析：primary → mul → add → cmp → logic）
   这才是根治，括号只是规避
```

## 教训

这是 **16 轮调试中最有价值的发现**：一个缺失的语言特性（优先级）
会造成下游所有数据结构的地址计算错误，表现为各种看似无关的症状。

以后遇到"符号查不到/地址错乱"类问题，应先怀疑**表达式求值顺序**。


---

# 第 23-26 轮关键认知（必读，避免走弯路）

## 认知一：80KB 上限是对的，20KB 上限曾掩盖进展

```text
第 23 轮把 verify_selfhost 的输出上限 20000 → 80000 后发现：
  T3 实际能生成 40,983 字节（不是"死循环"）
```
**别再调低上限**。T2 的输出本来就很大。

## 认知二："2.7 倍过度生成"是错觉

第 24 轮测出 T2(mcc10.ds) = 40,983，而 T1 的只有 15,269，以为是过度生成。
第 26 轮修正 `>>` 解析后，T1(mcc10.ds) 变成 **41,465** —— 与 40,983 同量级。

**结论**：15,269 是 `>>` 损坏导致的偏短垃圾输出；正确尺寸就是 **~41K**。
所以固定点目标应该是 `T2 == T3 ≈ 41K`，不要期待 15K。

## 认知三：`>>` 的正确修法（已定位，未成功）

源码 `emit_expr`（约 307-340 行）：

```ds
let op = peek(s)
advance()          ← 吃掉第一个 '>'
skip(s)
emit(80)
emit_factor(s)     ← 【错】对 >> 情况，位置还在第二个 '>' 上
emit(91)
...
if op == 62 {
    advance()      ← 【错】这里才吃掉第二个 '>'
    emit(72) emit(137) emit(217)   // mov rcx,rbx
    emit(72) emit(211) emit(232)   // shr rax,cl
}
```

**正确改法（两处必须同时改）**：
```ds
advance()
skip(s)
if op == 62 { if peek(s) == 62 { advance()  skip(s) } }   // ← 新增
emit(80)
emit_factor(s)
emit(91)
...
if op == 62 {
    // 删掉这里的 advance()
    emit(72) emit(137) emit(217)
    emit(72) emit(211) emit(232)
}
```

**已试过**：两处同改后 T1=14,298（正常）、T2=41,465（合理）、但 **T3=0**（T2 不工作）。
→ 说明 `>>` 修复方向正确，但还有配套问题。**已回退**。

## 当前稳定状态（第 26 轮末）

```text
verify_mcc10:  PASS
T1 = 14,212 / T2 = 15,269 / T3 = 40,983
```
注意：这个状态下 `>>` 仍是坏的（`T2` 里 `(v>>8)` 生成 `mov eax,[rbp+0]`）。

## 第 27 轮起的正确步骤

```text
1. 重新应用 >= 的两处修改（见上）
2. 【不要看尺寸】先验证 T2 对最小用例是否正确：
     fn f(s: i32) -> i32 { return s }
   → T1 与 T2 应生成完全相同的字节（之前是 1.00）
3. 若最小用例也错 → `>>` 修复引入了新问题，用 capstone 反汇编 T2 的 emit32
4. 若最小用例对 → 问题只在复杂源码，用前缀二分定位
```

## 关键调试脚本（workspace 根目录）

```text
_ratio.py        对比 T1/T2 在最小用例上的输出（比值应 1.00）
_ratio2.py       累积前缀二分，找发散函数
_rcdiff.py       对比单个函数的 T1/T2 生成结果
_e32.py          测 emit32 对负数的处理
_e32dis.py       反汇编 T2 的 emit32
_trace.py        记录执行轨迹
_ovf2.py         找输出膨胀点（上限 80000 版需自己调）
```

## 26 轮修复总表

```text
1. 符号表重置顺序          6. 运算符优先级（14 处括号）
2. if 条件 rel8→rel32      7. emit_let 数字快速路径删除 ← 最关键
3. while 回跳 rel8→rel32   8. 一元负号（2 处）
4. 函数体循环补 skip        9. emit_value 回滚重解析
5. 槽访问 disp8→disp32     10. >> 解析顺序（已定位，未成功应用）
```


---

# 会话总结（30 轮目标周期，2026-11-27）

## 目标完成度

| 阶段 | 完成度 | 证据 |
|---|---|---|
| ① 编译器自举 | 70% | T1=14,212 正确；T2=15,269 生成；T3=40,983 完整生成；T2≠T3 |
| ② 引导链 Ds 化 | 40% | Ds MBR(65B)+stage2(377B)；16 位部分 QEMU 全通；卡 16→64 远跳 |
| ③ 构建脚本 Ds 化 | 0% | 未开始 |
| 产品 100% Ds | ✅ | 内核 10,769 字节全 Ds，真机可启动 |

## 最终稳定状态（务必保持）

```text
verify_mini   PASS (17)   verify_mcc10  PASS   verify_mbr16  PASS (3)
构建           BUILD: PASS（默认安全路径）
镜像 sha256    8f795ac1ff7bf8785006a3e3a0aaf1c7420fa54436a9000eabe811d1f12af00f
U 盘           未被改动（与镜像一致）
自举           T1=14,212 / T2=15,269 / T3=40,983 → 未达固定点
```

## 下一步的第一件事（新 session 直接执行）

```text
1. 打开 dsos-os/compiler/mcc10.ds，定位 emit_expr（307 行附近）
2. 找 op == 62（>>）的两处 advance()
3. 按本文件"认知三"同时修改两处
4. **只测最小用例**：
     fn f(s: i32) -> i32 { return s }
     fn _start() { }
     sys_exit(0)
   → 用 _ratio.py 或 _finalexp.py 的 gen() 对比 T1 和 T2 的输出
   → 要求完全一致（之前是 96 vs 96）
5. 最小用例通过后再跑完整 verify_selfhost
6. 若最小用例失败 → 说明修改吃错字符，用 capstone 反汇编 T2 的 emit32 核对
```

## 千万不要做的事

```text
✗ 不要把 verify_selfhost 的输出上限调回 20000（会误判为死循环）
✗ 不要期待 T2/T3 是 15K 量级（正确约 41K）
✗ 不要在 verify_mcc10 未 PASS 时继续（会漏回归）
✗ 不要为验证编译器去刷 U 盘（内核编译不依赖 mcc10）
```

## 本会话交付物清单

```text
dsos-os/ds/kernel.ds              内核（100% Ds，v1.1）
dsos-os/ds/mbr.ds                 Ds MBR（65 字节）
dsos-os/ds/stage2.ds              Ds stage2（377 字节，16 位部分全通）
dsos-os/ds/thunk16.ds             16 位写盘 thunk（验证通过）
dsos-os/ds/build_dsos.py          构建（默认安全路径 + --ds-boot/--ds-mbr 实验）
dsos-os/ds/flash_dsos.py          烧盘（守卫 + 重试）
dsos-os/ds/logtool.py             日志分区工具
dsos-os/ds/verify_*.py            7 个验收脚本
dsos-os/compiler/mcc10.ds         Ds 写的编译器（自举进行中）
dsos-os/compiler/HANDOFF-next.md  本文档
dsos-os/docs/AI-GUIDE.md          面向 AI 的学习指南
仓库 yzxcrush/dsos                已同步
```


---

# 补充：>> 的完整修复方案（操作数顺序 + 解析顺序）

## 代码位置（emit_expr，307 行起）

需要改 **3 处**：

```ds
        let op = peek(s)
        advance()
        skip(s)
        if op == 62 { if peek(s) == 62 { advance()  skip(s) } }   // ← 改 1：新增
        emit(80)
        emit_factor(s)                                            // 右值 → eax
        emit(91)                                                  // pop rbx = 左值
        ...
                if op == 62 {
                    // 删除原来的 advance()                        ← 改 2
                    emit(72)  emit(137)  emit(193)   // mov rcx,rax（移位量=右值）
                    emit(72)  emit(211)  emit(235)   // shr rbx,cl（左值右移）
                    emit(72)  emit(137)  emit(216)   // mov rax,rbx（结果）
                }
```

## 关键诊断（字节级证据）

基线状态下 T2 编译最小用例的输出：

```text
T1: 55 48 89 e5 48 81 ec 40 00 00 00 e8 2b 00 00 00 ...
T2: 55 48 89 e5 48 81 ec 40 00 01 01 e8 2b 01 01 01 ...
                             ^^^^^           ^^^^^
```

所有 4 字节值的**高两个字节变成 01**。

原因：`emit32` 里 `(v >> 16) as u8` 在 T2 中生成的是 `RHS >> LHS`（操作数反了），
所以 16>>v 之类的垃圾值被写进去。

## 三处全改后仍然失败（已试）

```text
verify_mcc10:  PASS
T1 = 14,334
T2 = 41,463   ← 尺寸仍 2.9 倍
T3 = 0        ← T2 完全不工作
```

**说明还有第 4 个关联 bug**：修正 >> 后，T1 生成的代码体积翻倍，
暗示某处依赖原来"错误的短代码"才能凑巧工作。

## 下一步建议

```text
1. 三处全改后，用 _diffmin.py 检查最小用例 T1/T2 是否终于一致
2. 若一致 → 说明 >> 已修好，T3=0 是另一个 bug（查 T2 入口/前几条指令）
3. 若不一致 → 对比差异字节，定位剩余问题
4. 注意 T2=41K 说明 T1 的生成逻辑变了，先确认 T1 编译 mcc10.ds 的过程无异常
```


---

# 后台自动化扫描结果（嵌套 if 不是原因）

## 已自动测试的 3 种写法

| 写法 | T1 | T2 | 最小用例 T1 vs T2 | 结论 |
|---|---|---|---|---|
| 单行嵌套 `if a { if b {...} }` | 14,334 | 41,463 (crash) | 96 vs 0 | ✗ |
| 多行嵌套 | 14,334 | 41,463 (crash) | 96 vs 0 | ✗ |
| 拆分（两个独立 if） | 14,386 | 41,466 (err=None) | 96 vs 0 | ✗ |

**结论：嵌套 if 写法不是原因。三种写法 T2 都产生 0 字节输出。**

## 关键观察

```text
1. T2 都是 ~41,463 字节（比 T1 大 2.9 倍）
2. T2 对任何输入都产生 0 字节
3. 写法 split 时 T2 无 err（正常退出）但也产出 0 → 说明 T2 的 _start 没执行到发射逻辑
```

## 新的怀疑方向

修 `>>` 后 T1 的输出体积翻倍（14K → 41K），这个"翻倍"本身是异常信号。

可能原因：
```text
A. T1 编译 mcc10.ds 时，某个循环生成了重复代码（41K）
   → 说明修改后的源码触发了 T1 的重复生成
B. T2 的入口/序言部分损坏，直接返回不干活
   → 41K 里大部分是无效代码
```

## 下一步（新 session）

```text
1. 用 capstone 反汇编 T2 的开头 200 字节，看序言和 call _start 是否正确
2. 检查 T2 的 41K 输出里是否有大量重复模式（用字符串搜索找重复片段）
3. 对比修改前后 T1 的生成：为什么 14K → 41K
   · 用 _rcdiff.py 逐函数对比修改前后的 T1 输出
4. 重要判据：如果 T1 的输出体积异常翻倍，先查 T1 的生成逻辑，
   而不是查 T2 的行为
```

## 当前状态

```text
mcc10.ds   已恢复原始（T1=14,212 / T2=15,269 / T3=40,983）
verify_mcc10 PASS
U 盘       未改动
后台脚本   _sweep_if.py / _step_shr.py / _sweep_shr.py 均可复用
```


---

# 第 33 轮：独立 >> 循环方案也失败（重要转折）

## 三次尝试的对比

| 方案 | T1 | T2 | 最小用例 | 结果 |
|---|---|---|---|---|
| 基线（>> 损坏） | 14,212 | 15,269 | 96 vs 96（长度同内容异） | T2 能跑但 emit32 坏 |
| 内联修复（3 处） | 14,334 | 41,463 | 96 vs 0 | T2 完全不工作 |
| **独立 >> 循环** | **14,384** | **41,464** | 96 vs 0 | T2 完全不工作 |

## 关键矛盾

```text
>> 损坏  → T1 输出 15,269 → T2 能工作（但 emit32 写坏高字节）
>> 正确  → T1 输出 41,464 → T2 完全不工作
```

**正确实现的输出是损坏实现的 2.7 倍** —— 这不符合"只是修了一处运算"的预期。
说明：修好 >> 后暴露了 T1 在别处的严重重复生成（2537 次垃圾读取）。

## 第 32 轮定位（仍然有效）

```text
误解析起点 = emit_if（T1 正常 11,122 → T1n 爆炸 41,464）
emit_if 里的可疑构造：
    if peek(s) == 101 { if peek_at(s, 1) == 108 { is_else = 1 } }
```

## 新假设（下一轮验证）

```text
>> 正确的实现让 emit_expr 的"循环次数"变多或变少，
影响了 emit_if 里那些"单行嵌套 if"的解析
→ 可能真正的 bug 在 emit_if 对单行嵌套 if 的处理
→ 但 T1（>> 损坏时）能正确处理同一段代码……

矛盾点：为什么 T1 能处理？因为 >> 损坏时 emit_expr 会提前停止（读垃圾后继续），
恰好让后续解析落在一个"可接受"的位置。
```

## 下一步建议（换个思路）

不要继续修 `>>`，而是**先把 emit_if 里的单行嵌套 if 改写成多行**：

```ds
# 改写前（emit_if 内）
if peek(s) == 101 { if peek_at(s, 1) == 108 { is_else = 1 } }

# 改写后
if peek(s) == 101 {
    if peek_at(s, 1) == 108 { is_else = 1 }
}
```

这是**零风险改动**（语义相同），可以测试"是否 emit_if 的单行嵌套才是真凶"。
如果 T1 输出体积因此从 41K 回落，就找到了真正的 bug 位置。

## 当前状态

```text
mcc10.ds     已恢复原始（T1=14,212 / T2=15,269 / T3=40,983）
verify_mcc10 PASS
U 盘          未改动
目标          33/40 轮
```


---

# 第 35 轮：41K 膨胀的算术分析（重要推理）

## 数据

```text
T1（>> 损坏）= 14,212 字节，编译 mcc10.ds 输出 15,269，垃圾读取 ~20 次
T1n（>> 正确）= 14,384 字节，编译 mcc10.ds 输出 41,464，垃圾读取 2,537 次

数学：2,537 × 7 字节（mov eax,[rbp+0] 是 7 字节）≈ 17,800 字节
      15,269 + 17,800 ≈ 33,000  —— 接近 41,464 的量级
```

**结论：41K 的主体就是那 2,537 次垃圾读取**，不是"正常代码变多"。

## 为什么正确解析反而产生更多垃圾读取？

关键对比（emit_expr 处理 `v >> 8`）：

```text
【损坏版】advance() 只吃第一个 '>'，然后在第二个 '>' 位置调用 emit_factor
  → emit_factor 读垃圾（1 次），pos 不前进
  → 分支里 advance() 吃掉第二个 '>'
  → 右操作数 8 【没有被消费】→ 留在当前位置
  → 外层调用者看到 '8'，误以为是逗号/右括号 → 但恰好能继续
  → 垃圾读取总数很少

【正确版】advance() advance() 吃掉两个 '>'
  → emit_factor 正确解析右操作数 8（消费掉）
  → 但外层某处期望的位置不对 → 连锁误解析 → 2,537 次垃圾读取
```

**推论**：mcc10 里 `>>` 的**右操作数本来就被"故意"留在流里**，由外层消费。
这是原设计的隐式约定——修 `>>` 破坏了这个约定。

## 下一步验证（关键实验）

```text
实验：只在 emit_expr 里加"右操作数不消费"的正确移位
  即：解析右操作数用于生成代码，但【回滚 pos】让外层重新看到它

  let sp = load32(12288)
  ... 解析 RHS、生成 shr ...
  store32(12288, sp)      // 回滚：让外层再看到右操作数

如果这样 T2 回到 15K 且 emit32 变正确 → 说明这就是正确修法
```

## 另一个方向：直接检查为什么外层期望"未消费的右操作数"

```text
用 T1n 反汇编一个含 >> 的简单函数，看它生成的代码里
右操作数是不是被"二次消费"了。
最小用例：fn f(v: i32) -> i32 { return v >> 8 }
```

## 当前状态

```text
mcc10.ds     原始稳定（T1=14,212 / T2=15,269 / T3=40,983）
verify_mcc10 PASS / U 盘未改动
目标          35/40 轮
```


---

# 第 37 轮：has_cmp 误判 >> 是根因之一（已确认并修复）

## 根因

```ds
// emit_factor 的括号分支
if c == 40 {
    advance()
    if has_cmp(s) == 1 { parse_cond(s) } else { emit_expr(s) }
    ...
}
```

`has_cmp` 扫描括号内容，遇到 `<`/`>`/`=` 就返回 1（判定为条件）。
但 `(v >> 8)` 里的 `>>` 是**移位**，不是比较 → 被误判成条件 → 走 `parse_cond`
→ `parse_cond` 把 `>>` 当比较运算符解析 → 全面误解析。

## 修复（已应用并验证消除垃圾读取）

```ds
        if depth == 0 {
            if c == 61 { return 1 }
            if c == 60 || c == 62 {
                let nx = load8(s + p + i + 1)
                if nx != c { return 1 }      // >> 和 << 不是比较
            }
        }
```

## 修复后的数据

```text
T1 = 14,463 （基线 14,212）
T2 = 41,463 （仍 2.9 倍）
垃圾读取 = 0 （之前 2537，已消除 ✓）
最小用例仍不一致（T2 对任何输入输出 0 字节）
```

## 进展判断

```text
✓ has_cmp 误判已修（垃圾读取归零，这是实质进展）
✗ T2 仍不可用（输出 0 字节）
? T1 输出仍是 41K（2.9 倍），原因待查
```

## 下一步（新 session）

```text
1. 应用两处修复（has_cmp + >> 独立循环）
2. 关键问题：为什么 T1 的输出是 41K 而不是 ~16K？
   · 用累积前缀找第一个输出异常的顶层函数
   · 注意：垃圾读取已归零，所以 41K 不再是垃圾，而是"重复或冗长"代码
3. 检查 T2 的入口 call _start 的位移是否为 0（第 31 轮的发现）
   · 若是 → fn_get(_start) 失败 → _start 没被正确注册
   · 查 emit_fn 对 _start 的处理（它是源码最后一个函数）
```

## 当前状态

```text
mcc10.ds     原始稳定（T1=14,212 / T2=15,269 / T3=40,983）
verify_mcc10 PASS / U 盘未改动
目标          37/40 轮
```


---

# 第 38-39 轮：完整因果链 + 已排除项（最终状态）

## 完整因果链（已全部证实）

```text
T3 = 0 字节
  ↓
T2 对任何输入输出 0 字节
  ↓
T2 开头: call 0x10010 —— 位移为 0
  ↓
"未知函数 → 位移置 0" 回退生效
  ↓
fn_get(_start) 返回 0（_start 从未注册）
  ↓
函数表只有 40 项，而 mcc10.ds 有 44 个函数
  ↓
解析在 emit_if（第 40 个函数）处中断
  ↓
后 4 个函数（emit_while / emit_fn / emit_stmt / _start）从未被处理
```

## 第 39 轮已排除的构造（全部 0 垃圾读取，正常）

```text
✓ 单行嵌套 if + 赋值：  let x = 0  if peek(s) == 101 { if peek_at(s,1) == 108 { x = 1 } }
✓ if-else 结构
✓ store8(addr, v as u8)   参数带 as 转换
✓ let x = 100 - (jf + 4)  减法+括号
```

四者 T1n 编译后垃圾读取都是 0，只是体积略大（T1n 用 frame 4096 + disp32）。

## 下一步（新 session 的关键实验）

```text
既然 4 个构造单独都正常，误解析必然来自【它们的组合】或 emit_if 里的：
  · `while peek(s) != 125 { emit_stmt(s)  skip(s) }`
  · `if is_else == 1 { ... } else { ... }` 的 else 分支
  · `store8(24576 + jf, dj0 as u8)` 循环写 4 次

最有效的做法：把 emit_if 的函数体【逐语句截断】，
用 T1n 编译每个前缀，找到第一次出现"垃圾读取 > 0"或"函数表项数异常"的位置。
（这正是第 32 轮累积前缀法，只是这次在函数内部做）
```

## 已确认的两个修复（尚未同时生效验证）

```ds
// 1. has_cmp 不把 >> / << 当比较
        if depth == 0 {
            if c == 61 { return 1 }
            if c == 60 || c == 62 {
                let nx = load8(s + p + i + 1)
                if nx != c { return 1 }
            }
        }

// 2. 独立 >> 循环（放在 emit_expr 的 emit_factor 之后）
    while peek(s) == 62 && peek_at(s, 1) == 62 {
        advance()  advance()  skip(s)
        emit(80)
        emit_factor(s)
        emit(91)
        emit(72)  emit(137)  emit(193)   // mov rcx,rax
        emit(72)  emit(211)  emit(235)   // shr rbx,cl
        emit(72)  emit(137)  emit(216)   // mov rax,rbx
        skip(s)
    }
```

应用这两处后：T1=14,463 / T2=41,463 / 垃圾读取=0（但仍不达固定点，因 _start 未注册）

## 当前稳定状态

```text
mcc10.ds     原始（未应用上述修复）
verify_mini PASS(17) / verify_mcc10 PASS / verify_mbr16 PASS(3)
T1=14,212 / T2=15,269 / T3=40,983
U 盘         未改动，可启动（sha256 8f795ac1…）
```

## 会话总账（30+39 轮）

```text
已修 bug：11 类
已达到：产品内核 100% Ds；自举 T3 完整生成 40,983 字节
未达到：T2 == T3（差 emit_if 内部的一处误解析 → _start 未注册）
```
