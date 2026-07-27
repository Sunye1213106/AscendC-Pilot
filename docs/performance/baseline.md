# UO/TG Pipeline Performance Baseline

Captured on `main` before deterministic pipeline performance optimization (2026-07-27).

**Regression operator (not hardcoded in code):** `D:\ops-transformer\attention\flash_attention_score_grad`

**Note:** Full FAG UO workspace was not present locally at capture time. Micro-benchmarks below use
`engines/understand-operator/tests/fixtures/fag_macro_semantic_failure` and synthetic rebuild paths.
Re-run `python scripts/profile_uo_pipeline.py` after a full `/uo-init` on FAG to refresh end-to-end numbers.

## UO (ms)

```yaml
uo:
  extract_plan_finalize:
    build_layered_kb_total: null  # requires full FAG uo workspace
    yaml_export: null
    sqlite_export: null
    human_view_export: null
  build_layered_kb:
    entrypoints: null
    macro_semantics: null
    tilingkey: null
    host: null
    kernel: null
    bridge: null
    yaml_export: null
  rebuild_from_ledger:
    zero_delta_skip: null
    selective_rebuild: null
  recheck_closure:
  export_integrity:
    sqlite_export: null
    integrity_check: null
```

## TG (ms)

```yaml
tg:
  tg_contract:
    consumer_scan: null
  binding_inventory:
    consumer_scan: null
  tg_plan: null
  tg_solve: null
```

## Known bottlenecks (pre-optimization)

- `build_layered_kb` always runs `export_kb_graph` + `export_human_views` even on intermediate rebuilds
- `reconcile_bridge` writes `bridge.yaml` internally; caller writes again
- Host and kernel extraction are sequential
- TG consumer scripts re-read and re-parse Python sources on every contract/build step
