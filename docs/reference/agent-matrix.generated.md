# Agent 矩阵

本文件由 `agents/*.yaml` 生成，请不要手工编辑。

| Agent | 类型 | 角色 | 模式 | 可读范围 | 可写范围 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| `ascendc-pilot` | `llm` | `controller` | `primary` | `pilot:*` |  | `agents/ascendc-pilot.yaml` |
| `ce-analyst` | `llm` | `producer` | `subagent` | `pilot:ce/intent/**`, `pilot:ce/impact/**`, +8 | `pilot:runs/**/actions/feature_decompose/parts/**`, `pilot:runs/**/actions/feature_decompose/scratch/**`, +4 | `agents/ce-analyst.yaml` |
| `ce-change-referee` | `llm` | `referee` | `subagent` | `pilot:ce/**`, `pilot:uo/**`, +6 | `pilot:ce/impact/audit_report.yaml`, `pilot:ce/verify/exclusion_review.yaml`, +1 | `agents/ce-change-referee.yaml` |
| `ce-reviewer` | `llm` | `readonly_reviewer` | `subagent` | `pilot:uo/**`, `pilot:ce/**`, +5 | `pilot:ce/review/**`, `pilot:ce/verify/code_review.yaml`, +2 | `agents/ce-reviewer.yaml` |
| `deterministic-ce-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:ce/**`, `pilot:uo/**`, +6 | `pilot:ce/**`, `pilot:runs/**`, +1 | `agents/deterministic-ce-engine.yaml` |
| `deterministic-tg-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:tg/**`, `pilot:uo/**`, +8 | `pilot:tg/**`, `pilot:runs/**`, +2 | `agents/deterministic-tg-engine.yaml` |
| `deterministic-uo-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:uo/**`, `pilot:runs/**`, +2 | `pilot:uo/**`, `pilot:runs/**/actions/**`, +1 | `agents/deterministic-uo-engine.yaml` |
| `tg-closure-referee` | `llm` | `referee` | `subagent` | `pilot:tg/closure/**`, `pilot:uo/**`, +4 | `pilot:runs/**/actions/lemma_review/review.yaml`, `pilot:runs/**/actions/closure_audit/review.yaml` | `agents/tg-closure-referee.yaml` |
| `tg-init-audit` | `llm` | `referee` | `subagent` | `pilot:tg/**`, `pilot:uo/**`, +3 | `pilot:tg/init/audit_report.yaml`, `pilot:runs/**/actions/init_audit/**` | `agents/tg-init-audit.yaml` |
| `tg-lemma-producer` | `llm` | `producer` | `subagent` | `pilot:tg/closure/lemmas/leads.yaml`, `pilot:tg/closure/**`, +8 | `pilot:runs/**/actions/lemma_mine/parts/**`, `pilot:runs/**/actions/lemma_mine/scratch/**`, +1 | `agents/tg-lemma-producer.yaml` |
| `uo-gap-investigator` | `llm` | `readonly_analyst` | `subagent` | `pilot:uo/ir/unresolved.yaml`, `pilot:uo/ir/codemap_analyze_receipt.yaml`, +4 | `pilot:uo/ir/gap_investigation.yaml`, `pilot:runs/*/actions/investigate/parts/**`, +2 | `agents/uo-gap-investigator.yaml` |
| `uo-query` | `llm` | `readonly_analyst` | `subagent` | `pilot:uo/**`, `pilot:runs/**`, +3 |  | `agents/uo-query.yaml` |
