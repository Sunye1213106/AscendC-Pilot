# 应用语义补丁 (ledger)

## Goal

校验 LLM patch（task open、candidate 窗、source/candidate hash）后写入 `semantic_resolution_ledger`；**不得**直接改写派生图。仅此时 `task_attempts` / `total_semantic_batches` 递增。

消化对象：`ir/semantic_patches.yaml`（由 `adjudicate_llm_tasks` 产出）或对空候选任务的自动 `mark_missing`。  
**不是** `extract_plan` 的职责；本步是确定性引擎，**不做** LLM 边裁决。

## Domain Procedure

1. 先完成 `detect_score_post`；若 open blocking 需 LLM → 先 `adjudicate_llm_tasks` 写出 `semantic_patches.yaml`。
2. Pilot `run-action apply_semantic_patch`（读 `ir/semantic_patches.yaml`；无文件时仅对空候选 auto `mark_missing`；仍需 LLM 则失败并提示跑 adjudicate）。
3. 拒绝越权符号 / 过期 hash / 窗外 candidate。
4. **空候选禁假闭合**（硬）：
   - `mark_missing` 或 `candidates=[]` 时，只允许 `mark_missing` / `inspect_candidates` / `reject_edge`
   - 禁止 `accept_edge` / `choose_one`
   - 诚实 `mark_missing` 不得夹带 `accepted_candidate_ids`
5. 随后应 `acp next` → `rebuild_from_ledger`。

## Output

- 合同 id：`semantic-patch-v1`
- `ir/semantic_resolution_ledger.yaml`
