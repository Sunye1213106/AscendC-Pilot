# Composer / plan execution log (fa-pr13 optimization_plan.md)

Date: 2026-08-10. Scope: TG side of the plan. UO cold-start speedup was
handled by a separate agent and is out of scope here.

## Plan items

| Item | Status | Evidence |
|---|---|---|
| P0-1 cold_start seal + audit writer_role | done | `cold_start.py` seal+chain; certify refuses missing/`auto_ok` without `writer_role=engine`; `test_p0_bypass_gates.py` |
| P0-2 provenance before lemma_apply | done | `_run_lemma_apply` → `require_cold_start`, reason `PROVENANCE_REQUIRED` |
| P0-3 UO cold measure | skipped | User confirmed UO speedup already completed elsewhere |
| P1-1 open_patterns + r_witness_values | done | `residual.py`; adaptive focus dims (operator-agnostic) |
| P1-2 lemma_verify | done | engine action + METHOD.md; apply re-checks `REFUTED_BY_R` |
| P1-3 set membership DSL | done | `rule_engine.match_when` / `in` / `not_in`; hypothesis fold |
| P1-4 construct path_counts | done | `construct_hook_dominated` warning; hook-only → issue/`CODEMAP_PATH_REQUIRED` |
| P1-5 search lockout | done | `search_round.search_lockout.yaml` |
| P1-6 tg-lemma-loop | done | `_run_lemma_loop`, workflow/ownership/METHOD.md |
| P2 hypothesis fallback | done | `hypothesis.py` + mine staging injection |
| P2 hint live source_ref | done | `certificate.validate` → `hint_requires_live_source_ref` |
| P2 domain establishment | done | `I0_kernel` / `I0_tilingdata` fail when UO views missing |
| Generic (no FAG specialisation) | done | gate expanded to TG/replay/pilot |

## Real workspace findings (pre-gate)

Against `/work/ops-transformer/.../flash_attention_score_grad/.ascendc-pilot/arch35/tg/closure`:

- Old certificate claimed `ok=true`, `R=4121`, `E=4584`, `gap=0`, `active_rules=23`.
- New gates: `cold_start_unsealed` + `provenance_chain_missing`.
- Kernel / tilingdata coverage CSVs were header-only; `I0_*` now fail with
  `*_domain_not_established` until UO `views/` or `kb_graph.sqlite` exist.
- Rules carry citations in `certificate.proof_scope.assignments`, not only
  `source_citations`; certificate validation now reads both.

## Regressions run

- `engines/testcase-generation/tests` + `scripts/tests/replay`: 446 passed
- `test_no_operator_specialisation`: 6 passed (scope includes TG/replay/pilot)
- `test_lemma_hypothesis`: 7 passed
- `test_domain_establishment`: 6 passed
- pilot (deselect lineage lock flake): 206 passed, 4 skipped

## Still blocked for a fresh gap=0 certificate

1. Sealed `tg-cold-start` must be run *before* any promote (not backfilled).
2. UO product must expose `views/kernel.yaml` + `views/tilingdata.yaml` (or DB).
3. Producer must cite live source for each promoted lemma; `lemma_loop` stops at
   `NEED_PRODUCER` when only engine hypotheses exist.
