# -*- coding: utf-8 -*-
"""Project a frozen CANN ``TilingContext`` host-API catalog onto the CodeMap.

Host IR already walked these call sites during extract. This pass does not
re-lex sources and does not mint every ``context_->`` method. The catalog is
intentionally tiny: ``SetScheduleMode`` (hang / batch vs stream) and
``SetBlockDim`` (same path, cheap).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from uo_init.ids import operation_site_id
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.kernel_scan import norm_file

# Frozen CANN gert::TilingContext methods. Not every host setter.
TILING_CONTEXT_HOST_APIS = frozenset({"SetScheduleMode", "SetBlockDim"})
_MAX_SITES_PER_API = 32
_MAX_TOTAL = 64


def _site_get(site: Any, name: str, default: Any = "") -> Any:
    if isinstance(site, dict):
        return site.get(name, default)
    return getattr(site, name, default)


def _callee_short(site: Any) -> str:
    raw = str(_site_get(site, "callee") or "")
    return raw.split("::")[-1].strip()


def enrich_tiling_context_apis(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
    host_ir: Any = None,
) -> CodeMap:
    """Mint locatable host OPERATION nodes for catalog TilingContext calls."""
    if host_ir is None:
        return codemap
    root = Path(operator_root).expanduser().resolve() if operator_root else Path()
    root_s = str(root) if operator_root else ""
    per_api: dict[str, int] = defaultdict(int)
    minted = 0
    for site in list(getattr(host_ir, "call_sites", None) or []):
        if minted >= _MAX_TOTAL:
            break
        callee = _callee_short(site)
        if callee not in TILING_CONTEXT_HOST_APIS:
            continue
        if per_api[callee] >= _MAX_SITES_PER_API:
            continue
        file = str(_site_get(site, "file") or "")
        line = int(_site_get(site, "line") or 0)
        if not file or line <= 0:
            continue
        nfile = norm_file(file, root_s)
        column = int(_site_get(site, "column") or 0)
        oid = operation_site_id(
            file=nfile, line=line, column=column, callee=callee, root=root_s
        )
        args_raw = _site_get(site, "args") or ()
        args = [str(a) for a in (args_raw if not isinstance(args_raw, str) else (args_raw,))]
        attrs = {
            "callee": callee,
            "layer": "host",
            "catalog": "cann_tiling_context",
            "function": str(_site_get(site, "caller") or ""),
            "receiver": str(_site_get(site, "receiver") or ""),
            "receiver_type": str(_site_get(site, "receiver_type") or ""),
            "args": args,
            "argument": args[0] if args else "",
            "architecture": architecture,
            "provenance": "host_tiling_context_api",
            "column": column,
        }
        codemap.upsert(
            EntityKind.OPERATION,
            callee,
            eid=oid,
            attrs=attrs,
            file=nfile,
            line=line,
            status="confirmed",
        )
        per_api[callee] += 1
        minted += 1
    codemap.meta["tiling_context_apis"] = {
        "count": minted,
        "by_callee": dict(per_api),
        "catalog": sorted(TILING_CONTEXT_HOST_APIS),
    }
    return codemap
