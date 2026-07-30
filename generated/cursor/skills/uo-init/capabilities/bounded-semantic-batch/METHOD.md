# 有界语义批次

## Purpose

公共硬限制：每 shard ≤ 30 obligations，且不超过 token budget。

## Method

1. Host prepare 调用 `uo_init.blocker_shards.plan_blocker_shards`（`resolve_gaps`）或等价 Host 调度器。
2. 数量或 token 任一超限 → 继续拆分。
3. 任务数 > 30 却未分片 → `LLM_WORK_NOT_SHARDED`。
4. 单 shard 仍超限 → `LLM_SHARD_TOO_LARGE`。

## Hard Constraints

- MUST NOT：在 Action prompt 中实现分片。
- MUST NOT：把确定性可裁剪项送入 LLM。
- MUST NOT：恢复已删除的 `uo.scripts.llm_work_scheduler`；调度落在 `uo_init` / Pilot prepare。
