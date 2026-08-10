# UO cold-start after speedup (completeness-preserving)

Source: `uo_cold_speed.json` / `uo_cold_speed.log` (FAG arch35, cold TU cache wiped).

| Phase | Before (probe run) | After | Notes |
|---|---:|---:|---|
| prepare | 32.9s | **0.3s** | force_confirm skips TU probe (extract still full) |
| extract | 59.2s | **54.1s** | ProcessPool host\|\|kernel (unchanged path) |
| analyze | 111.2s | **33.5s** | compile 32.7s; no re-bundle |
| resolve | 0.1s | 0.1s | |
| commit | 118.5s | **1.0s** | reuses analyze CodeMap |
| **total** | **321.8s** | **88.9s** | target was ≤180s |

Baseline extract-only wall was **311.9s** (`uo_cold_baseline.md`).

## Completeness check (same as pre-speedup product)

- entities=4583, relations=9293, legal_key_count=8705
- graph_fp=`5d29d0d84b2629bb2b8a2b86f89c7a2dae338e0e8edc3a1136e9ec5a9b98cfbf`
- tiling_key coverage 19/19 (decl/packing/producer/root), dependency 12/19
- host/kernel/tilingdata/input-output path flags all true

## What changed (no pass skipped)

1. **analyze→commit reuse** — compile once; commit only writes `.uo`
2. **host_ir.pkl + in-process bundle store** — analyze does not rebuild var_model
3. **`_host_symbols_for_key` O(n³)→indexed** — finalize_views 46s→0.6s
4. **kernel function def scan** — catastrophic regex → linear `)…{` walk (scopes 26s→0.5s)
5. **source_gaps line index + batched macro/kernel regex** — 17s→9s
6. **shared source text cache** across enrichment passes
7. **skip redundant audit** in `write_codemap` when summary already computed

No `fast`-profile pass skipping; all enrichment passes still run.
