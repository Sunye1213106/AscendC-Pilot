# 导出 TG Host View

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.export_tg_host_view`（确定性）。

## Goal

在 KB 已导出之后，写出 TG/CE 搜索投影：

- `uo/ir/tg_host_view.yaml` — fields/writers/reads/predicates/declared_keys/platform_gates
- `source.graph_fingerprint` 必须与 `operator_graph` 对齐

## Domain Procedure

```text
acp run-action export_tg_host_view --project <算子目录>
```

成功标志：finalize ok；`tg_host_view.yaml` 存在且含非空 `fields`。

## Hard Constraints

- MUST NOT：手工编辑 `tg_host_view.yaml`
- MUST NOT：在 `export_kb` / `build_index` 之前跑本步
- MUST NOT：默认写出完整 `value_expr` / `expanded`
- MUST NOT：再写权威副本到 `host_codemap.yaml`（旧文件只读兼容）

## Output

- 合同：`export-tg-host-view-v1`
- 写域：`uo/ir/tg_host_view.yaml`、`uo/indexes/kb_graph.sqlite`（VIEW/表）、receipt
