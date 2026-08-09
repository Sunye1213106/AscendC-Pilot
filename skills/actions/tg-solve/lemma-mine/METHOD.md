# 源码引理挖掘

## Goal

针对 leads 中「构造后未命中」的观测，从源码写出可审查的 staging 证明。

## Input Interpretation

仅处理 `acp next` 提供的当前 unresolved / target 子集与上下文包。  
每条 lead 应带：目标 key、构造 case、oracle 结果（REWRITE/REFUSE）、可选 `construct_reasons` 假设。

## Domain Procedure

1. 仅消费 leads 封闭包。
2. 对每条 lead：对照构造 case 走源码入口 → 解释拒绝或改写 → 按 LEMMA.md 路径 A/B/C 写 staging parts。
3. 调用 `lemma-evidence` 填空证据包 ID；证明五检查必须引用真实条目。
4. 禁止写 excluded；禁止虚构 lead；禁止把假设列表直接写成 `grade=source_lemma`。

## Domain Decisions

- 证据规则见 capability `tilingkey-closure`（`LEMMA.md` + `PROOF.md`），勿在本文件复制。
- 合格 `combo_evidence` 必须交代：源码定位、推理链、为何不被后续覆盖推翻、**与本条构造 case 的对应关系**。

## Output

- 合同 id：`lemma-mine-v1`
- 不得写声明外路径。

## Cannot Decide

- 回放显示其实可命中 / 与 R 冲突 → reject lead，回到 construct
- 证据不足 → unresolved / needs_human

本文件不得描述 Pilot advance、complete 或其他阶段。
