# Template-aware call graph (Phase 6)

## Problem: old merge paths

Earlier extraction merged kernel/host symbols too aggressively:

- **Short-name collision**: nodes with the same display id (e.g. `Process`) from different classes or files were treated as one entity.
- **CBM `resolve_qn`**: when several symbols shared a short name, the first SQL hit was returned.
- **`find_function_body`**: multiple brace-bounded definitions with the same name picked `matches[0]` unless a zero-distance `hint_line` applied.
- **Kernel subgraph**: a single `KPATH_ENTRY` owned file-level `KOP_{kind}_{stem}` markers for every scanned kernel header.
- **Branch/loop ids**: `stable_id("KBR_", name, line)` ignored owning function and file identity, so the same line number in two files could collide conceptually.
- **`build_layered_kb`**: merged nodes solely by `id`, even when `identity_key` differed.

## New identity model (`IDENTITY_VERSION=3`)

Semantic identity material now includes:

| Field | Role |
|--------|------|
| `identity_key` / `stable_id` | Hash of kind, path, qn, signature, class, template arity, **specialization_kind**, arch, families |
| `specialization_kind` | `primary` \| `partial` \| `explicit` \| `instance` \| `none` (generic C++ heuristics) |
| `template_arity_or_signature` | Normalized contents of the first balanced `<...>` near a declaration |
| `mint_scoped_node_id` | Branch/loop nodes scoped by **owning function `identity_key` + file + line** |
| `mint_method_identity` | Methods require `class_or_namespace` |

Entrypoint linking uses `target_status=candidate_set` with `candidate_ids` when multiple template impls share a path family (fail-closed, no fake resolution).

Kernel extraction prefers **`entrypoint_graph.extraction_units`**: each unit gets its own `KernelEntry` node id (`entry_root` / EP stable id), and files attach to the unit matched by `path_family` or seed file.

## Tests

Run:

```bash
cd engines/understand-operator
python -m pytest tests/test_template_aware_identity.py tests/test_kernel_unit_isolation.py tests/test_no_fag_hardcode.py -q
```

Coverage highlights:

- DemoKernelA vs DemoKernelB `Process` → different `stable_id`
- Overloads, template arity, primary vs explicit → distinct keys
- Branch ids differ for same line across files
- Ambiguous `resolve_qn` → `None`; ambiguous `find_function_body` without class → `None`
- Multi-unit kernel graph → multiple `KernelEntry` nodes, Process nodes under distinct entries (not one `KPATH_ENTRY`)

## Unresolved / static limits

- Template specialization detection is heuristic (header snippet only); explicit specializations without `template<>` in the snippet may stay `none`.
- CBM ambiguity remains unresolved until disambiguated by class, file, or human confirmation — never auto-picked.
- Multi-unit GET_TPL binding still blocks globally when multiple host calls exist without schema/file/unit association.

## FAG verification note

Production code must not hardcode FAG or FlashAttention names (`tests/test_no_fag_hardcode.py` guards this).

Read-only spot-check on existing fixture IR
`TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/uo/ir/`
(artifacts may predate a full re-extract under identity v3):

- `entrypoint_graph.yaml`: **13** `extraction_units`; multiple distinct `identity_key` / `stable_id` values; `symbol_ref.class_or_namespace` includes several kernel/host classes (not a single short-name merge).
- `host_subgraph.yaml`: helper nodes carry per-symbol `identity_key` + optional `class_or_namespace`.
- No lone global `KPATH_ENTRY` as the sole kernel owner in current entrypoint units.

Re-running UO extract on FAG after this change set is recommended for a full kernel-subgraph multi-unit `Process`/`Init` binding check.
