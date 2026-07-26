"""Producer-facing CBM locate + windowed source read (wraps uo.scripts.cbm_client)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def lookup_symbol(
    project_root: Path,
    *,
    name: str,
    file_contains: str = "",
    architecture: str = "",
    class_qn: str = "",
    pad: int = 2,
    limit: int = 8,
) -> dict[str, Any]:
    """Resolve a symbol via local CBM SQLite and return a bounded source window.

    Reuses ``CbmClient`` + ``read_source_snippet`` — no second indexing path.
    """
    from ascendc_pilot.paths import uo_root
    from uo.scripts.cbm_client import CbmClient, read_source_snippet

    root = Path(project_root).expanduser().resolve()
    uo = uo_root(root)
    client = CbmClient(uo)
    out: dict[str, Any] = {
        "ok": False,
        "cbm_project": client.project or "",
        "cbm_available": bool(client.available),
        "query": str(name or "").strip(),
        "status": "unavailable",
        "hits": [],
        "snippet": "",
        "evidence_source": "cbm",
    }
    q = str(name or "").strip()
    if not q:
        out["error"] = "name required"
        return out
    if not client.available:
        out["error"] = "CBM SQLite unavailable — check uo/cbm/index_meta.json"
        out["fallback"] = "Read confirmed-scope file window (offset/limit); do not dump whole file"
        return out

    try:
        hit, ambiguous = client.resolve_qn_or_ambiguous(
            q,
            file_contains=str(file_contains or "").strip() or None,
            class_qn=str(class_qn or "").strip() or None,
            prefer_file_contains=str(file_contains or "").strip() or None,
            architecture=str(architecture or "").strip() or None,
            limit=max(1, int(limit)),
        )
    finally:
        client.close()

    if hit is not None:
        snip = read_source_snippet(
            root,
            hit.file_path,
            hit.start_line,
            hit.end_line or hit.start_line,
            pad=max(0, int(pad)),
        )
        out.update(
            {
                "ok": True,
                "status": "resolved",
                "hits": [hit.as_dict()],
                "snippet": snip,
                "evidence_files": [hit.file_path],
                "evidence_lines": [f"{hit.start_line}-{hit.end_line or hit.start_line}"],
            }
        )
        return out

    hits = [h.as_dict() for h in ambiguous]
    out["hits"] = hits
    if hits:
        out["status"] = "ambiguous"
        out["ok"] = True
        out["fallback"] = (
            "Disambiguate with file_contains/class_qn, or Read a window around "
            "candidate start_line (not whole file)"
        )
        return out

    out["status"] = "miss"
    out["ok"] = True
    out["fallback"] = (
        "CBM miss — Read confirmed-scope source window using candidate file_path/start_line; "
        "never dump the entire file"
    )
    return out


def lookup_as_json(project_root: Path, **kwargs: Any) -> str:
    return json.dumps(lookup_symbol(project_root, **kwargs), ensure_ascii=False, indent=2)
