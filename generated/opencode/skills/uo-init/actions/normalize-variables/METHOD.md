# 变量归一化

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.normalize_variables`（确定性）。

## Goal

流水线占位。变量域已在 `extract_host` → `extract_host_bundle` 内建好；本步只写 deferred receipt，满足阶段顺序。

## Domain Procedure

```text
acp run-action normalize_variables --project <算子目录>
```

## Output

- `uo/tiling/normalize_variables_receipt.yaml`（`deferred_to: export_kb`）
- 合同：`normalize-variables-v1`
