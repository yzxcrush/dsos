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
