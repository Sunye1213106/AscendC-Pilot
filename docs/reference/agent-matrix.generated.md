# Agent 矩阵

本文件由 `agents/*.yaml` 生成，请不要手工编辑。

| Agent | 类型 | 角色 | 模式 | 可读范围 | 可写范围 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| `ascendc-pilot` | `llm` | `controller` | `primary` | `*` |  | `agents/ascendc-pilot.yaml` |
| `ce-reviewer` | `llm` | `readonly_reviewer` | `subagent` | `uo/**`, `ce/**`, +4 | `ce/review/**`, `runs/**/actions/code_review/**` | `agents/ce-reviewer.yaml` |
| `deterministic-tg-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `tg/**`, `uo/**`, +7 | `tg/**`, `runs/**`, +2 | `agents/deterministic-tg-engine.yaml` |
| `deterministic-uo-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `uo/**`, `../uo/**`, +3 | `uo/**`, `../uo/**`, +2 | `agents/deterministic-uo-engine.yaml` |
| `tg-closure-referee` | `llm` | `referee` | `subagent` | `tg/closure/**`, `uo/**`, +5 | `runs/**/actions/lemma_review/review.yaml`, `runs/**/actions/closure_audit/review.yaml` | `agents/tg-closure-referee.yaml` |
| `tg-init-audit` | `llm` | `referee` | `subagent` | `tg/**`, `uo/**`, +3 | `tg/init/audit_report.yaml`, `runs/**/actions/init_audit/**` | `agents/tg-init-audit.yaml` |
| `tg-lemma-producer` | `llm` | `producer` | `subagent` | `tg/closure/lemmas/leads.yaml`, `tg/closure/**`, +9 | `runs/**/actions/lemma_mine/parts/**`, `runs/**/actions/lemma_mine/scratch/**`, +1 | `agents/tg-lemma-producer.yaml` |
| `uo-gap-investigator` | `llm` | `readonly_analyst` | `subagent` | `uo/ir/unresolved.yaml`, `uo/ir/codemap_analyze_receipt.yaml`, +4 | `uo/ir/gap_investigation.yaml`, `runs/*/actions/investigate/parts/**`, +2 | `agents/uo-gap-investigator.yaml` |
| `uo-query` | `llm` | `readonly_analyst` | `subagent` | `uo/**`, `runs/**`, +3 |  | `agents/uo-query.yaml` |
