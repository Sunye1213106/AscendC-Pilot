# extract_plan — 结构抽取（领域方法）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` / `harness run-action` 给出的动作。  
> Agent 不得自行 advance；闭环由 Harness engine + gate 托管。

## Purpose

脚本只做事实发现与**分对象评分**；复杂语义交给受 Harness 约束的 LLM。  
**candidate 边不得假闭合**；Patch 只写 `semantic_resolution_ledger`，再确定性重建派生图。

**入口事实源唯一**：`ir/entrypoint_graph.yaml`。禁止 `roles.*.selected`。

## Harness engine 闭环（同一 extract 阶段内）

```text
detect_score_pre          # extract.pre_semantic：入口/注册/boundary
→ extract_plan / build    # extract.plan_and_graph：plan + host/kernel/tilingkey
→ detect_score_post       # extract.post_semantic：bridge/KEY/provenance（禁止提前跑）
→ apply_semantic_patch    # 写 ledger；仅此时 attempts += 1
→ rebuild_from_ledger     # 重建派生图
→ recheck_closure         # 不递增 attempts
```

Gate：`detect_score_pre` / `extract_plan_subagent` / `semantic_closure` / `detect_score_post`。  
blocking LLM 未清且预算未尽 → 不可 advance。

## Actions

### 1. pre_semantic：入口图 + 评分

- `resolve_entrypoints`：CBM（confirmed scope 硬边界；`op_name` 仅排序）+ 注册宏
- fluent：`IMPL_OP_OPTILING(Op).Tiling(Class)` → `source_verified`
- 启发式 `_link_*` → `candidate`，**不得**单独满足 closure
- engine：`detect_score_pre` → `ir/score_report_pre.yaml` + `ir/llm_tasks.yaml`

### 2. 评分 ≠ 严重级别

- 评分 + `required_evidence` → 能否 `source_verified` 自动接受
- 必要性（主链）独立决定 blocking / degraded / informational
- **低分主链缺口仍为 blocking**（`mark_missing` / `inspect_candidates`）
- per-type `score_profile`；禁止统一 0.85 当真值

### 3. LLM 有界裁决（任务合同）

- 仅裁决候选；禁 `invent_symbol` / `repo_wide_search`
- Patch 必须引用 `task_id` + candidate id；校验 snapshot / candidate hash
- 写入 `ir/semantic_resolution_ledger.yaml` → `rebuild_from_ledger`
- 验证来源：`source_verified` | `semantic_verified` | `candidate` | `rejected`

### 4. plan_and_graph + post_semantic

- `propose_extract_plan` / LLM plan / `apply_extract_plan` / `build_layered_kb`
- Writer/receiver 身份：`file_path|qn|class`（禁止短名唯一键）
- **仅 plan/host 存在后**才 `detect_score_post`（评 Bridge/KEY）

### 5. 分层完整性

- 每个 `input_derivable=true` KEY、verified TilingData、CSV determinant、主 extraction unit
- `operator_capabilities` 显式声明；禁止「没找到 KEY 就当简单算子」
- def-use：仅 verified 边证明 reachability；candidate/structurally_inferred 可展示不可证明

## Hard Constraints

- MUST NOT：恢复 `selected`；candidate 边闭合主链；patch 直改派生图
- MUST NOT：recheck/detect/gate 递增 attempts；算子特化正则
- MUST NOT：以 multi-schema 本身触发 LLM（仅绑定歧义）；以 `file_contains=op_name` 硬过滤闭包文件
- MUST：证据不足保留分级 unresolved；Agent 不得推进 Harness 完成态

## Stop Conditions

- verified-closed + 分层覆盖通过；或 blocking 已入账且 batch 预算耗尽 → fail / 显式 degradation
