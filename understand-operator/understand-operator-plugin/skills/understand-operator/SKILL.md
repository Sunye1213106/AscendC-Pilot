---
name: understand-operator
description: >-
  Router for AscendC operator KB commands. Prefer /uo-init, /uo-query, /uo-update,
  /uo-diff. Use only when the user says understand-operator without a subcommand.
disable-model-invocation: true
argument-hint: "use /uo-init | /uo-query | /uo-update | /uo-diff"
---

# understand-operator (retired single entry)

The old monolithic `/understand-operator` entry is **retired**.

Tell the user to use one of:

| Command | Purpose |
|---|---|
| `/uo-init` | End-to-end KB build in a target repo |
| `/uo-query` | KB-first Q&A (CBM only when source proof needed) |
| `/uo-update` | Disabled; ask the user to rerun `/uo-init` |
| `/uo-diff` | Reserved diff interface (unchanged / read-only) |

Shared scripts remain in this directory (`prepare_operator.py`,
`quality_gate.py`, `verify_required_subagents.py`, `prepare_fact_file.py`,
`validate_candidate_batch.py`, `compile_candidate_facts.py`,
`evaluate_review_trigger.py`, `validate_spec_consistency.py`, `validate_fact_stage.py`,
`build_fact_registry.py`, `build_query_index.py`, `verify_required_scripts.py`,
`build_compile_gate.py`, `source_graph_compiler.py`, `materialize_derived_graph.py`,
`validate_semantic_completeness.py`, `prepare_graph_review.py`,
`validate_graph_review.py`, `uo_query_readonly.py`). Agent-side CBM lookups use MCP
`codebase-memory-mcp`; no local CBM query script is provided.

Default user-facing language is Chinese (`prompts/00_language.md`); TodoWrite titles must be Chinese.

If the user clearly wants a full build, load and follow `../uo-init/SKILL.md`.
If they ask a question about an existing KB, load `../uo-query/SKILL.md`.
If they want incremental refresh, load `../uo-update/SKILL.md`.
If they ask for diff only, load `../uo-diff/SKILL.md`.

## Global underlying rule

`../../prompts/00_cbm_first_rule.md`: choose tools by question type. File
structure and macro-scope discovery use deterministic filesystem/`rg` first;
symbols, calls, registration semantics, IO semantics, and source behavior
validation remain CBM MCP first.
