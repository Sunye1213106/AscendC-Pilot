# Agent 矩阵

本文件由 `agents/*.yaml` 生成，请不要手工编辑。

| Agent | 类型 | 角色 | 模式 | 可读范围 | 可写范围 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| `ascendc-pilot` | `llm` | `controller` | `primary` | `pilot:*` |  | `agents/ascendc-pilot.yaml` |
| `ce-analyst` | `llm` | `producer` | `subagent` | `pilot:ce/intent/**`, `pilot:ce/impact/**`, +10 | `pilot:runs/**/actions/feature_decompose/parts/**`, `pilot:runs/**/actions/feature_decompose/scratch/**`, +8 | `agents/ce-analyst.yaml` |
| `ce-applier` | `llm` | `producer` | `subagent` | `pilot:ce/intent/**`, `pilot:ce/apply/**`, +11 | `source:op_host/**`, `source:op_kernel/**`, +4 | `agents/ce-applier.yaml` |
| `ce-change-referee` | `llm` | `referee` | `subagent` | `pilot:ce/**`, `pilot:uo/**`, +4 | `pilot:ce/impact/audit_report.yaml`, `pilot:ce/verify/exclusion_review.yaml`, +1 | `agents/ce-change-referee.yaml` |
| `ce-reviewer` | `llm` | `readonly_reviewer` | `subagent` | `pilot:uo/**`, `pilot:ce/**`, +8 | `pilot:ce/review/**`, `pilot:ce/verify/code_review.yaml`, +1 | `agents/ce-reviewer.yaml` |
| `deterministic-ce-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:ce/**`, `pilot:uo/**`, +8 | `pilot:ce/**`, `pilot:runs/**`, +1 | `agents/deterministic-ce-engine.yaml` |
| `deterministic-tg-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:tg/**`, `pilot:uo/**`, +9 | `pilot:tg/**`, `pilot:runs/**`, +3 | `agents/deterministic-tg-engine.yaml` |
| `deterministic-uo-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:uo/**`, `pilot:runs/**`, +2 | `pilot:uo/**`, `pilot:runs/**/actions/**`, +1 | `agents/deterministic-uo-engine.yaml` |
| `tg-analyst` | `llm` | `producer` | `subagent` | `pilot:tg/**`, `pilot:uo/**`, +7 | `pilot:runs/**/actions/bind_init/parts/**`, `pilot:runs/**/actions/bind_init/scratch/**`, +12 | `agents/tg-analyst.yaml` |
| `uo-gap-investigator` | `llm` | `readonly_analyst` | `subagent` | `pilot:uo/ir/unresolved.yaml`, `pilot:uo/ir/codemap_analyze_receipt.yaml`, +4 | `pilot:uo/ir/gap_investigation.yaml`, `pilot:runs/*/actions/investigate/parts/**`, +2 | `agents/uo-gap-investigator.yaml` |
| `uo-query` | `llm` | `readonly_analyst` | `subagent` | `pilot:uo/**`, `pilot:runs/**`, +3 |  | `agents/uo-query.yaml` |
