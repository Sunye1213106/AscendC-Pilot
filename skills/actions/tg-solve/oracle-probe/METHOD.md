# Oracle 可信度探测

## Goal

Oracle 可信度探测。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 使用 capability `tilingkey-closure`。
2. 检查 schema / ledger 可达性（完整 Host replay 依赖环境）。
3. 写出 `tg/closure/oracle_probe.yaml`。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`（含 `ORACLE.md`），勿在本文件复制。
- Schema 范例：`capabilities/tilingkey-closure/examples/log_protocol.excerpt.yaml`。

## Output

- 合同 id：`oracle-probe-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
