# 签发 gap=0 证书

## Goal

签发 gap=0 证书。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 跑 `closure_soundness` gate。
2. 写 `tg/closure/certificate.yaml`。
3. gap≠0 或健全失败则不得 ok。

## Domain Decisions

- 遵循已加载 Policy 与 Capability 硬限制。
- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。
- `R − D` 单独报 undeclared-key defect；范例：`examples/undeclared_keys.excerpt.csv`。

## Output

- 合同 id：`closure-certify-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
