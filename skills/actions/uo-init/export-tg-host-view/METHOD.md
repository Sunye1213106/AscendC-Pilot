# 导出 TG Host View 投影

> **acp 是真实 CLI。** 本 Action 走 uo_init.pilot_engines.export_tg_host_view。

## Goal

在 `export_kb` + `build_index` 之后，把 live HostIR 投影为 `ir/tg_host_view.yaml`，并写入 `source.graph_fingerprint`，供 TG/CE 查询。**不是**第二套语义权威。

## Domain Procedure

```text
acp run-action export_tg_host_view --project <算子目录>
```

前置：`ir/operator_graph.yaml` 与 `indexes/kb_graph.sqlite` 已存在。禁止把 `.probe_cache/fag_bundle.pkl` 当作生产输入。

成功标志：finalize ok: true，并满足本 Action 的 output contract；`source.graph_fingerprint` 与 operator_graph 一致。

## Output

- 仅写 Spec / ownership 声明路径。
- 本文件不得描述 Pilot advance、complete 或其他阶段。
