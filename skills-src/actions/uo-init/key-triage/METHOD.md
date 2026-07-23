# key_triage — KEY 粗分（领域方法）

> 勿在本文件推进 Harness 阶段；只执行 `harness next` 给出的 `key_triage` / `key_resolution`。

## Purpose

清空可抽样 unresolved，补全 input_derivable / KEY shape 语义，过置信度/integrity 门，导出单态图。

## Actions

### 1. LLM 残留 unresolved（任务 B）

- Prompt：`tpl_residual.md`
- 简单 FP 抽样 ≤12 → 写 `ir/resolution_patch.yaml`；由后续确定性 Action / 引擎 apply（**禁止**直调 `apply_resolution.py`）
- 复杂 KEY → 写入 `escalate_keys`（交 `uo-key-resolve` triage→分流；建库期不派 `/uo-query`）

### 2. KEY triage + 按复杂度 resolve

- 条件：gaps open / confidence≠high / escalate_keys
- 先派 **一次** `tpl_key_triage` → `ir/key_triage.yaml`
- 再派 `tpl_key_resolve`：
  - **complex**（IsNzOut、分轴等）：一 KEY 一 Task
  - **simple**（empty_tensor、纯 regbase 等）：多 KEY 打包（≤6）
- 仅 `confidence: high` 可闭合；CBM = **MAY**（非主路径）
- 并行 cap 建议 8（Tasks，非「每 KEY 必一 agent」）

### 3. 确定性 classify（Harness 引擎，勿直调 .py）

- 由后续 `confidence_report` / resolve 相关 deterministic Action 调用 `classify_input_derivable`
- Agent **禁止** `python …/classify_input_derivable.py`

### 4. 置信度 + 原因裁判（运动员/裁判分离）

- 运动员 `uo-key-resolve`：非 high 项写满 patch 原因字段
- `harness run-action confidence_report` → `checks/confidence_gate.yaml`（勿直调 `check_final_confidence.py`）
- 若 `need_llm_count>0` / reported → 派 **`uo-confidence-review`**
- `harness validate-key-gates`
- `harness advance export`（phase_gates 通过才可离开 resolve）
- fail → 回 KEY resolve；**禁止**跳过 triage / 直接 accepted / 父代理手写裁判 YAML

### 5. 导出 + integrity

- `harness run-action export_integrity`（内嵌 KEY 硬门禁 / 建图）
- 最终：`harness complete`（唯一合法 pass）

## Hard Constraints

- MUST：先 triage 再分流；先 `--check` 再 apply resolution（经 Harness/引擎，勿直调 `apply_resolution.py`）
- MUST：`escalate_keys` 非空或 gaps open → 必须产出 `ir/key_triage.yaml` 再 resolve
- MUST：非 high 有原因 + `uo-confidence-review` 裁判 pass
- MUST NOT：父代理用「直接 accepted」顶替 key-resolve
- MUST NOT：Agent 自行宣布 done（只认 `harness complete`）
- MUST NOT：默认每个 KEY 一个 subagent；把 complex 打进 batch
- MUST NOT：建库期派 `/uo-query` 做 KEY 闭合；用猜测清空 gaps
- MUST NOT：confidence_report 对全部 KEY 复制同一套 bit-pack 借口
- MUST NOT：直调 `classify_*.py` / `check_final_confidence.py` / `kb_query_export.py` / `export_kb_graph.py` / `check_kb_integrity.py`

## Failure Handling

- 无法 high → `CONFIDENCE_REPORTED`（且须通过 report quality / closed_high 规则）
- integrity fail → `VALIDATION_FAILURE`
- 子代理不可 resume → `SUBAGENT_RESUME_UNAVAILABLE`
- key gates fail → `KEY_GATE_FAILURE`
