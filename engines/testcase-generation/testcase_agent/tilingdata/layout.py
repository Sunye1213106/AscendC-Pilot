# -*- coding: utf-8 -*-
"""Load TilingData ABI layout facts for the generic decoder.

Authority: ``views/tilingdata.yaml`` fields in the finalized ``.uo``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


def _arch() -> str:
    for _name in ("UO_ARCH", "ASCENDC_ARCH"):
        _raw = (os.environ.get(_name) or "").strip()
        if _raw:
            return _raw
    raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE: architecture required")


def _normalize_fields(fields: list[Any]) -> list[dict[str, Any]] | None:
    out: list[dict[str, Any]] = []
    for raw in fields:
        if not isinstance(raw, Mapping):
            return None
        name = str(raw.get("name") or "").strip()
        if not name:
            return None
        if raw.get("variant_guard") or raw.get("nested") or raw.get("nested_struct"):
            return None
        try:
            offset = int(raw["offset"])
            size = int(raw["size"])
        except (KeyError, TypeError, ValueError):
            return None
        row = {
            "name": name,
            "offset": offset,
            "size": size,
            "type": str(raw.get("type") or raw.get("ctype") or "uint"),
            "endian": str(raw.get("endian") or "little"),
        }
        out.append(row)
    return out if out else None


def _from_tilingdata_view(view: Mapping[str, Any]) -> dict[str, Any] | None:
    """Promote view structs → flat layout when every field has offset+size."""
    fields_acc: list[dict[str, Any]] = []
    for st in list(view.get("structs") or []):
        if not isinstance(st, Mapping):
            continue
        for f in list(st.get("fields") or []):
            if isinstance(f, Mapping):
                fields_acc.append(dict(f))
    # Flat ``fields`` list also accepted.
    if not fields_acc and isinstance(view.get("fields"), list):
        fields_acc = [dict(f) for f in view["fields"] if isinstance(f, Mapping)]
    normalized = _normalize_fields(fields_acc)
    if not normalized:
        return None
    return {"schema": "ascendc-pilot-tilingdata-layout/v1", "fields": normalized}


def load_tilingdata_layout(operator_root: Path | None = None) -> dict[str, Any] | None:
    """Return a generic-decoder layout or ``None`` when UO facts are incomplete."""
    roots: list[Path] = []
    if operator_root is not None:
        roots.append(Path(operator_root))
    for env in ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR"):
        raw = (os.environ.get(env) or "").strip()
        if raw:
            roots.append(Path(raw).expanduser().resolve())
    arch = _arch()
    seen: set[Path] = set()
    for root in roots:
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        try:
            from testcase_agent import product_uo

            view = product_uo.view(root, "views/tilingdata.yaml", architecture=arch)
            if isinstance(view, dict) and view:
                layout = _from_tilingdata_view(view)
                if layout:
                    return layout
        except Exception:
            continue
    return None
