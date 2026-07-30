# 派生 TilingKey 字段

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.derive_key_fields`（确定性）。

## Goal

对每个 TilingKey 维度回溯 host 赋值 DAG，产出：

- `uo/ir/host_derivation.yaml` — status / value_expr / value_leaves / root_vars / undecided_guards
- `uo/tiling/key_derivations.yaml` — TG 消费契约视图
- `uo/ir/derive_key_fields_receipt.yaml` — 契约 `derive-key-fields-v1`

## Domain Procedure

```text
acp run-action derive_key_fields --project <算子目录>
```

成功标志：finalize ok；`host_derivation.yaml` 存在且字段数与 TPL 维一致（FAG arch35 为 19）。

## Hard Constraints

- MUST NOT：手工编辑 `uo/ir/host_derivation.yaml`
- MUST NOT：跳过本步直接 `resolve_gaps`（pipeline 禁止跳步）
- undecided guard 的闭合交给后续 `normalize_predicates` → `resolve_gaps`

## Output

- 合同：`derive-key-fields-v1`
- 写域：`uo/ir/**`、`uo/tiling/key_derivations.yaml`
