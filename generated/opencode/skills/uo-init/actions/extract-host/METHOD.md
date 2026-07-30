# 抽取 Host IR

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.extract_host`（确定性）。须已 `scope_confirm`。

## Goal

对已确认范围内的 host 源码做 libclang 分析，构建内存 bundle：

- Host IR / 写点与控制流
- 可控性度量
- VariableModel
- TilingKey ↔ host 绑定（`tpl_bind`）
- 初版 gap / blockers

## Domain Procedure

```text
acp run-action extract_host --project <算子目录>
```

## Output

- `uo/ir/host_extract_receipt.yaml`（合同 `extract-host-v1`）
- 完整 IR 缓存在进程内，供后续 Action / export 使用
