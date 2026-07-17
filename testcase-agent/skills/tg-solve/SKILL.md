---
name: tg-solve
description: >-
  Solve an approved TestAgent plan with SMT/set-cover and emit CSV cases.
  Use when the user runs /tg-solve.
argument-hint: "<project_root> --op-name <op_name> [--dry-run]"
---

# /tg-solve

Resolve install paths from `skills/PATHS.md` (or `~/.config/opencode/testcase-agent-plugin` after install).

Prerequisites:

- Run `tg-plan` first, then AskQuestion `approve` (writes `plan/human_supplement.yaml` with current Snapshot/Plan Hash).
- Or call this skill directly after an approved `human_supplement.yaml`.
- `plan/unresolved.yaml` must be `ready_for_manual_review` with no hard blockers and no contract gaps.

```powershell
tg-solve <project_root> --op-name <op_name>
tg-solve <project_root> --op-name <op_name> --dry-run
```

Rules:

- Run deterministic prepare first to refresh `realization/consumer_evidence.yaml`.
- Reuse `consumer_schema.yaml` and `realization_map.yaml` only when their hashes match the latest evidence, snapshot, and plan.
- If contract files are missing or stale, dispatch `/tg-csv-contract`, then run deterministic validation before invoking Python `tg-solve`.
- Stop on validation failure. Do not continue to CSV emission with stale or partial contract files.
- Compose GlobalLegal ∧ obligation Target via scripts; SMT via Z3.
- Write abstract candidates under `solve/` for audit.
- By default write `cases/cases.csv` (fag_debug_tools compatible). `--dry-run` skips CSV.
- Do not call LLM to invent case rows.
- Do not modify `.understand-operator/`.
