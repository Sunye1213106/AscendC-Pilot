# 有界语义批次

## Purpose

公共硬限制：每 shard ≤ 30 obligations，且不超过 token budget。用于 Host 对 map-reduce 子代理任务的分片（例如 lemma 挖掘），**不是** `/uo-init` 的缺口补齐步骤。

## Method

1. Host prepare 在 Action 声明为 map-reduce 时调用分片调度器（如 `uo_init.blocker_shards.plan_blocker_shards`）。
2. 数量或 token 任一超限 → 继续拆分。
3. 任务数 > 30 却未分片 → `LLM_WORK_NOT_SHARDED`。
4. 单 shard 仍超限 → `LLM_SHARD_TOO_LARGE`。

`/uo-init` 不再调用 `resolve_gaps`。图上未闭合项保留在 `unresolved.yaml`，调查走 `/uo-investigate`。

## Hard Constraints

- MUST NOT：在 Action prompt 中实现分片。
- MUST NOT：把确定性可裁剪项送入 LLM。
- MUST NOT：恢复已删除的 `uo.scripts.llm_work_scheduler`；调度落在 Host prepare。
