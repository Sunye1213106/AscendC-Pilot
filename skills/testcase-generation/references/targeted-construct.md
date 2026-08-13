# Targeted construct

**When to load**: overlay `scenario_targeted` during solve. Complements
`references/search.md` (full-key search).

```text
ScenarioSet
  → retrieve similar rows from harness corpus
  → mutate 1–3 knobs on the CodeMap producer cone
  → repair (InputSemantics + illegal-combo filter)
  → emit harness CSV
  → optional Host replay only if the scenario also needs a key witness
```

## Rules

1. If corpus retrieve hits, **do not** cartesian-expand declared keys `D`.
2. `P-ILLEGAL` → Disable row or exclusion; never NPU.
3. New rows must fill the harness case schema; missing columns use adapter
   defaults, not invented tensors.
4. Precision/perf oracles are harness modes (`only_grad` / `profiler`).
   A tiling-key HIT does not close those obligations.
5. Budget comes from the scenario catalog; exceeding budget is a plan
   change, not a silent expand.
6. Full-key overlay remains `tilingkey_full_coverage` on a separate
   certificate.
