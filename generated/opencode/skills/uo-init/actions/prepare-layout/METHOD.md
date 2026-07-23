# 创建知识库目录

> **`acp` 是真实 CLI。** 本 Action 是确定性的：只允许 `acp run-action prepare_layout`。  
> 禁止手工 `mkdir`、禁止直调 `prepare_operator.py`、禁止跳过本步去做 scope。

## Goal

经 Pilot 包装创建 UO KB 目录布局（含 `manifest.yaml`）。

## Domain Procedure

```text
acp run-action prepare_layout --project <算子目录>
```

成功标志：`.ascendc-pilot/uo/manifest.yaml` 存在且 finalize `ok: true`。  
若缺失 → 不得进入 `scope_confirmation`。

## Output

- 合同 id：`kb-layout-v1`（要求 `uo/manifest.yaml`）
- 不得写声明外路径。

本文件不得描述 Pilot advance、complete 或其他阶段。
