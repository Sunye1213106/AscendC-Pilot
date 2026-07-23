# tg-init-audit — `init/audit_report.yaml` schema

路径（装机后）：`$PLUGIN_ROOT/agents/references/init-audit-schema.md`  
清单权威：`$PLUGIN_ROOT/skills/tg-init/references/tg-init-audit.md`  
合法 skip：`$PLUGIN_ROOT/skills/tg-init/references/legitimate-skips.md`

`checks[].id` **MUST** 覆盖清单全量（与 `resolve_policy.AUDIT_CHECKLIST_IDS` 同构）。  
`--verify-csv-closure` 的 `gates` 键 = `VERIFY_GATE_IDS`（清单子集，同名）。

```yaml
version: 1
status: pass | fail
checked_at: <iso>
op_name: <op>
checks:
  - id: lexicon_resolve_sync
    status: pass | fail | warn
    detail: "..."
  - id: confidence_high_only
    status: pass | fail
    detail: "..."
  - id: chain_to_csv
    status: pass | fail
    detail: "..."
  - id: no_opaque_fn_leaf
    status: pass | fail
    detail: "..."
  - id: nonempty_keys_resolved
    status: pass | fail
    detail: "..."
  - id: binding_resolve_coverage
    status: pass | fail
    detail: "needs_binding_keys ⊆ uo_query_resolve/KEY_*.yaml"
  - id: unresolved_honesty
    status: pass | fail
    detail: "skip ∈ legitimate-skips.md（含 not_input_derivable）"
  - id: domain_symmetry
    status: pass | fail
    detail: "..."
  - id: domain_align
    status: pass | fail
    detail: "..."
  - id: tiling_domain_ok
    status: pass | fail
    detail: "..."
  - id: no_placeholders
    status: pass | fail
    detail: "..."
  - id: merge_report
    status: pass | fail
    detail: "..."
  - id: merge_artifacts
    status: pass | fail
    detail: "..."
  - id: full_csv_closure
    status: pass | fail
    detail: "..."
  - id: mid_symbol_drained
    status: pass | fail
    detail: "..."
  - id: shape_graph_built
    status: pass | fail
    detail: "..."
  - id: shape_chain_consistent
    status: pass | fail
    detail: "..."
  - id: unbound_reducible
    status: pass | fail
    detail: "..."
  - id: kernel_shape_progress
    status: pass | fail | warn
    detail: "..."
blockers: []
warnings: []
next: "tg-init --confirm" | "PARENT: auto nested Tasks → re-merge → --verify-csv-closure (do NOT ask user)"
```

warn 仅允许：`lexicon_resolve_sync`、`kernel_shape_progress`。
