---
name: tg-contract
description: >-
  Build CSV consumer evidence and realization map from an explicit test-script
  root before planning. Use when the user runs /tg-contract or needs SMT→CSV.
argument-hint: "<project_root> --op-name <op_name> --csv-consumer-root <test_script_root>"
---

# /tg-contract

Deterministic script scan + bootstrap realization map (KEY/branch derived from CSV).
Optionally refine with `/tg-csv-contract` LLM agent.

```powershell
tg-contract <project_root> --op-name <op_name> --csv-consumer-root <test_script_root>
```

`<test_script_root>` must contain the CSV consumer scripts (e.g. `TEST/fag_debug_tools`).
Do **not** rely on silent FASG path discovery.

Outputs under `.testcase-generator/<op>/realization/`:

- `consumer_evidence.yaml` — headers, field accesses, sample domains
- `consumer_schema.yaml` — ordered fields / roles
- `realization_map.yaml` — `VAR_CSV_*` free vars + derived KEY/branches (version 2)
- `binding_lexicon.yaml` — per-op KEY tokens / CSV aliases / KEY derivations (bootstrap heuristics only until `/tg-csv-contract`)
- `unresolved.yaml` — gaps for LLM refinement

Then run `/tg-csv-contract` to fill `binding_lexicon.yaml` from script/KB evidence (TG does **not** ship operator-specific hard tables), then `tg-plan`.
