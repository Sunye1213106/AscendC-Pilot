---
name: tg-plan
description: >-
  Intake Understand KB, extract generation conditions, and build L0–L3 coverage
  plan filtered by CSV realization reachability. Use when the user runs /tg-plan.
argument-hint: "<project_root> --op-name <op_name> --csv-consumer-root <root> [--level L0|L1|L2|L3] [--topic <id>]"
---

# /tg-plan

Requires a CSV contract first (`tg-contract` or pass `--csv-consumer-root` to rebuild).

```powershell
tg-contract <project_root> --op-name <op_name> --csv-consumer-root <test_script_root>
tg-plan <project_root> --op-name <op_name> --level L1 --csv-consumer-root <test_script_root>
```

Plan filters:

- L0 KEY values not in derived CSV image → `NOT_CSV_REALIZABLE` (unreachable)
- L1 abstract/unmapped branches → unreachable

Review `plan/levels/<level>/review.md` for pending vs not-CSV-realizable counts.

## HARD STOP — human review

After `tg-plan`, **stop**. Use AskQuestion: `approve` / `reject` / `suggest`.
On `approve`, run `tg-solve` immediately.
