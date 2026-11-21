# spec/IR.md — HIR / CFG / lvalue 契约（最小后端设计）

> 目标：让 `dscc` 从"表达式求值器"变成"能编译内核的代码生成器"。
> 本轮**只定义**，不实现。实现顺序见 §7。

---

## 1. 为什么需要 IR

当前 `dscc` step4/5 是**直接遍历 AST 发指令**，因此：

- 遇到 `WhileStmt` / `Index` / `AssignStmt` 只能 `raise`（无对应生成逻辑）；
- 变量的生命周期只覆盖一个表达式，跨基本块就失效；
- 没有"地址"概念，`v[i] = x` 无从下手。

IR 的作用是把「语义」与「指令选择」解耦：AST → HIR → CFG（基本块 + 边）→ 指令选择。

## 2. HIR（高层 IR）

### 2.1 指令集（最小集）

```text
; 值
t0 = const  <i64>
t1 = global <sym>                 ; 取地址（全局/字符串）
t2 = param  <index>
t3 = binop  <op> t0, t1
t4 = unop   <op> t0
t5 = call   <fn> (t...)           ; 返回 rax
t6 = load   <ty> <lvalue>
     store  <ty> <lvalue>, t0
t7 = addr_of <lvalue>             ; 取地址（&x, arr+i）
t8 = cast   <ty> t0               ; 显式 as
```

### 2.2 语句

```text
  let   <sym> <ty> = t0
  assign <lvalue> = t0
  jump  <bb>
  br    t0, <bb_true>, <bb_false>
  ret   t0?
  eval  t0                          ; 丢弃值
```

### 2.3 lvalue 的三种形态（关键）

```text
LVar(sym)                 局部变量（栈槽或寄存器）
LGlobal(sym)              全局 / 字符串 / 常量表（.data/.rodata）
LDeref(addr_ty, t_addr)   内存解引用：*p、v[i]、s.f
```

**规则**：`v[i]` 不产生新指令，它 lower 成
`LDeref(ty=T, t_addr = addr_of(v) + i * sizeof(T))`；
`v[i] = x` lower 成 `store LDeref(...), x`。

这正是当前后端缺失的那一层：**地址是值，lvalue 是"可写的位置"**。

## 3. CFG（控制流图）

- 每个函数拆基本块；块内无分支，块尾必为 `jump/br/ret`。
- `while c { body }` 的 lower：

```text
  bb.cond:  t = <c>;  br t, bb.body, bb.exit
  bb.body:  <body>;        jump bb.cond      ← 回边
  bb.exit:  ...
```

- `for x in a..b`、`loop`、`break`/`continue` 在此基础上加跳转，不引入新机制。

## 4. 跨回边的 liveness（必须解决的一项）

`while` 引入**回边**后，循环里定义的变量在下一轮迭代可能被使用：

```text
bb.body:  i = i + 1        ← 下一轮 bb.cond 要用 i
          jump bb.cond
```

要求：
1. 循环体内被 `assign` 的变量，若在条件或后续迭代中被读，必须**跨块存活**；
2. 最简实现：**所有局部变量一律占栈槽**（§6），不依赖寄存器存活；
3. 寄存器分配阶段再做活跃区间分析，跨回边的变量自然落入"活跃"集合。

## 5. 指令选择（最小策略）

| HIR | x86_64 |
|---|---|
| `const` | `mov r, imm` |
| `param i` | 从 `rdi/rsi/rdx/rcx/r8/r9` 或栈读 |
| `binop add/sub/and/or/xor` | 对应 ALU 指令 |
| `binop mul` | `imul` |
| `binop div/mod` | `xor rdx,rdx; div`；有符号 `idiv` |
| `unop neg/not` | `neg` / `not` |
| `load ty lv` | 按 `ty` 宽度选 `mov al/ax/eax/rax` |
| `store ty lv, t` | 按宽度选 `mov [addr], …` |
| `addr_of LGlobal` | `lea r, [rip+sym]`（`bare` 可用绝对） |
| `br` | `test` + `jz/jnz` |
| `call` | SysV 调用序列（见 `ABI-v1.md` §3） |

## 6. 先栈槽，后寄存器（实现策略）

**第一版一律用栈槽**：

```text
每个局部变量 → [rbp - 8*k]
每个临时值  → 压栈 / 出栈
```

- 优点：正确性容易保证，循环/作用域/递归都能过；
- 缺点：慢、代码大（`bare` 镜像会明显变大）；
- **寄存器分配是第二阶段**：在固定点自举达成之后再做线性扫描，不影响语义。

> 这条策略是刻意的：先窄后宽。不要在正确处理之前追求性能。

## 7. 实现顺序（每步都要有可跑的 case）

| 步 | 内容 | 验收 case |
|---|---|---|
| 1 | HIR + `LVar` + `let`/`assign`/`binop` | 已有 `branch.ds` 仍能编 |
| 2 | CFG + `while`/`loop`/`break`/`continue` + 回边存活 | 循环求和 |
| 3 | `LGlobal` + `.rodata` 字符串 + `p("hi")` | 打印字符串 |
| 4 | `LDeref` + `v[i] = x` 地址计算 | 数组写入后读回 |
| 5 | `bare` profile + 入口 `_start` + `hlt` | **`alive.ds` 编出可上屏镜像** |
| 6 | 寄存器分配（可延后） | 同一套 case 仍全绿 |

## 8. 与 Python Stage-0 的关系

`dsos/shell/kernel.py`（Python 发射器）**冻结为 Stage-0 原型 / 行为 oracle**：

- 它的**输出行为**（屏幕、串口、退出码）是 Ds+ 实现的对照标准；
- 其**实现方式**（Python 发字节）不得再扩展、不得复用为 Ds+ 后端；
- 对照方式：同一份用例，Stage-0 与 Ds+ 产物行为必须一致（比对屏幕文本 / 退出码）。
