# UO/TG Pipeline Performance — After Optimization

Captured after deterministic pipeline performance work on `main` (2026-07-27).

**Regression operator (not hardcoded in code):** `D:\ops-transformer\attention\flash_attention_score_grad`

Run `python scripts/profile_uo_pipeline.py <repo> --op-name <name> --out docs/performance/profile.json` after a full `/uo-init` workspace exists.

## UO (ms)

```yaml
uo:
  extract_plan_finalize:
    build_layered_kb_total: fixture_microbench
    yaml_export: 0  # structural mode skips publish
  build_layered_kb:
    host_kernel_parallel: enabled_when_both_layers_selected
    bridge: single_write_via_persist_false
  rebuild_from_ledger:
    zero_delta_skip: fast_path_preserved
    selective_rebuild: PATCH_TYPE_TO_LAYERS
  recheck_closure:
    integrity: deferred_to_export_integrity
  export_integrity:
    sqlite_export: temp_db_atomic_replace_with_skip
    human_view_export: publish_kb_products_only
```

## TG (ms)

```yaml
tg:
  tg_contract:
    consumer_scan: cached_via_consumer_index
  binding_inventory:
    consumer_scan: shared_index_when_out_root_present
  tg_plan: unchanged_semantics
  tg_solve: unchanged_semantics
```

## Improvements delivered

| Area | Before | After |
|------|--------|-------|
| Intermediate `build_layered_kb` | Always exports sqlite + human views | `mode=structural` skips publish |
| `bridge.yaml` | Double write | Single write (`persist=False`) |
| Host + Kernel | Serial | `ProcessPoolExecutor(max_workers=2)` with serial fallback |
| YAML IR writes | Always rewrite | `write_yaml_if_changed` |
| SQLite export | Delete + rebuild in place | Temp db + atomic replace; skip if `source_hashes` unchanged |
| TG consumer scan | Re-read + re-parse each pass | `consumer_index.json` reuse |
| `recheck_closure` | Could run `check_kb_integrity` | Integrity deferred to `export_integrity` |

## Test coverage

- `test_structural_publish_split.py`
- `test_bridge_single_write.py`
- `test_parallel_host_kernel_determinism.py`
- `test_yaml_write_if_changed.py`
- `test_incremental_layer_rebuild.py`
- `test_closure_fast_path.py`
- `test_consumer_index_reuse.py`
