"""CBM-based blast-radius / impact for code review (replaces CRG)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts.cbm_client import CbmClient, CbmSymbol


LAYER_HINTS = (
    ("kernel", ("/kernel/", "kernel_", "op_kernel")),
    ("tiling", ("/tiling/", "tiling", "op_host")),
    ("host", ("/host/", "op_host", "aclnn")),
)


def impact_from_files(
    uo_root: Path,
    files: list[str],
    *,
    max_symbols_per_file: int = 40,
    max_callers_per_symbol: int = 30,
    max_priority: int = 40,
) -> dict[str, Any]:
    """Map changed files → CBM symbols → inbound callers → impacted files + priority."""
    client = CbmClient(uo_root)
    if not client.available:
        return {
            "status": "missing",
            "error": "CBM SQLite unavailable",
            "hint": "Run /uo-init Phase0 index (MCP index_repository) and ensure cbm/index_meta.json is set",
            "project": client.project or None,
            "db_path": str(client.db_path) if client.db_path else None,
            "changed_symbols": [],
            "callers": [],
            "impacted_files": [],
            "priority": [],
        }

    changed_symbols: list[dict[str, Any]] = []
    callers: list[dict[str, Any]] = []
    impacted_files: set[str] = set()
    seen_sym: set[int] = set()
    seen_caller: set[int] = set()
    caller_counts: dict[int, int] = {}

    try:
        for fpath in files:
            norm = fpath.replace("\\", "/")
            impacted_files.add(norm)
            base = Path(norm).name
            # Prefer basename match; also try path suffix.
            hits = client.search_symbols(file_contains=base, limit=max_symbols_per_file)
            if not hits and "/" in norm:
                hits = client.search_symbols(file_contains=norm.split("/")[-2] + "/" + base, limit=max_symbols_per_file)
            for sym in hits:
                if sym.node_id in seen_sym:
                    continue
                # Keep symbols that actually belong to this changed path when possible.
                if base not in sym.file_path and norm not in sym.file_path:
                    continue
                seen_sym.add(sym.node_id)
                entry = sym.as_dict()
                entry["layer_hint"] = _layer_hint(sym.file_path)
                entry["priority_boost"] = _priority_boost(sym, inbound_degree=0)
                changed_symbols.append(entry)
                inbound = client.callers_callees(sym.node_id, direction="inbound", limit=max_callers_per_symbol)
                caller_counts[sym.node_id] = len(inbound)
                entry["inbound_degree"] = len(inbound)
                entry["priority_boost"] = _priority_boost(sym, inbound_degree=len(inbound))
                for caller in inbound:
                    impacted_files.add(caller.file_path)
                    if caller.node_id in seen_caller:
                        continue
                    seen_caller.add(caller.node_id)
                    cdict = caller.as_dict()
                    cdict["calls"] = sym.qualified_name or sym.name
                    cdict["layer_hint"] = _layer_hint(caller.file_path)
                    callers.append(cdict)
    finally:
        client.close()

    priority = sorted(
        changed_symbols,
        key=lambda s: (-int(s.get("priority_boost") or 0), -int(s.get("inbound_degree") or 0), s.get("qualified_name") or ""),
    )[:max_priority]

    return {
        "status": "ok",
        "project": client.project,
        "db_path": str(client.db_path) if client.db_path else None,
        "changed_file_count": len(files),
        "changed_symbol_count": len(changed_symbols),
        "caller_count": len(callers),
        "changed_symbols": changed_symbols[:80],
        "callers": callers[:80],
        "impacted_files": sorted(impacted_files)[:120],
        "priority": priority,
        "hotspots_hint": _hotspots_hint(priority),
    }


def cbm_status(uo_root: Path) -> dict[str, Any]:
    client = CbmClient(uo_root)
    return {
        "available": client.available,
        "project": client.project or None,
        "db_path": str(client.db_path) if client.db_path else None,
        "hint": None
        if client.available
        else "Run /uo-init Phase0 (MCP index_repository) then prepare_operator --write-index-meta",
    }


def _layer_hint(file_path: str) -> str:
    low = file_path.replace("\\", "/").lower()
    for name, tokens in LAYER_HINTS:
        if any(tok in low for tok in tokens):
            return name
    return "other"


def _priority_boost(sym: CbmSymbol, *, inbound_degree: int) -> int:
    score = min(inbound_degree, 20)
    layer = _layer_hint(sym.file_path)
    if layer == "kernel":
        score += 8
    elif layer == "tiling":
        score += 5
    elif layer == "host":
        score += 3
    label = (sym.label or "").lower()
    if label in {"function", "method"}:
        score += 2
    return score


def _hotspots_hint(priority: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in priority[:15]:
        out.append(
            {
                "qualified_name": item.get("qualified_name"),
                "file_path": item.get("file_path"),
                "inbound_degree": item.get("inbound_degree"),
                "layer_hint": item.get("layer_hint"),
                "priority_boost": item.get("priority_boost"),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CBM blast-radius from changed files")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--files", default="", help="Comma-separated changed file paths")
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    if args.status_only:
        print(json.dumps(cbm_status(uo_root), ensure_ascii=False, indent=2))
        return 0 if cbm_status(uo_root).get("available") else 1
    files = [p.strip() for p in args.files.split(",") if p.strip()]
    result = impact_from_files(uo_root, files)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
