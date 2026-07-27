# UO/TG Pipeline Performance — After Optimization (P0/P1 fix)

Captured after deterministic pipeline performance work + P0/P1 gap fixes on `main` (2026-07-27).

**Regression operator (not hardcoded in code):** use a local UO workspace with full IR; example path used in probes may be `D:\ops-transformer\attention\flash_attention_score_grad` when available.

Run:

```bash
python scripts/profile_uo_pipeline.py <repo> --op-name <name> --out docs/performance/profile.json --with-tg --consumer-root <csv>
```

When no full FAG workspace is present locally, keep probe harness + fixture microbench notes below; fill wall-clock ms from a real workspace when available.

## UO (ms)

```yaml
uo:
  extract_plan_finalize:
    build_layered_kb_total: probe_or_fixture  # structural mode
    yaml_export: 0  # structural skips publish; publish via export_integrity
  build_layered_kb:
    host_kernel_parallel: ProcessPool max_workers=2; fallback_reason recorded
    kernel_file_parallel: ProcessPool when >=2 files; serial/parallel byte-equivalent
    bridge: single_write_via_persist_false
    operator_graph_write: once_after_structural_stats
  rebuild_from_ledger:
    zero_delta_skip: fast_path_preserved
    selective_rebuild: PATCH_TYPE_TO_LAYERS
  recheck_closure:
    integrity: deferred_to_export_integrity
    closure_summary: unified_schema_v2
  apply_update / update_operator:
    structural_only: true
    gates_export: deferred_to_confidence_report_and_export_integrity
  export_integrity:
    sqlite_export: source_hashes_skip_before_entity_collect; PRAGMA integrity_check=ok
    human_view_export: once_in_publish_kb_products  # integrity refresh_human_views=False
```

## TG (ms)

```yaml
tg:
  tg_contract:
    consumer_index: required_optional_evidence_separate_field
    fingerprint: stat_then_sha256; cache_hit_no_read_bytes
  binding_inventory:
    consumer_scan: shared_consumer_index_via_out_root
  tg_plan: unchanged_semantics
  tg_solve: unchanged_semantics
```

## Improvements delivered (honest)

| Area | Before (broken/claim) | After (fixed) |
|------|------------------------|---------------|
| TG `required_optional_evidence` | Mixed into `field_accesses`; lost on consume | Independent index field; evidence-equivalent across no-cache/first/hit |
| `uo-update` apply | Ran integrity before sqlite export → stale sqlite fail | Structural + receipt only; export in `export_integrity` |
| Human views | Double export (publish + integrity) | Single export; `refresh_human_views=False` in publish path |
| Update Action detect/plan | Re-ran each Action | Shared `load_*_if_fresh` helpers |
| Kernel file parallel | Scaffold only / fake tests | Real ProcessPool + serial/parallel fixture equivalence |
| SQLite skip | After entity collect | Before entity collect |
| YAML rewrite | Full dump always / weak skip | Sidecar `.content-hash` skips `safe_dump` |
| Profiler | Invalid run_id; silent rebuild | Valid run_id; errors recorded; optional TG double-run |

## Test coverage

- `test_consumer_index_reuse.py` (evidence equivalence + stat cache)
- `test_structural_publish_split.py`
- `test_bridge_single_write.py`
- `test_parallel_host_kernel_determinism.py` (real multi-file fixture)
- `test_yaml_write_if_changed.py` (content-hash sidecar)
- `test_uo_update.py::test_apply_update_ignores_stale_sqlite`
- `test_closure_fast_path.py`
- `test_no_fag_hardcode` (must stay green)
