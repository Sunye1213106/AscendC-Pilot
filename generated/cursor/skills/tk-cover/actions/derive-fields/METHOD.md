# 读取宿主派生

> 确定性 Action：只允许 `acp run-action derive_fields`。

## Goal

推进 `tk-cover` 流水线本步；产物路径以 Spec / output_contract 为准。

## Domain Procedure

```text
acp run-action derive_fields --project <算子目录>
```

## Done When

对应 `uo/tk/*` receipt 写出且 output_contract 校验通过。
