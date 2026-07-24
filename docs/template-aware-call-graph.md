# Template-aware Function / Call Graph

## Problem: old merge paths still left

Identity v3 stopped short-name ID collisions, but extraction still had:

1. Candidate dedupe ignored signature / template / start_line → overloads collapsed early.
2. Kernel Branch/Loop scanned whole files and hung under a single Entry.
3. No stable `calls` edges (Entry `contains` Process/Init only).
4. TDF / KVAR used leaf-only ids (`TDF_<leaf>`).
5. `KEY_TILINGKEY` selected **all** KernelEntry nodes.
6. `_merge_nodes` silently renamed colliding ids (`id@ikey[:8]`).

## What changed (production)

| Area | Change |
|------|--------|
| `function_body.py` | `FunctionDefinition` / `CallSite`; `iter_function_definitions` / `resolve_*`; brace parser no longer mistakes nested `if (` for methods |
| `function_call_graph.py` | verified / `candidate_set` / `missing` `calls` edges (fail-closed) |
| `resolve_entrypoints.py` | `_dedupe_candidates` key includes signature + template + start_line; enrich from snippet |
| `extract_kernel_subgraph.py` | per-`FunctionDefinition` Branch/Loop/Call; Entry→KernelClass→Function; typed TDF via `mint_field_identity`; TilingKeyValue→TemplateInstance (no select-all) |
| `extract_host_subgraph.py` | TDF nodes use `mint_field_identity` + `owning_type` |
| `reconcile_bridge.py` | leaf fallback marked `owning_type_missing_unique_leaf_fallback` |
| `semantic_identity.py` | scoped ids prefer ordinal + normalized expr; `mint_template_instance_identity` |
| `build_layered_kb.py` | `SEMANTIC_ID_COLLISION` diagnostics; no silent alt-id |

### FunctionDefinition schema

```yaml
name / qualified_name / class_or_namespace
normalized_signature
template_arity_or_signature / specialization_kind
file_path / start_line / end_line
header_text / body_text
source_hash / snippet_hash
identity_key / stable_id
```

### Template instance mapping

```text
TilingKeyDimension --has_value--> TilingKeyValue
TilingKeyValue --selects--> TemplateInstance   # resolved | candidate_set
TemplateInstance --implements--> KernelEntry     # when uniquely matched
KernelEntry --contains--> KernelClass --contains--> FunctionDefinition
FunctionDefinition --contains--> Branch|Loop
FunctionDefinition --calls--> FunctionDefinition
```

Ambiguous KEY→instance: `target_status: candidate_set` + unresolved `tilingkey_template_instance_ambiguous`. Never select-all Entries.

## Unit tests (no live FAG required)

```bash
cd engines/understand-operator
python -m pytest \
  tests/test_template_aware_identity.py \
  tests/test_kernel_unit_isolation.py \
  tests/test_no_fag_hardcode.py \
  tests/test_function_call_graph.py \
  tests/test_tiling_field_identity.py \
  tests/test_fag_function_isolation.py \
  -q -k "not fag_repo"
```

Last run: **37 passed**.

## FAG rebuild (manual)

```bash
cd engines/understand-operator
python -m uo.scripts.build_layered_kb \
  d:/PR-review/TEST/ops-transformer/attention/flash_attention_score_grad \
  --op-name flash_attention_score_grad \
  --architecture arch35 \
  --layers host,kernel,tilingkey,golden,bridge
```

Optional integration:

```bash
python -m pytest tests/test_fag_function_isolation.py::test_fag_repo_kernel_extract_if_present -q
```

Do **not** treat pre-rebuild IR under `.ascendc-pilot/uo/ir/` as proof of this change set.

## Static limits still open

- Call resolution is brace/source based; no full C++ overload ranking by argument types.
- Template specialization kind remains heuristic from nearby header text.
- Macro regions outside any function attach to `FileScope`, not a KernelEntry.
- Host REGISTER_TILING_TEMPLATE → instance wiring is best-effort via tilingkey aliases / path_family.
