# 抽取 TilingKey 绑定

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.extract_tiling_key`（确定性）。

## Goal

从上一步 `extract_host` 的 bundle 取出 binding，写出回执（**不重算**绑定）。

## Domain Procedure

```text
acp run-action extract_tiling_key --project <算子目录>
```

## Output

- `uo/tiling/key_bind_receipt.yaml`（`binding_count` / `bind_error`）
- 合同：`extract-tiling-key-v1`
