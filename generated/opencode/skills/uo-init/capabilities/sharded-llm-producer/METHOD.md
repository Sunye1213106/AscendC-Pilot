# 分片 LLM Producer

## Purpose

Map worker 只处理本 shard；分片算法与全局计数在 Host/Runtime，不在 Prompt。

## Method

1. 只读本 `batch_*.yaml` 与本 part（rework）。
2. 逐项裁决，写本 `part_*.yaml`。
3. 运行 shard validator（`acp inspect` / producer-self-check）。
4. 停止；禁止 finalize / next / advance。

## Hard Constraints

- MUST NOT：读取完整 worklist / 完整 candidates / 其他 batch / 其他 part。
- MUST NOT：写 canonical `uo/ir/**` 或总 `semantic_relations.yaml` / `semantic_patches.yaml` / 旧 `decision_report.yaml`。
- MUST NOT：在 prompt 或手工实现分片算法 / 全局计数。
