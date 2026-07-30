# 应用 gap patch

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.apply_gap_patch`（确定性）。

## Goal

校验并合并 `resolve_gaps` 各 shard 的 parts（及可选 `uo/ir/gap_patch_proposal.yaml`）：

1. blocker_id 存在于 `unresolved.yaml`
2. classification 在封闭枚举内
3. `input_derived` 的 var_id/value 在 VariableModel 域内
4. evidence path:line + snippet 命中源码

合入 `uo/ir/gap_bindings.yaml` 后重跑派生：要求 **derived 不降** 且 **escalating 严格下降**，否则 rollback 标 rejected。

## Domain Procedure

```text
acp run-action apply_gap_patch --project <算子目录>
```

## Output

- `uo/ir/gap_bindings.yaml`、`uo/ir/gap_patch_receipt.yaml`
- 可能更新 `uo/ir/host_derivation.yaml`
- 合同：`gap-patch-v1`
