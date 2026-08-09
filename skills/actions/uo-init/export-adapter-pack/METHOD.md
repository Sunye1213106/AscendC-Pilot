# 导出 TG adapter pack

> **acp 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.export_adapter_pack`。

## Goal

从 UO `host_derivation` / KB 导出冷启动所需的 adapter YAML（bridge / feature_bindings / search_hints / construction_hints），写入 `.ascendc-pilot/<arch>/uo/adapter/`，不污染 `operators/` 先验。

## Domain Procedure

```text
acp run-action export_adapter_pack --project <算子目录>
```

成功标志：finalize ok: true，且 `uo/adapter/` 下四份 YAML 存在；sampling grid 键均在 `input_semantics.knob_schema()` 内。

## Output

- 仅写 Spec / ownership 声明路径（`uo/adapter/**`）。
- 本文件不得描述 Pilot advance、complete 或其他阶段。
