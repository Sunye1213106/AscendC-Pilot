# key_resolution — KEY 语义闭合（仅处理 triage 分配目标）

> 本 Action 只处理 prepare 给出的 target_ids。禁止重做 triage 或扩 scope。

## Purpose

对 `key_triage` 分配的 KEY 批次做语义闭合，写出 `input_derivable_patch.yaml`。

## Inputs

- Pilot `dispatch_targets.target_ids`（有限集合）
- `ir/key_triage.yaml`（只读）

## Outputs

- `uo/ir/input_derivable_patch.yaml`（+ 可选 `key_shape_resolve/**`）

## Forbidden

- MUST NOT：改写 `key_triage.yaml`
- MUST NOT：处理 target_ids 之外的 KEY
- MUST NOT：为无证据 KEY 假标 high / accepted

## Procedure

1. 只处理 prepare 注入的 target_ids。
2. 证据不足保持 unresolved。
3. 写完 patch 后停止；后续 confidence/export 由其它 Action 负责。
