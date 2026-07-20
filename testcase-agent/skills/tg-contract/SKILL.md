---
name: tg-contract
description: >-
  Build CSV consumer evidence and realization map from an explicit test-script
  root. Prefer embedding via tg-plan --test-script-root; use this only when the
  user wants contract artifacts alone or to refresh lexicon before plan.
argument-hint: "<project_root|kb_root> --op-name <op> --test-script-root <test_script_root>"
---

# /tg-contract

Deterministic script scan + bootstrap realization map (KEY/branch derived from CSV).
Optionally refine with `/tg-csv-contract` LLM agent.

**Default UX:** users who already want a plan should run `/tg-plan` with
`--test-script-root` — that **embeds** this step. Only run `/tg-contract` alone when
they ask for contract refresh without planning.

```powershell
tg-contract <project_root> --op-name <op_name> --test-script-root <test_script_root>
# aliases: --csv-consumer-root
```

`<test_script_root>` must contain the CSV consumer scripts (e.g. `TEST/fag_debug_tools`).
Do **not** rely on silent FASG path discovery.
`project_root` may be the op package or a `.understand-operator[/<op>]` KB path.

Outputs under `.testcase-generator/<op>/realization/`:

- `consumer_evidence.yaml` — headers, field accesses, sample domains
- `consumer_schema.yaml` — ordered fields / roles
- `realization_map.yaml` — `VAR_CSV_*` free vars + derived KEY/branches (version 2)
- `binding_lexicon.yaml` — per-op KEY tokens / CSV aliases / KEY derivations (bootstrap heuristics only until `/tg-csv-contract`)
- `unresolved.yaml` — gaps for LLM refinement

Then optionally `/tg-csv-contract` to fill `binding_lexicon.yaml`, then `tg-plan`
(with `--test-script-root` again, or `--reuse-contract` if map is fresh).
