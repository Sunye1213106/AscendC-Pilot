# 应用语义补丁 (ledger)

## Goal

校验 LLM patch（task open、candidate 窗、source/candidate hash）后写入 `semantic_resolution_ledger`；**不得**直接改写派生图。仅此时 `task_attempts` / `total_semantic_batches` 递增。

## Domain Procedure

1. Pilot `run-action apply_semantic_patch`（ctx 含 patch）。
2. 拒绝越权符号 / 过期 hash / 窗外 candidate。
3. 随后应 `rebuild_from_ledger`。

## Output

- 合同 id：`semantic-patch-v1`
- `ir/semantic_resolution_ledger.yaml`
