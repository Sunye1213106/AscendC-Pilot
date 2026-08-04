# 应用已审引理到 E

## Goal

应用已审引理到 E。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 仅应用已审 / 健全规则。
2. 反例时 revoke 并重算 E。
3. 刷新 excluded / open。

## Domain Decisions

- 遵循已加载 Policy 与 Capability 硬限制。
- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。

## Output

- 合同 id：`lemma-apply-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
