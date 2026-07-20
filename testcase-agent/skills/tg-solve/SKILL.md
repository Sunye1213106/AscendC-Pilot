---
name: tg-solve
description: >-
  Solve an approved TestAgent plan with SMT (VAR_CSV_* free) and emit CSV rows
  by projecting the model. Use when the user runs /tg-solve.
argument-hint: "<project_root> --op-name <op_name> [--level L0|L1] [--dry-run]"
---

# /tg-solve

Prerequisites: `tg-contract` + approved `tg-plan`.

```powershell
tg-solve <project_root> --op-name <op_name> --level L0
```

Rules:

- Load existing `realization/` contract (version 2). Do not invent CSV headers.
- SMT free variables are `VAR_CSV_*`; KEY/mapped branches are derived.
- Emit CSV by projecting `VAR_CSV_*` (+ emit_derived templates). No DEFAULT_SHAPE guessing unless `--allow-legacy-realization`.
- Solver report must include skipped counts.
- Do not modify `.understand-operator/`.
