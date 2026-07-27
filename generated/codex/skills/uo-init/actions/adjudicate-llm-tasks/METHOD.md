# 裁决 llm_tasks → semantic_patches

## Goal

对 `ir/llm_tasks.yaml` 中 **open + blocking** 任务做边/缺口裁决，写出 `ir/semantic_patches.yaml`。  
本步是 producer；**不**写 ledger、**不**改派生图。后续由确定性 `apply_semantic_patch` 消化补丁。

## Domain Procedure

1. Pilot `run-action adjudicate_llm_tasks` 准备 Bundle 与 `task_prompt_stub`。
2. 派发 `uo-semantic-resolve`：只读 `llm_tasks`（及必要证据窗口），写出 `semantic_patches.yaml`。
3. 规则：
   - 每条 patch **必须**含 `candidate_set_hash`（从 `llm_tasks` 同 `task_id` **原样复制**；权威字段名，勿写 `patch_candidate_set_hash`）
   - 同步复制 `source_snapshot_hash`（若 task 上有）
   - 有候选且证据足够 → `accept_edge` / `choose_one`（只能选窗内 candidate id）
   - 空候选 / 证据不足 → **诚实** `mark_missing`（禁止假 ACCEPT、禁止 invent_symbol）
   - 不得夹带 `accepted_candidate_ids` 到 `mark_missing`
4. `acp run-action adjudicate_llm_tasks --finalize`（校验合同产物）。
5. 下一步：`acp next` → `apply_semantic_patch`（禁止跳过）。

## Output

- 合同 id：`semantic-patches-v1`
- `ir/semantic_patches.yaml`（`version` + `patches[]`，每项含 `task_id` / `candidate_set_hash` / `action` / candidate ids / `evidence`）

## Stop Conditions

- 每个 open blocking 任务都有一条对应 patch；或显式 needs_human（不得静默漏项）。
