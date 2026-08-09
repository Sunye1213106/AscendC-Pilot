# 导出与完整性校验

## Goal

导出并做完整性校验。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 按确定性引擎 / Pilot 包装命令执行。
1. 只处理当前 Action 指定的 ID 或文件。
2. 按输出合同生成候选产物；证据不足保留 unresolved。

## Domain Decisions

- 本 Action 特有分类/闭合规则见关联 task prompt（若有）。

## Output

- 合同 id：`integrity-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
