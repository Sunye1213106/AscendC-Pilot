# 确认 TG 模式意图

## Goal

写入 `tg/init/init_intent.yaml`，声明默认 `tilingkey_full_coverage` 或 `csv_consumer`。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 读取上下文 / 参数中的 mode 提示；缺省为 `tilingkey_full_coverage`。
2. 写出意图产物，供后续 contract / plan / solve 分流。
3. 全量模式下不强制 CSV consumer root。

## Domain Decisions

- 遵循已加载 Policy 与 Capability 硬限制。

## Output

- 合同 id：`tg-init-intent-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
