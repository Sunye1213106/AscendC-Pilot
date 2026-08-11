# Action 临时工作区

## Purpose

临时计算写入 `runs/{run_id}/actions/{action_id}/scratch/**`，不污染正式 IR。

## Method

1. 只写本 Action scratch。
2. Map worker 只写 `scratch/{shard_id}/**`。
3. 正式结论仍写 staging/part，由 finalizer/reducer 提升。

## Hard Constraints

- MUST NOT：scratch 路径进入下游语义消费。
- MUST NOT：用 scratch 绕过 lease 写 `uo/ir/**`。
