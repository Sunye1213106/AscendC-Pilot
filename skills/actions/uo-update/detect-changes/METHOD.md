# 检测源码变更

## Goal

检测源码相对定稿 KB 的变更。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 使用 capability `source-reading`。
2. 只处理当前 Action 指定的 ID 或文件。
3. 按输出合同生成候选产物；证据不足保留 unresolved。

## Domain Decisions

- 本 Action 特有分类/闭合规则见关联 task prompt（若有）。

## Output

- 合同 id：`change-detect-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
