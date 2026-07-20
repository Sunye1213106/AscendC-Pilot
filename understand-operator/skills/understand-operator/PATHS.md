# Path Resolution

`PLUGIN_ROOT` = repository root (contains `skills/`, `prompts/`, `uo/`, `spec/`).

After `./install.ps1 opencode`, the same tree is also linked as:

`~/.config/opencode/understand-operator-plugin` → `PLUGIN_ROOT`

## SCRIPT_DIR (only canonical location)

```
uo/scripts/
```

Prefer absolute: `$PLUGIN_ROOT/uo/scripts`.

Do **not** look for `.py` wrappers under `skills/understand-operator/` (removed).

## Spec

```
spec/bundle.yaml      # declares hash_inputs
spec/ownership.yaml
spec/kb_layout.yaml
spec/schemas/diff/    # uo-update diff product
```

Hash 只覆盖 `bundle.yaml` → `hash_inputs` 列表中的文件（见仓库 README §5）。

## Active scripts (uo-init / uo-update / uo-query)

### Shared
- `_ir_io.py`, `cbm_client.py`

### uo-init (+ Phase0)
- `prepare_operator.py`
- `macro_scope_scan.py`
- `review_checkpoint.py`
- `stage_cbm_scope.py`
- `finalize_phase0.py`
- `resolve_entrypoints.py`
- `build_layered_kb.py`
- `extract_host_subgraph.py` / `extract_kernel_subgraph.py` / `extract_tilingkey_space.py` / `extract_golden.py`
- `macro_regions.py`  # `#if`/`#ifdef` region eval + KEY soft-undefined
- `reconcile_bridge.py`
- `extract_key_predicates.py`
- `apply_resolution.py`
- `kb_query_export.py`
- `verify_required_subagents.py`

### uo-update
- `detect_kb_changes.py`
- `plan_kb_update.py`
- `update_operator.py`
- `export_diff_product.py`
- (+ Phase0 / `build_layered_kb` as needed)

### uo-query
- `uo_query_readonly.py` (optional; primary path is KB + CBM MCP)

## PROMPT_DIR

`$PLUGIN_ROOT/prompts`
