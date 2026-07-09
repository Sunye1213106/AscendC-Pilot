# Question Taxonomy for uo-query

先对用户问题分类，再决定读哪些 KB 文件。分类结果要在回答开头用一行写明，例如：`问题类型: host_tiling`。

## 类型一览

| type | 含义 | 典型问法 / 关键词 |
|---|---|---|
| `io_boundary` | 算子 IO、属性、文件边界、入口 | 输入/输出、必选、optional、dtype、layout、shape 约束、host/kernel 入口、哪些文件 |
| `host_tiling` | Host 侧 tiling 分流、谓词、family、tiling data | tiling、tiling_key、family、F00x、branch、predicate、IsTnd、IsTndSwizzle、deterministic、sparse、template、dispatch、GetWorkspaceSize、PostTiling、命中条件、哪种 shape |
| `compute_dataflow` | 计算步骤 / 数据搬运 / pipeline | compute、dataflow、DataCopy、SetFlag、WaitFlag、matmul、softmax、stage_pre/post、C00x |
| `kernel_path` | Kernel 实现路径、对齐、buffer/sync | kernel path、K_TASK、op_kernel、Init/Process、sync、buffer、UB、L1、对齐 |
| `evidence_quality` | 证据冲突、置信度、质量门 | conflict、unknown、quality gate、置信度、缺证据 |
| `testing_hints` | 精度/性能/覆盖测试设计提示 | golden、accuracy、performance、coverage、测例 |
| `overview_route` | 总览、怎么读 KB、从哪入手 | 概览、route、怎么看、从哪开始 |
| `mixed` | 跨多类 | 同时问 tiling 命中 + kernel 行为等 |

## 分类规则（按优先级）

1. 出现 `IsTndSwizzle` / `IsTnd` / `tiling_key` / `family` / `F00` / `branch` / `predicate` / `命中` / `shape 更容易` → **`host_tiling`**
2. 出现 `K_TASK` / `kernel path` / `op_kernel` / `buffer` / `sync` → **`kernel_path`**
3. 出现 `DataCopy` / `compute step` / `C00` / `pipeline` → **`compute_dataflow`**
4. 出现 `必选输入` / `optional` / `输出` / `属性` / `layout` → **`io_boundary`**
5. 出现 `conflict` / `quality` / `置信度` → **`evidence_quality`**
6. 出现 `测例` / `golden` / `精度标准` → **`testing_hints`**
7. 否则若问「整体/怎么读」→ **`overview_route`**
8. 多类关键词并存 → **`mixed`**，并列出主类型 + 次类型

## 分类后的阅读顺序

分类完成后：

1. 先读 `route.md` / `route.json` 的对应 Fast Task Routes / maps
2. 再按 `kb-file-map.md` 打开该类的「必读」文件
3. 不够再读「可选」；仍不够才 CBM / 源码

## 示例

| 问题 | 分类 | 先读 |
|---|---|---|
| 哪种输入 shape 更容易命中 IsTndSwizzle | `host_tiling` | `route.md` → `tiling/tiling_decision_tree.md` / `tiling_predicate_space.yaml` / `dispatch_variables.yaml` / `tiling_route.yaml` / `tiling_branch_families.yaml` |
| 主路径 kernel 做了哪些 matmul | `kernel_path` (+ 可带 `compute_dataflow`) | `route.md` → `kernel/paths/K_TASK_002_*.yaml` + `flows/compute_flow.yaml` |
| 必选输入有哪些 | `io_boundary` | `route.md` → `summary/operator_io.yaml` |
