# 分片语义 Producer

## Purpose

Map worker 只处理 assigned shard，写 part，不写 canonical IR。

## Method

1. 只读自己的 `batches/batch_NNN.yaml` 与引用源码窗。
2. 只写 `parts/part_{shard_id}.yaml` 与 `scratch/{shard_id}/**`。
3. Part 必须带 run_id / action_session_id / shard_id / task_ids / hashes。
4. Rework 时 resume 原 worker_session_id。

## Hard Constraints

- MUST NOT：读取其他 shard batch/part。
- MUST NOT：直接写 `uo/ir/semantic_patches.yaml` / `llm_tasks.yaml` / ledger。
- MUST NOT：执行 `acp finalize` / `next` / `advance`。
- MUST NOT：裁决 batch 外 task_id。
