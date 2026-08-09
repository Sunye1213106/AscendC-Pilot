# 反例维替换解释

## Goal

把构造后 **REWRITE / REFUSE** 的结果整理成「要的→给的 / 拒绝原因」观测，供 lemma_leads 使用。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。

## Domain Procedure

1. 对 open target：构造（best-effort）→ 回放（或复用最近 judged 行）。
2. 汇总稳定替换维、拒绝码；附 `construct_reasons` 仅作 hypothesis 字段。
3. 写 `tg/closure/construct/explain_receipt.yaml`。
4. 不写 R/E；不把假设晋升为 lemma。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`，勿在本文件复制。

## Output

- 合同 id：`closure-explain-v1`
- 不得写声明外路径。

## Cannot Decide

- oracle 不可信 → ORACLE_SUSPECT，停止排除
- 证据不足 → unresolved / needs_human

本文件不得描述 Pilot advance、complete 或其他阶段。
