"""Audit checklist ids for tg-init.

Only the tilingkey_full_coverage audit checklist remains. It is consumed by
``init_status.require_audit_pass`` to validate ``init/audit_report.yaml``.
"""

from __future__ import annotations

TILINGKEY_AUDIT_CHECKLIST_IDS: tuple[str, ...] = (
    "tilingkey_contract",
    "declared_set_nonempty",
    "binding_inventory",
    "host_view_aligned",
    "graph_fingerprint",
    "integrity_gate",
)
