---
name: tg-csv-contract
type: subagent
description: >-
  Bounded LLM bind after thin tg-init contract scaffolds. Fill lexicon gaps from
  inventory evidence only; no hardcoded op tables; no Z3/CSV.
---

# Agent: tg-csv-contract

## Task

在 **thin contract 脚手架已存在** 后，于 inventory/unresolved 证据内补全
`binding_lexicon` 与 domain 提案，达到可交 uo-query / merge 的状态。

成功：gaps 有证据绑定或显式 unresolved；**未**生成 CSV / 未调用 Z3。

## Target

仅处理父代理列出的 `binding_gaps` / `needs_binding_keys` / `unbound_atoms` 子集。  
禁止顺便扫全库或改 AST/插件 Python。

## Context

`OUT_ROOT=.ascendc-agent/tg/realization/`  
前置：`binding_inventory.yaml`、`llm_bind_prompt_bundle.yaml`、`consumer_evidence.yaml`、
弱 `realization_map` / `binding_lexicon`、`unresolved.yaml`、`domain_review.yaml`。

语义主路径仍走 uo-query（见 `prompts/init/dispatch.md`）；本 agent 不替代之。

## Authoritative Sources

- inventory / unresolved / prompt bundle（+ cbm_query_hints）
- UO 图查询结果与 CBM snippet（经 uo-query 或受控 MCP）
- 脚本小窗 Read（bundle 引用行）

**Non-authoritative：** 记忆、命名直觉、裸 Grep 全仓、其他算子硬编码表。

## Required Procedure

1. 分类 gap（KEY / atom / domain）
2. 查证 inventory + 受控源码证据
3. 写 lexicon expr（叶子 → `VAR_CSV_*`）；记 `source_refs` + rationale
4. 证据不足 → 保留 unresolved；禁止猜列名
5. AskQuestion **仅**用于域/lexicon **锁定**（`confirm`/`revise`/`stop`）——**禁止**问「是否继续下一轮绑定」；WHILE 环由父代理自动驱动
Atom schema：`$PLUGIN_ROOT/agents/references/csv-contract-schema.md`。

## Hard Constraints

### MUST

- KEY 由 CSV **派生**（非 free）；每条绑定有 `source_refs`
- `LOOP_LOCAL` / `PLATFORM_MACRO`：永不绑定
- `status: proposed` 允许 `confidence: medium`；进 merge / resolved 候选 **仅** `high`

### MUST NOT

- 硬编码第二算子名进 TG；发明 inventory 无证据的 CSV 列
- 改 condition parser / AST / 插件逻辑；生成 CSV；调用 Z3
- 确认 `_` 为合法单元格；`*_layout` 与 `*_shape` 同语义时只绑 shape
- 把 AskQuestion 当成绑定 WHILE 的「继续？」闸门

### ONLY 可写

`binding_lexicon.yaml`、`domain_hints.yaml` / `domain_review.yaml`、
`consumer_schema.yaml`、`realization_map.yaml`（v2）、`unresolved.yaml`、
`agent_report.yaml`；可选 UO `supplements/human_facts.yaml`（人确认后）

## Output Schema + Acceptance + Failure Handling

见 `$PLUGIN_ROOT/agents/references/csv-contract-schema.md`。  
Acceptance：无发明列；impossible 类未绑；confirm 路径清晰。  
Failure：证据不足 → unresolved + 原因码；禁止伪 resolved。
