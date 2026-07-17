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
| `/uo-init` | End-to-end layered KB build (Phase0 + directed IR + bounded LLM resolve + contract export) |
| `/uo-query` | KB-first Q&A from `ir/operator_graph.yaml` + contracts |
| `/uo-update` | Incremental refresh: isomorphic KB + dedicated `diff/` product for PR tests |
| `/uo-diff` | Reserved read-only CBM change summary (does not write KB or `diff/`) |

Scripts live only at `$PLUGIN_ROOT/uo/scripts`
(see `PATHS.md`). This skill is a router; it does not host `.py` wrappers.

Active pipeline: `prepare_operator` → Phase0 → `build_layered_kb` →
`apply_resolution` → `kb_query_export`; update via `update_operator` /
`export_diff_product`. Validation: `uo._operator.kb_compiler.validate_kb`.

Default user-facing language is Chinese (`prompts/00_language.md`).

If the user clearly wants a full build, load and follow `../uo-init/SKILL.md`.
If they ask a question about an existing KB, load `../uo-query/SKILL.md`.
If they want incremental update after code changes, load `../uo-update/SKILL.md`.
