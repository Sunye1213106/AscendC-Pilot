# 重建 R 账本

## Goal

重建 R 账本。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 调用 `ledger.rebuild` 重建 R/open。
2. 按需 `lemma.apply_rules` 刷新 E（不引入未审规则）。
3. 产物落在 `tg/closure/`。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。

## Output

- 合同 id：`closure-ledger-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
