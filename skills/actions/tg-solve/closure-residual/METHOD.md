# 残差分析与路由

## Goal

残差分析与路由。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 调用 `residual.analyse` + `search_round.route`。
2. 写出 `tg/closure/route.yaml`（reason code）。
3. gap≠0 时由 Agent 执行 `acp rework --reason <code>`；GAP_ZERO 才 advance 到 audit。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。

## Output

- 合同 id：`closure-residual-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
