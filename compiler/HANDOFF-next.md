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
