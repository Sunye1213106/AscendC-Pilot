# 创建知识库目录

> **`acp` 是真实 CLI。** 本 Action 是确定性的：只允许 `acp run-action prepare_layout`。  
> 禁止手工 `mkdir`、禁止直调未在 Spec 注册的脚本、禁止跳过本步去做 scope。

## Goal

经 Pilot 包装完成 UO 布局初始化：

1. `op_spec.discover` 发现算子布局（opdef / host / kernel / tiling key header）
2. 重置 `.ascendc-pilot/uo/` 为合同骨架：只保留本 Action 声明的目录与占位文件
3. 为 OPTIONAL 层写入 `status: not_extracted` 占位
4. 写出 `manifest.yaml`、`operator.yaml`、`runs/<run_id>/scope/layout_receipt.yaml`

## Domain Procedure

```text
acp run-action prepare_layout --project <算子目录>
```

成功标志：

- `.ascendc-pilot/uo/manifest.yaml` 存在，`schema: kb_schema-v1`，`status: prepared`
- `.ascendc-pilot/uo/operator.yaml` 存在
- `runs/<run_id>/scope/layout_receipt.yaml` 校验通过
- `uo/` 顶层仅含合同允许的目录与文件（见下方 Output）
- 空壳目录 `ir/` `checks/` `indexes/` `cross_layer/` `review/` **不**在本步预创建（由后续 extract/export 按需创建）
- `.ascendc-pilot/{tg,ce}/` 不属于本 Action 写域

未达成 → 不得进入 `scope_scan` / `scope_confirm`。

## Output

- 合同 id：`kb-layout-v1`（要求 `uo/manifest.yaml`、`uo/operator.yaml`）
- 写域：`uo/**`
- prepare 后允许存在的 `uo/` 内容：
  - `manifest.yaml` / `operator.yaml`
  - `tiling/data_model.yaml`
  - `kernel/pipeline.yaml` / `kernel/resources.yaml`
  - `flow/golden_model.yaml` / `flow/numerical_model.yaml`
  - `summary/`
  - `runs/<run_id>/scope/`

本文件不得描述 Pilot advance、complete 或其他阶段。
