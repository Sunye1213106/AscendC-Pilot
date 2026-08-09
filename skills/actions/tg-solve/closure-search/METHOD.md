# 定向搜索一轮

## Goal

定向搜索一轮。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 执行有界 `search_round.run_round`（fit→generate→progress）。
2. 写 `tg/closure/rounds/round_*/progress.yaml`。
3. 不在本 Action 内死循环；外环由 residual rework 驱动。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。
- Schema 范例：`capabilities/tilingkey-closure/examples/search_hints.excerpt.yaml`（结构可照抄，数值不可搬）。
- `feature_bindings` 的 `floor_terms` 见同目录 `feature_bindings.excerpt.yaml`。

## Output

- 合同 id：`closure-search-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
