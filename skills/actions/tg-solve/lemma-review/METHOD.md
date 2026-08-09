# lemma_review

## Goal

完成本 Action 声明的有界语义任务。

## Domain

遵循 `skills/domain/source-lemma-proof/SKILL.md`。

必读 `references/referee-replay.md`；只 replay 证书。

## Input

仅处理 Bundle / Task Prompt 提供的 targets 与上下文。

## Output

- 合同 id：`lemma-review-v1`
- 只写声明路径。

## Cannot Decide

证据不足 → unresolved / needs_human；勿猜测。

本文件不得描述 Pilot advance、complete 或其他阶段。
