# 源码引理挖掘

## Goal

源码引理挖掘。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 仅消费 leads 封闭包。
2. 按 LEMMA.md 路径 A/B/C 写 staging parts。
3. 禁止写 excluded；禁止虚构 lead。

## Domain Decisions

- 遵循已加载 Policy 与 Capability 硬限制。
- 证据规则见 capability `tilingkey-closure`（`LEMMA.md` + `PROOF.md`），勿在本文件复制。
- 合格 `combo_evidence` 必须交代源码定位、推理链、为何不被后续覆盖推翻。

## Output

- 合同 id：`lemma-mine-v1`
- 不得写声明外路径。

## Cannot Decide

- 证据不足 → unresolved / needs_human
- 缺工具或 gate 前置 → 停止并回报 blocking reason

本文件不得描述 Pilot advance、complete 或其他阶段。
