---
name: tg-solve
description: >-
  Solve an approved TestAgent plan with SMT (VAR_CSV_* free) and emit CSV rows.
  Blocks when domain_review/binding gaps are unconfirmed or realize yields zero rows.
argument-hint: "<project_root> --op-name <op_name> [--level L0|L1] [--dry-run]"
---

# /tg-solve

Prerequisites: thin `tg-contract` + **LLM/human confirmed** lexicon & domain_review + approved `tg-plan`.

```powershell
tg-solve <project_root> --op-name <op_name> --level L0
```

## Hard gates

- `DOMAIN_REVIEW_REQUIRED` — `domain_review.yaml` still `pending` / unreviewed columns.
- `BINDING_REVIEW_REQUIRED` — `MISSING_CSV_REF` / `UNBOUND_KEY` gaps without locked lexicon entries.
- `REALIZE_EMPTY` — `selected_count>0` but `realized_count==0` (treat as fail, not success).
- Plan approval / plan_hash / contract gap checks unchanged.

## Rules

- Load existing `realization/` contract (version 2). Do not invent CSV headers.
- SMT free variables are `VAR_CSV_*`; KEY/mapped branches are derived.
- Bound `VAR_KEY_*` without confirmed `binding_lexicon.key_derivations` → `KEY_DERIVATION_MISSING`.
- Do **not** add AST specializations to “fix” empty CSV — go back to LLM bind/review.
- Do not modify `.understand-operator/` unless writing confirmed supplements when asked.
