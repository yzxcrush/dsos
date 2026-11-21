# bootstrap/SEED.md — 一次性 bootstrap seed

> 目标：DsOS 最终只由 **Ds+ 工具链**构建。运行时与发布链**不得**包含 C 或 Python。
> 允许**一次性** bootstrap seed；stage1 自举成功后，seed 退出发布链。

## 1. 决策：选项 B（预编译 Ds+ 编译器 seed）

| 选项 | 内容 | 结论 |
|---|---|---|
| A | 不允许 seed（必须自举起步） | ❌ 逻辑死结：用一个不存在的编译器编译它自己 |
| **B** | **预编译 Ds+ 编译器 seed** | ✅ **采用** |
| C | 手写最小机器码 seed，不用任何其他语言 | ⛔ 兜底，不采用（理由见 §3） |

## 2. 自举链（固定点定义）

```text
T0      当前 Python 参考实现（dsv01 + dsplus 前端 + 后端）  ← 仅 bootstrap 层，一次性
  │     编译「Ds+ 编译器源码」（compiler/*.ds）
  ▼
seed    预编译的 Ds+ 编译器二进制（归档，不再重建）
  │     编译 compiler/*.ds
  ▼
stage1  Ds+ 编译器（由 seed 产出）
  │     编译 compiler/*.ds
  ▼
stage2  Ds+ 编译器（由 stage1 产出）
  │     编译 compiler/*.ds
  ▼
stage3  Ds+ 编译器（由 stage2 产出）
```

**验收（唯一判据）**：

```text
stage2.out == stage3.out        逐字节相同
```

固定点成立之前，不得声称"自举完成"。

**退出条件**：固定点达成后
- T0（Python）从构建链删除；
- `bootstrap/` 只保留 seed 二进制 + 本文件；
- 发布产物与 `commit` / `seed SHA256` 一一对应。

## 3. 为什么不选 C（手写机器码 seed）

- 一个能编译 Ds+ 子集的编译器，手写机器码是**数万字节**量级；
- 手写字节没有类型检查、没有中间语言、没有可调试性——任何一处编码错误都只能靠反汇编定位；
- 它消除的"对 T0 的信任"，可以由 §4 的归档 + 可复现命令替代；
- 结论：**C 的风险远高于它带来的信任收益**，仅作为 B 完全不可行时的兜底。

## 4. Seed 归档要求（B 落地时必须齐备）

| 项 | 要求 | 当前状态 |
|---|---|---|
| seed 二进制 | `bootstrap/seed/dsplus-seed-<ver>.bin` | ⏳ 待生成 |
| SHA256 | 写入本文件 §5 | ⏳ 待填 |
| 来源说明 | 哪个 commit 的 T0、哪个 commit 的编译器源码、哪条命令 | ⏳ 待填 |
| 使用记录 | 每次用 seed 产出的 stageN 的哈希 | ⏳ 待填 |
| 可复现命令 | 重建 seed 的确切命令（供审计） | ⏳ 待填 |

> **当前 seed 尚不存在**，因为 T0 的后端只能编译 `+ - / if / sys_exit`
> （详见 `gap-report.md`）。在 T0 能编译编译器源码之前，本文件只记录**契约**，
> 不得把任何产物标注为"seed 已归档"。

## 5. Seed 记录表（待填）

```text
seed_file   : (TBD)
seed_sha256 : (TBD)
built_by    : T0 = dsv01 @ commit (TBD)
built_from  : compiler/*.ds @ commit (TBD)
build_cmd   : dsplus build compiler/main.ds --target linux -o bootstrap/seed/... (TBD)
```

## 6. 硬约束（违反即失败）

1. seed **只允许**用于生成 stage1；不得直接用于构建 DsOS。
2. stage1 自举成功后，构建链中不得再出现 `python` / `gcc` / `clang` / `nasm`。
3. `dsplus build` 是最终唯一入口：
   ```bash
   dsplus build kernel.ds --target bare -o dsos.img
   ```
4. 发布说明必须写明：产物 commit、seed SHA256、固定点日志位置。
