# TD / branch-outcome probe scripts (FAG exploration archive)

These scripts proved the first per-key branch-outcome gap=0 for
`bn2gs1s2_plain`. **Do not grow new operator logic here.**

## Where the capability lives now

| Concern | Engine module |
|---|---|
| Branch condition eval | `testcase_agent.closure.branch_eval` |
| Per-key `(site, outcome)` ledger | `testcase_agent.closure.branch_outcome` |
| Lemma field pins | `testcase_agent.closure.field_pins` |
| Key↔Data reuse (leads / harvest / E inherit) | `testcase_agent.closure.key_data_coupling` |
| UO value-defining writers + guards | `uo_init.passes.value_defining_sites` |
| UO views gate | `uo_init.tg_projection.require_tg_views` |
| Plan level L3 | `testcase_agent.planner` (`L3` / mode `branch_outcome_coverage`) |

The hand-written `lemmas.yaml` rule `drop_off_divisible_by_8` is now reproduced
automatically by `key_data_coupling.derive_pin_leads` (shared root `keepProb`),
so new operators should get leads from UO structure rather than hand analysis.

## What remains here

- Fixtures: `layout.json`, `steerable_branches.json`, `lemmas.yaml`,
  `picked_keys.json`, `close_bn2gs1s2_plain.json` — regression inputs.
- One-off FAG drivers (`close_one_key.py`, `run_pilot.py`, …) may import the
  engine modules; they are not Pilot skills and must not encode FAG-only rules
  into TG.

## Policy

- Shallow UO writers → directed source read + UO gap-patch (not TG hardcode).
- Lemma / E → `source_verified` window (`skills/policies/evidence`).
- No new `td-init` / `td-solve` workflow; use `/tg-plan --level L3` + `/tg-solve`.
