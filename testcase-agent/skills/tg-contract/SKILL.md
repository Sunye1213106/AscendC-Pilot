---
name: tg-contract
description: >-
  Thin AST discovery of CSV columns + unresolved KEY/domain gaps. Always hand
  off to LLM binding (/tg-csv-contract or tg-domain-review) before plan/solve.
argument-hint: "<project_root|kb_root> --op-name <op> --test-script-root <test_script_root>"
---

# /tg-contract

Deterministic **thin AST** only: discover columns, call sites, literal clues, and
**unresolved** gaps. Do **not** invent KEY↔CSV bindings or final domains here.

```powershell
tg-contract <project_root> --op-name <op_name> --test-script-root <test_script_root>
```

`<test_script_root>` must contain the CSV consumer scripts.
`project_root` may be the op package or a `.understand-operator[/<op>]` KB path.

## Outputs under `.testcase-generator/<op>/realization/`

| Artifact | Role |
|----------|------|
| `consumer_evidence.yaml` | Headers, field accesses (discovery) |
| `consumer_schema.yaml` | Ordered fields; thin domains marked |
| `realization_map.yaml` | Bootstrap map (version 2) |
| `binding_lexicon.yaml` | Unlocked proposals only until LLM+human confirm |
| `binding_inventory.yaml` | CSV columns, KEY ids, consumer_kind, thin domains |
| `unresolved.yaml` | `MISSING_CSV_REF` / `UNBOUND_KEY` / thin domain gaps |
| `llm_bind_prompt_bundle.yaml` | Slice for LLM binding + domain review |
| `domain_review.yaml` | Per-column review status (`pending` until confirmed) |
| `domain_hints.yaml` | Stub for LLM/human domain values |

## MUST — LLM bind + human confirm (hard stop)

After CLI success, **Stop**. Do **not** jump to `tg-plan` while
`unresolved.status=ready_for_llm` or `domain_review.status=pending`.

1. Run `/tg-csv-contract` and/or agent `tg-domain-review` on the inventory/unresolved bundle.
2. AskQuestion: `confirm` / `revise` / `stop`.
3. Only after human confirm: write `locked: true` lexicon derivations +
   `domain_review.status=confirmed` (+ `domain_hints` / optional UO `supplements/human_facts.yaml`).
4. Then `tg-plan` → approve → `tg-solve`.

## Hard prohibitions

- **No per-operator / per-test-suite AST specialization** in plugin Python
  (no `keep_prob→IsDrop`, no FAG shape tables, no FASG path hardcodes).
- Gaps go to `unresolved` → LLM → human. Do **not** add another AST if-else.
- Do not modify `.understand-operator/` except optional confirmed `supplements/human_facts.yaml` writeback when the user asks.
