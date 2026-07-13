---
name: tg-plan
description: >-
  Build the TestAgent phase 1 coverage-obligation plan from a frozen tg-init
  snapshot. Use when the user runs /tg-plan or asks to plan testcase generation
  coverage from TestAgent intake.
argument-hint: "<project_root> --op-name <op_name> [--level L0|L1|L2] [--focus \"<natural language scope>\"]"
---

# /tg-plan

Use this command to build the phase 1 coverage plan from a frozen TestAgent snapshot.

Run:

```powershell
tg-plan <project_root> --op-name <op_name> --level L1 --focus "TND 场景中 PostNz 分支"
```

Levels:

- `L0`: minimal legal smoke.
- `L1`: runtime/main functional coverage plus legal boundaries and expected rejects.
- `L2`: exhaustive reachable TilingKey coverage with pruning, relations, merging, and per-key realization.

After it completes, stop for human review. In OpenCode, prefer a `question` selection with:

- `approve`: allow phase 2
- `revise`: modify coverage plan
- `supplement`: add human test focus
- `stop`: stop

Human supplements must be written to `.testcase-generator/<op_name>/plan/human_supplement.yaml`. Approval requires:

- `decision: approve`
- `approved_snapshot_hash: <current snapshot_hash>`
- `approved_plan_hash: <current plan_hash>`
- `approved_at: <review timestamp>`

Do not modify Understand Canonical KB.
