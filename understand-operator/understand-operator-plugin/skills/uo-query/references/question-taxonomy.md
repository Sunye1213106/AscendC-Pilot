# Question Taxonomy for uo-query

先对用户问题分类，再决定读哪些 KB 文件。分类结果要在回答开头用一行写明，例如：`问题类型: host_tiling`。

## 类型一览

| type | 含义 | 典型问法 / 关键词 |
|---|---|---|
| `io_boundary` | 算子 IO、属性、文件边界、入口 | 输入/输出、必选、optional、dtype、layout、shape 约束、host/kernel 入口、哪些文件 |
| `host_tiling` | Host 侧 tiling 机制/变量、分流、family、tiling data、key 逻辑关系 | tiling、tiling 机制、变量、影响、tiling_key、family、F00x、branch、predicate、IsTnd、deterministic、sparse、dispatch、mutex、implies、合法组合、剪枝、合并、pruning、merging、input_realization |
| `compute_dataflow` | 计算步骤 / 数据搬运 | compute、dataflow、DataCopy、matmul、softmax、C00x、golden model |
| `golden_generation` | 未来 golden 生成所需语义 | golden、参考计算、公式、numerical、tolerance |
| `kernel_path` | Kernel 实现路径、pipeline、buffer/sync | kernel path、Kxxx、op_kernel、pipeline、sync、buffer、UB、L1 |
| `evidence_quality` | 证据冲突、置信度、质量门 | conflict、unknown、quality、置信度、缺证据 |
| `test_contract` | 测试生成契约（非真实测例） | TestGenerate、coverage obligation、accuracy hint、performance hint |
| `overview_route` | 总览、怎么读 KB | 概览、route、怎么看、从哪开始 |
| `mixed` | 跨多类 | 同时问 tiling + kernel 等 |

## 分类规则（按优先级）

1. 出现 `IsTndSwizzle` / `IsTnd` / `tiling_key` / `family` / `F00` / `branch` / `predicate` / `命中` → **`host_tiling`**
2. 出现 `K_TASK` / `K00` / `kernel path` / `op_kernel` / `buffer` / `sync` / `pipeline` → **`kernel_path`**
3. 出现 `golden` / `参考计算` / `tolerance` / `numerical` → **`golden_generation`**
4. 出现 `DataCopy` / `compute step` / `C00` → **`compute_dataflow`**
5. 出现 `必选输入` / `optional` / `输出` / `属性` / `layout` → **`io_boundary`**
6. 出现 `conflict` / `quality` / `置信度` → **`evidence_quality`**
7. 出现 `测例` / `TestGenerate` / `coverage obligation` → **`test_contract`**
8. 否则若问「整体/怎么读」→ **`overview_route`**
9. 多类关键词并存 → **`mixed`**

## 分类后的阅读顺序

1. 先读 `index.yaml`
2. overview 再读 `route.md`
3. 按 `kb-file-map.md` / `index.yaml.qa_routes` 打开对应文件
4. 不够再读「可选」；仍不够才 CBM / 源码
5. **禁止**默认读 `archive/`

## 示例

| 问题 | 分类 | 先读 |
|---|---|---|
| 哪种输入 shape 更容易命中 IsTndSwizzle | `host_tiling` | `index.yaml` → `tiling/index.yaml` → `key_space.yaml` / `families.yaml` |
| 主路径 kernel 做了哪些 matmul | `kernel_path` (+ compute) | `index.yaml` → `kernel/paths.yaml` + `flow/compute_graph.yaml` |
| 必选输入有哪些 | `io_boundary` | `index.yaml` → `operator.yaml` |
| 后续怎么生成 golden | `golden_generation` | `index.yaml` → `flow/golden_model.yaml` + `numerical_model.yaml` |
| TestGenerate 要覆盖什么 | `test_contract` | `index.yaml` → `test/contract.yaml` + `tiling/coverage_model.yaml` |
