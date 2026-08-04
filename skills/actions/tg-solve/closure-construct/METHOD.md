# 构造式收尾

## Goal

构造式收尾。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 列出 distance-1 目标。
2. 写 `tg/closure/construct/targets.yaml`。
3. 完整 construct+replay 依赖 Host oracle。

## Domain Decisions

- 遵循已加载 Policy 与 Capability 硬限制。
- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。
- Schema 范例：`capabilities/tilingkey-closure/examples/construction_hints.excerpt.yaml`。

## Output

- 合同 id：`closure-construct-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
