# 应用语义补丁 (ledger)

## Goal

校验 LLM patch（task open、candidate 窗、source/candidate hash）后写入 `semantic_resolution_ledger`；**不得**直接改写派生图。仅此时 `task_attempts` / `total_semantic_batches` 递增。

消化对象：`ir/llm_tasks.yaml` 中的 blocking 任务（含 `mark_missing`、`entrypoint_dispatch_bind`、`choose_edge` 等）。**不是** `extract_plan` 的职责。

## Domain Procedure

1. Pilot `run-action apply_semantic_patch`（ctx 含 patch）。
2. 拒绝越权符号 / 过期 hash / 窗外 candidate。
3. **空候选禁假闭合**（硬）：
   - `mark_missing` 或 `candidates=[]` 时，只允许 `mark_missing` / `inspect_candidates` / `reject_edge`
   - 禁止 `accept_edge` / `choose_one`（否则会把任意 edge id 升成 `semantic_verified`）
   - 诚实 `mark_missing` 不得夹带 `accepted_candidate_ids`
4. 随后应 `rebuild_from_ledger`（`mark_missing` 补丁不升级边；仅记 unresolved 账）。

## Output

- 合同 id：`semantic-patch-v1`
- `ir/semantic_resolution_ledger.yaml`
