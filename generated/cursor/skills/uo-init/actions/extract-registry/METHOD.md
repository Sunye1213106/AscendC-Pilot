# 抽取 Registry 竞价

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.extract_registry`（确定性）。

## Goal

从 host registry / 能力注册排出 tiling family 竞争顺序与 predicate。

## Domain Procedure

```text
acp run-action extract_registry --project <算子目录>
```

## Output

- `uo/tiling/families.yaml`（`ordered` / `pred_count`）
- 合同：`extract-registry-v1`
