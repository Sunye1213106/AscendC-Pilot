---
name: tg-solve
description: >-
  Run TestAgent phase 2 abstract SMT solving from an approved coverage plan. Use
  when the user runs /tg-solve or asks to solve approved testcase generation
  obligations into abstract candidates.
argument-hint: "<project_root> --op-name <op_name>"
---

# /tg-solve

Use this command to run phase 2 abstract SMT solving from an approved TestAgent plan.

Prerequisites:

- Run `tg-init` first.
- Run `tg-plan` first.
- Human approval must bind both the current Snapshot Hash and current Plan Hash in `.testcase-generator/<op_name>/plan/human_supplement.yaml`.
- `plan/unresolved.yaml` must be `ready_for_manual_review` with no hard blockers and no contract gaps.

Run:

```powershell
tg-solve <project_root> --op-name <op_name>
```

Rules:

- Only solve abstract Constraint IR with SMT.
- Every SAT candidate must come from a compiled obligation target expression.
- Stop after phase 2 candidate selection.
- Do not generate real shapes, tensors, CSV files, or executable test cases.
- Do not execute the operator.
- Do not enter phase 3.
