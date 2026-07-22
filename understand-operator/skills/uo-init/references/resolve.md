# Resolve（uo-init Phase 2）

## Purpose

清空可抽样 unresolved，补全 input_derivable 断边，过置信度/integrity 门，导出单态图。

## Entry / Exit

| | |
|---|---|
| Entry | Phase1 Extract 完成 |
| Exit | unresolved 无开放项；`confidence_gate` ∈ {pass, reported}；`integrity` pass |

人读 Step 明细：`docs/uo-init-workflow.md` Phase 2。  
相关：`references/confidence-gate.md` · `references/uo-input-derivable-resolve.md`。

## Actions

### 1. LLM 残留 unresolved（任务 B）

- Prompt：`tpl_residual.md`
- 简单 FP 抽样 ≤12 → `ir/resolution_patch.yaml` → `apply_resolution.py --check` → apply
- 复杂 KEY → 写入 `escalate_keys`（建库期仍走任务 E，**不**派 `/uo-query`）

### 2. LLM 断边（任务 E）

- 条件：gaps open / confidence≠high / escalate_keys
- Prompt：`tpl_input_derivable.md`；仅 `confidence: high` 可闭合
- cap 8；证据：CBM + path:line

### 3. 脚本 classify

- `classify_input_derivable` → 更新 `ir/input_derivable.yaml` / gaps

### 4. 脚本置信度门禁

- `check_final_confidence` → `checks/confidence_gate.yaml`
- fail → 回任务 E 或写满 `summary/confidence_report.md`
- MUST NOT：伪标 high

### 5. 脚本导出 + 建图

- `kb_query_export.py --view testcase-contract` → `export_kb_graph.py` → `indexes/kb_graph.sqlite`
- 合法模板实例 = sqlite 中 `KTPL_*`（`fixes_flag`→`KEY_*`）；不写 `key_cards/**`，不物化笛卡尔 `template_blocks`

### 6. 脚本 integrity

- `check_kb_integrity.py` → `checks/integrity.yaml` 须 pass
- `reported` 时已报告 open gaps → warning（非死锁）

## Hard Constraints

- MUST：先 `--check` 再 apply resolution
- MUST NOT：建库期派 `/uo-query`；用猜测清空 gaps

## Failure Handling

- 无法 high → `CONFIDENCE_REPORTED`
- integrity fail → `VALIDATION_FAILURE`
- 子代理不可 resume → `SUBAGENT_RESUME_UNAVAILABLE`
