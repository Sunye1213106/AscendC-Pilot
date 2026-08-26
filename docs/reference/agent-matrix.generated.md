# Agent 矩阵

本文件由 `agents/*.yaml` 生成，请不要手工编辑。

| Agent | 类型 | 角色 | 模式 | 可读范围 | 可写范围 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| `ascendc-pilot` | `llm` | `controller` | `primary` | `pilot:*` |  | `agents/ascendc-pilot.yaml` |
| `ce-analyst` | `llm` | `producer` | `subagent` | `pilot:ce/plan/**`, `pilot:session_handoff.md`, +7 | `pilot:runs/**/actions/plan_draft/**`, `pilot:runs/**/actions/plan_revise/**`, +2 | `agents/ce-analyst.yaml` |
| `ce-applier` | `llm` | `producer` | `subagent` | `pilot:ce/plan/**`, `pilot:runs/**`, +6 | `source:op_host/**`, `source:op_kernel/**`, +4 | `agents/ce-applier.yaml` |
| `ce-reviewer` | `llm` | `readonly_reviewer` | `subagent` | `pilot:uo/**`, `pilot:ce/plan/**`, +9 |  | `agents/ce-reviewer.yaml` |
| `deterministic-ce-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:ce/**`, `pilot:uo/**`, +7 | `pilot:ce/**`, `pilot:runs/**`, +1 | `agents/deterministic-ce-engine.yaml` |
| `deterministic-tg-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:tg/**`, `pilot:uo/**`, +8 | `pilot:tg/**`, `pilot:runs/**`, +3 | `agents/deterministic-tg-engine.yaml` |
| `deterministic-uo-engine` | `deterministic_engine` | `deterministic_engine` | `subagent` | `pilot:uo/**`, `pilot:runs/**`, +2 | `pilot:uo/**`, `pilot:runs/**/actions/**`, +1 | `agents/deterministic-uo-engine.yaml` |
| `tg-analyst` | `llm` | `producer` | `subagent` | `pilot:tg/**`, `pilot:uo/**`, +10 | `pilot:runs/**/actions/bind_init/parts/**`, `pilot:runs/**/actions/bind_init/scratch/**`, +1 | `agents/tg-analyst.yaml` |
| `uo-gap-investigator` | `llm` | `readonly_analyst` | `subagent` | `pilot:uo/ir/unresolved.yaml`, `pilot:uo/ir/codemap_analyze_receipt.yaml`, +4 | `pilot:uo/ir/gap_investigation.yaml`, `pilot:runs/*/actions/investigate/parts/**`, +2 | `agents/uo-gap-investigator.yaml` |
| `uo-heal-analyst` | `llm` | `producer` | `subagent` | `pilot:uo/**`, `pilot:runs/**`, +2 | `pilot:runs/**/actions/propose_include_heal/parts/**`, `pilot:runs/**/actions/propose_include_heal/scratch/**`, +1 | `agents/uo-heal-analyst.yaml` |
| `uo-query` | `llm` | `readonly_analyst` | `subagent` | `pilot:uo/**`, `pilot:runs/**`, +3 |  | `agents/uo-query.yaml` |
