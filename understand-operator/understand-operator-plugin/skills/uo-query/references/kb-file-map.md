# KB File Map

KB 根目录形态：

```text
<repo>/.understand-operator/<op_name>/
  route.md                 # 总路由地图（问答入口，必读）
  route.json               # 机器可读路由
  quality_gate.yaml        # 质量门 green/yellow/red
  cbm/                     # 索引与查询审计
  summary/                 # IO / 边界 / 进度
  tiling/                  # host tiling 分流
  flows/                   # compute + dataflow
  kernel/                  # kernel task / path / sync
  evidence/                # 一致性与冲突
  testing_hints/           # 测试设计提示（非真实测例）
```

下面「存什么」按真实完整 KB（如 `flash_attention_score_grad`）归纳。

## 总览 / 路由

| 文件 | 存什么 | 何时读 |
|---|---|---|
| `route.md` | Status、IO 摘要、Fast Task Routes、Family↔Kernel 图、Compute↔Path 图、Input↔Family、Hot Risks、Suggested Next Read | **任何问题先读** |
| `route.json` | 同上的结构化版本（kernel_tasks、conflicts、suggested_next_read） | 需要精确 id / 程序化跳转 |
| `quality_gate.yaml` | 整体是否可依赖 | 回答前看置信度 |
| `summary/overview.md` | 算子文字总览 | overview 类问题 |

## summary/ — IO 与边界（`io_boundary`）

| 文件 | 存什么 |
|---|---|
| `operator_io.yaml` | required/optional inputs、outputs、attributes、dtype/shape/layout 约束 |
| `operator_boundary.md` | host/tiling/kernel/golden/test 文件边界与职责 |
| `operator_manifest.yaml` | 入口符号、源文件清单、confidence |
| `analysis_plan.yaml` | 后续分析计划、open questions、source_hints |
| `ontology.yaml` | 术语/实体关系 |
| `macro_scope_review.yaml` | 探索范围审阅决策 |
| `workflow_progress.yaml` | 流水线进度 |
| `ignore_rules.md` | 忽略规则 |

## tiling/ — Host tiling（`host_tiling`）

| 文件 | 存什么 |
|---|---|
| `tiling_decision_tree.md` | 可读的 tiling 决策树 / 模板参数 / GetWorkspaceSize 等逻辑摘要 |
| `tiling_frontier.yaml` | tiling 代码前沿：关键函数、文件、入口 |
| `dispatch_variables.yaml` | 驱动分流的变量类别与代表名（含 IsTndSwizzle 等） |
| `tiling_predicate_space.yaml` | 规范化谓词原子（平台/dtype/deterministic/TND…） |
| `tiling_branch_families.yaml` | **主产物**：family 分组、谓词、结构签名、代表 case |
| `tiling_route.yaml` | family → normal/needs_review/excluded 路由 |
| `branch_matrix.yaml` | 代表 branch 样本表（非全量枚举） |
| `tiling_key.yaml` | tiling key / 模板描述 |
| `tiling_data_signature.yaml` | tiling data 字段签名 |
| `tiling_data_map.yaml` | tiling data 字段映射 |
| `kernel_evidence_backfill.yaml` | 从 kernel 回填的 tiling 修正 |

问「哪种 shape 命中某 flag」时优先：

1. `route.md`（Input/Family、Hot Risks）
2. `tiling/dispatch_variables.yaml` + `tiling_predicate_space.yaml`
3. `tiling/tiling_decision_tree.md` + `tiling_route.yaml`
4. `tiling/tiling_branch_families.yaml` + `branch_matrix.yaml`

## flows/ — 计算与搬运（`compute_dataflow`）

| 文件 | 存什么 |
|---|---|
| `compute_flow.yaml` / `.md` | 规范计算步骤（如 C001–C018）、依赖与语义 |
| `dataflow.yaml` / `.md` | 数据搬运、pipeline、同步相关数据面 |

## kernel/ — Kernel 路径（`kernel_path`）

| 文件 | 存什么 |
|---|---|
| `kernel_task_plan.yaml` | family→task 规划、entry hints、dispatchable |
| `kernel_dispatch_review.yaml` | 人工分发决策与 approved_task_ids |
| `kernel_path_matrix.yaml` | path 对齐矩阵 |
| `sync_buffer_map.yaml` | buffer / sync 事件图 |
| `paths/Kxxx_kernel_path.yaml` | 单条 kernel path：入口、对齐 IO/tiling/compute、细节 |

## evidence/ — 证据质量（`evidence_quality`）

| 文件 | 存什么 |
|---|---|
| `evidence_check.yaml` | 检查项状态 |
| `consistency_report.md` | 一致性文字报告 |
| `missing_items.yaml` | 缺失项 |
| `conflict_items.yaml` | 冲突项 |
| `confidence_report.yaml` | 分项置信度 |

## testing_hints/ — 测试提示（`testing_hints`）

| 文件 | 存什么 |
|---|---|
| `golden_hint.yaml` | golden 设计提示 |
| `accuracy_case_hint.yaml` | 精度测例提示 |
| `performance_case_hint.yaml` | 性能测例提示 |
| `coverage_hint.yaml` | 覆盖提示 |

**注意**：这里是 hints，不是可执行测试。

## cbm/

| 文件 | 存什么 |
|---|---|
| `index_meta.json` | CBM 项目/索引元数据 |
| `cbm_query_log.md` | Phase 0 索引日志 |
| `query_journal.jsonl` | 按需查询审计 |

## 用 route 跳转（推荐）

`route.md` 的 Fast Task Routes / Family→Kernel / Suggested Next Read 就是官方跳转表。  
分类后优先跟 route 指的路径，再下钻具体 yaml/md。
