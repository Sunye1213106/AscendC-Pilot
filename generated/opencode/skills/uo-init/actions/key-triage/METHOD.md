# key_triage — KEY 粗分（领域方法）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `key_triage` / `key_resolution`。

## Purpose

清空可抽样 unresolved，补全 input_derivable / KEY shape 语义，过置信度/integrity 门，导出单态图。

## Actions

### 1. LLM 残留 unresolved（任务 B）

- Prompt：`tpl_residual.md`
- 简单 FP 抽样 ≤12 → `ir/resolution_patch.yaml` → `apply_resolution.py --check` → apply
- 复杂 KEY → 写入 `escalate_keys`（交 `uo-key-resolve` triage→分流；建库期不派 `/uo-query`）

### 2. KEY triage + 按复杂度 resolve

- 条件：gaps open / confidence≠high / escalate_keys
- 先派 **一次** `tpl_key_triage` → `ir/key_triage.yaml`
- 再派 `tpl_key_resolve`：
  - **complex**（IsNzOut、分轴等）：一 KEY 一 Task
  - **simple**（empty_tensor、纯 regbase 等）：多 KEY 打包（≤6）
- 仅 `confidence: high` 可闭合；CBM = **MAY**（非主路径）
- 并行 cap 建议 8（Tasks，非「每 KEY 必一 agent」）

### 3. 脚本 classify

- `classify_input_derivable` → 更新 `ir/input_derivable.yaml` / gaps
- empty-only / 缺 triage·收据的 KEY patch → **拒收**（不写入闭合）

### 4. 置信度 + 原因裁判（运动员/裁判分离）

- 运动员 `uo-key-resolve`：非 high 项写满 `summary/confidence_report.md`「原因」
- `check_final_confidence` → `checks/confidence_gate.yaml`
- 若 `need_llm_count>0` / reported → 派 **`uo-confidence-review`**（`tpl_confidence_reason_review.md`）→ `review/confidence_reason_review.yaml`
- `harness validate-key-gates` → `checks/harness_key_gates.yaml`
- `harness advance export`（phase_gates 通过才可离开 resolve）
- fail → 回 KEY resolve 或补非同文报告后**再派裁判**；**禁止**跳过 triage / 直接 accepted / 父代理手写裁判 YAML

### 5. 导出 + integrity

- export graph / views → `check_kb_integrity`（内嵌 KEY 硬门禁）
- 最终：`harness complete`（唯一合法 pass）

## Hard Constraints

- MUST：先 triage 再分流；先 `--check` 再 apply resolution
- MUST：`escalate_keys` 非空或 gaps open → 必须产出 `ir/key_triage.yaml` 再 resolve
- MUST：非 high 有原因 + `uo-confidence-review` 裁判 pass
- MUST NOT：父代理用「直接 accepted」顶替 key-resolve
- MUST NOT：Agent 自行宣布 done（只认 `harness complete`）
- MUST NOT：默认每个 KEY 一个 subagent；把 complex 打进 batch
- MUST NOT：建库期派 `/uo-query` 做 KEY 闭合；用猜测清空 gaps
- MUST NOT：confidence_report 对全部 KEY 复制同一套 bit-pack 借口（Host 谓词可读则写 shape_expr / input_derivable）

### 5. 脚本导出 + 建图

- `kb_query_export.py --view testcase-contract` → `export_kb_graph.py` → `indexes/kb_graph.sqlite`
- 合法模板实例 = sqlite 中 `KTPL_*`（`fixes_flag`→`KEY_*`）；不写 `key_cards/**`，不物化笛卡尔 `template_blocks`

### 6. 脚本 integrity

- `check_kb_integrity.py` → `checks/integrity.yaml` 须 pass
- `reported` 时已报告 open gaps → warning（非死锁）；仍须通过 harness key gates

## Failure Handling

- 无法 high → `CONFIDENCE_REPORTED`（且须通过 report quality / closed_high 规则）
- integrity fail → `VALIDATION_FAILURE`
- 子代理不可 resume → `SUBAGENT_RESUME_UNAVAILABLE`
- key gates fail → `KEY_GATE_FAILURE`
