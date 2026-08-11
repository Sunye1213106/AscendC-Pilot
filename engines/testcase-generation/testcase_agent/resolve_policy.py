"""Audit checklist ids for tg-init.

The csv_consumer hard-gate policy (empty-key allowlist, legitimate-skip
classification, CSV-closure / domain-symmetry / merge-artifact verification,
mid-symbol chase queue, etc.) was removed with the csv_consumer stack. Only
the tilingkey_full_coverage audit checklist id list remains: it is consumed by
``init_status.require_audit_pass`` to validate ``init/audit_report.yaml``.
"""

from __future__ import annotations

# Canonical audit check ids for the (now-removed) csv_consumer checklist.
# Kept only because a couple of tests still assert on this constant's shape;
# no code path builds or requires this checklist anymore.
AUDIT_CHECKLIST_IDS: tuple[str, ...] = (
    "lexicon_resolve_sync",
    "confidence_high_only",
    "chain_to_csv",
    "no_opaque_fn_leaf",
    "nonempty_keys_resolved",
    "binding_resolve_coverage",
    "unresolved_honesty",
    "domain_symmetry",
    "domain_align",
    "tiling_domain_ok",
    "no_placeholders",
    "merge_report",
    "merge_artifacts",
    "full_csv_closure",
    "mid_symbol_drained",
    "shape_graph_built",
    "shape_chain_consistent",
    "unbound_reducible",
    "kernel_shape_progress",
)

# Full tilingkey_full_coverage audit — no CSV lexicon/shape-graph obligations.
TILINGKEY_AUDIT_CHECKLIST_IDS: tuple[str, ...] = (
    "tilingkey_contract",
    "declared_set_nonempty",
    "binding_inventory",
    "host_view_aligned",
    "graph_fingerprint",
    "integrity_gate",
)
