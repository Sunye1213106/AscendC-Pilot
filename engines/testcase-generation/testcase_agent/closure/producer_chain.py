# -*- coding: utf-8 -*-
"""Host → TilingData reverse producer chain.

Kernel predicate on a TilingData field becomes:
  field → host writer / tg_host_view → INPUT / COMPILE_VAR / MACRO roots → CSV knobs.

Unresolved reverse chains stay UNRESOLVED — never PROVEN_UNREACHABLE.
"""

from __future__ import annotations

from typing import Any

from testcase_agent.closure import workspace as W


def _load_host_view(ws: W.Workspace | None = None) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    try:
        from testcase_agent import product_uo
        import os

        arch = (os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "arch35").strip()
        doc = product_uo.view(ws.root, "ir/tg_host_view.yaml", architecture=arch)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _load_tilingdata_view(ws: W.Workspace | None = None) -> dict[str, Any]:
    from testcase_agent.closure import tilingdata_domain as TD

    doc, _ = TD.load_tilingdata_view(ws)
    return doc if isinstance(doc, dict) else {}


def resolve_field_to_inputs(field: str, *, ws: W.Workspace | None = None) -> dict[str, Any]:
    """Trace one TilingData field back toward host inputs."""
    ws = (ws or W.default_workspace()).ensure()
    td = _load_tilingdata_view(ws)
    host = _load_host_view(ws)
    field_row: dict[str, Any] = {}
    for st in td.get("structs") or []:
        if not isinstance(st, dict):
            continue
        for fld in st.get("fields") or []:
            if isinstance(fld, dict) and str(fld.get("name") or "") == field:
                field_row = fld
                break
    writers = list(field_row.get("writers") or [])
    writer_formula = str(field_row.get("writer_formula") or "")
    host_fields = [f for f in (host.get("fields") or []) if isinstance(f, dict)]
    # Match by name / tiling_key / packing tokens.
    matched = []
    roots: list[dict[str, Any]] = []
    for hf in host_fields:
        name = str(hf.get("name") or "")
        if name == field or field in name or name.endswith(field):
            matched.append(hf)
            for r in hf.get("reads") or []:
                if isinstance(r, dict):
                    roots.append(r)
    predicates = [
        p
        for p in (host.get("predicates") or [])
        if isinstance(p, dict) and field in str(p.get("fields") or [])
    ]
    status = "COVERED" if roots or writer_formula or writers else "UNRESOLVED"
    return {
        "field": field,
        "status": status,
        "writers": writers,
        "writer_formula": writer_formula,
        "host_fields": matched,
        "input_roots": roots,
        "predicates": predicates,
        "csv_hints": [
            {
                "root": r.get("root"),
                "kind": r.get("kind"),
                "entity_id": r.get("entity_id"),
            }
            for r in roots
        ],
        "note": (
            "Reverse chain ready for construct_case / knobs_for_field"
            if status == "COVERED"
            else "Host producer chain incomplete; leave UNRESOLVED"
        ),
    }


def resolve_obligation(obligation: dict[str, Any], *, ws: W.Workspace | None = None) -> dict[str, Any]:
    """Resolve one TD or Kernel obligation into host/input constraints."""
    fields: list[str] = []
    if obligation.get("field"):
        fields.append(str(obligation["field"]))
    fields.extend(str(x) for x in (obligation.get("tilingdata_fields") or []) if x)
    chains = [resolve_field_to_inputs(f, ws=ws) for f in fields]
    if not chains:
        return {
            "obligation_id": obligation.get("id"),
            "status": "UNRESOLVED",
            "reason": "no_tilingdata_dependency",
            "predicate": obligation.get("predicate"),
        }
    if any(c.get("status") == "COVERED" for c in chains):
        status = "COVERED"
    else:
        status = "UNRESOLVED"
    return {
        "obligation_id": obligation.get("id"),
        "status": status,
        "predicate": obligation.get("predicate"),
        "chains": chains,
        # Concrete predicate the solver must hit — never an abstract branch flag.
        "solver_goal": obligation.get("predicate") or "",
    }
