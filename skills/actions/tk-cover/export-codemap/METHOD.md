# 导出 HostIR codemap

> 确定性 Action：只允许 `acp run-action export_codemap`。

## Goal

推进 `tk-cover` 流水线本步；产物路径以 Spec / output_contract 为准。

## Domain Procedure

```text
acp run-action export_codemap --project <算子目录>
```

## Done When

对应 `uo/tk/*` receipt 写出且 output_contract 校验通过。
