# -*- coding: utf-8 -*-
"""Kernel-branch domain coverage over witness keys.

The finalized ``.uo`` is the primary and production authority. Legacy YAML is
accepted only as a compatibility fallback for pre-CodeMap fixtures.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import yaml

from testcase_agent.closure import finite_predicate as FP
from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W


def _arch() -> str:
    return (os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "arch35").strip()


def _product_doc(ws: W.Workspace) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from testcase_agent import product_uo
        p = product_uo.product(ws.root, architecture=_arch())
        doc = product_uo.view(ws.root, "views/kernel.yaml", architecture=_arch())
        if isinstance(doc, dict):
            return doc, {"kind": "uo", "path": str(p), "view": "views/kernel.yaml"}
    except Exception as exc:
        return {}, {"kind": "missing", "path": "", "reason": f"uo_product:{type(exc).__name__}:{exc}"[:180]}
    return {}, {"kind": "missing", "path": "", "reason": "views/kernel.yaml missing from .uo"}


def _legacy_root(ws: W.Workspace) -> Path:
    try:
        from ascendc_pilot.paths import uo_root
        return uo_root(ws.root, arch=_arch())
    except Exception:
        return ws.root / ".ascendc-pilot" / _arch() / "uo"


def view_source(uo: Path | None, rel: str = "views/kernel.yaml") -> dict[str, Any]:
    """Describe a legacy projection source without selecting it as authority.

    Kept as a small compatibility/introspection API for tests and diagnostics.
    Production ``load_kernel_view`` still resolves the formal ``.uo`` product
    first; this helper merely distinguishes an absent export from YAML/DB-backed
    legacy fixtures.
    """
    if uo is None:
        return {"kind": "missing", "path": "", "reason": "uo_root_missing"}
    root = Path(uo).expanduser().resolve()
    path = root / rel
    if path.is_file():
        return {"kind": "yaml", "path": str(path)}
    db = root / "indexes" / "kb_graph.sqlite"
    if db.is_file():
        return {"kind": "db", "path": str(db), "view": rel}
    return {"kind": "missing", "path": "", "reason": f"{rel} missing"}


def _legacy_doc(ws: W.Workspace) -> tuple[dict[str, Any], dict[str, Any]]:
    uo = _legacy_root(ws)
    for rel in ("views/kernel.yaml", "kernel/branches.yaml"):
        path = uo / rel
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(doc, dict):
                return doc, {"kind": "legacy_yaml", "path": str(path)}
    db = uo / "indexes" / "kb_graph.sqlite"
    if db.is_file():
        try:
            from uo_init.kb_index import load_view_blob
            for rel in ("views/kernel.yaml", "kernel/branches.yaml"):
                blob = load_view_blob(db, rel)
                if isinstance(blob, dict) and blob:
                    return blob, {"kind": "legacy_db", "path": str(db), "view": rel}
        except Exception:
            pass
    return {}, {"kind": "missing", "path": "", "reason": "no kernel view in .uo or legacy UO export"}


def load_kernel_view(ws: W.Workspace | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    ws = (ws or W.default_workspace()).ensure()
    doc, source = _product_doc(ws)
    if doc:
        return doc, source
    legacy, legacy_source = _legacy_doc(ws)
    return (legacy, legacy_source) if legacy else (doc, source)


def load_kernel_branches(uo: Path | None = None, *, ws: W.Workspace | None = None) -> list[dict[str, Any]]:
    # ``uo`` retained for API compatibility; product identity comes from ws.root.
    del uo
    doc, _ = load_kernel_view(ws)
    rows = list(doc.get("branches") or doc.get("nodes") or [])
    out = [row for row in rows if isinstance(row, dict) and (not row.get("stage") or row.get("stage") == "constexpr")]
    return out or [row for row in rows if isinstance(row, dict)]


def _condition_to_expr(branch: dict[str, Any]) -> dict[str, Any] | None:
    raw = branch.get("finite_predicate") or branch.get("predicate")
    if isinstance(raw, dict) and raw.get("op"):
        return raw
    dims = list(branch.get("dimensions") or [])
    cond = str(branch.get("condition") or "").strip()
    for dim in dims:
        for op, token in (("eq", "=="), ("ne", "!=")):
            if f"{dim} {token}" in cond:
                rhs = cond.split(token, 1)[1].strip().rstrip(";").strip("() ")
                if rhs.isdigit() or (rhs.startswith("-") and rhs[1:].isdigit()):
                    value: Any = int(rhs)
                elif rhs.lower() in {"true", "false"}:
                    value = rhs.lower() == "true"
                else:
                    value = rhs.strip("'\"")
                return {"op": op, "field": dim, "value": value}
    if dims and cond:
        return {"op": "eq", "field": dims[0], "value": "__UNSUPPORTED__"}
    return None


def evaluate_branch(branch: dict[str, Any], dims: dict[str, Any]) -> FP.Evaluation:
    expr = _condition_to_expr(branch)
    if expr is None:
        return FP.Evaluation(FP.Truth.UNSUPPORTED, {"reason": "no_condition"})
    if expr.get("value") == "__UNSUPPORTED__":
        return FP.Evaluation(FP.Truth.UNSUPPORTED, {"reason": "condition_unparsed", "raw": branch.get("condition")})
    values = {str(k): v for k, v in dims.items()}
    for k, v in list(values.items()):
        if isinstance(v, str) and v.isdigit():
            values[k] = int(v)
        elif isinstance(v, str) and v.startswith("-") and v[1:].isdigit():
            values[k] = int(v)
    return FP.evaluate(expr, values)


def compute_r_kernel(ws: W.Workspace | None = None, *, write: bool = True) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    doc, source = load_kernel_view(ws)
    rows0 = list(doc.get("branches") or doc.get("nodes") or [])
    branches = [r for r in rows0 if isinstance(r, dict) and (not r.get("stage") or r.get("stage") == "constexpr")]
    branches = branches or [r for r in rows0 if isinstance(r, dict)]
    Rset = ledger.load_R(ws)
    r_kernel: dict[str, list[int]] = {}
    branches_by_key: dict[int, list[str]] = {}
    rows: list[list[Any]] = []
    for branch in branches:
        bid = str(branch.get("id") or branch.get("name") or "")
        if not bid:
            continue
        hits: list[int] = []
        unsupported = 0
        for k in sorted(Rset):
            try:
                inst = W.decode(int(k))
            except Exception:
                continue
            ev = evaluate_branch(branch, inst)
            if ev.result is FP.Truth.TRUE:
                hits.append(int(k)); branches_by_key.setdefault(int(k), []).append(bid)
            elif ev.result in (FP.Truth.UNSUPPORTED, FP.Truth.UNKNOWN):
                unsupported += 1
        r_kernel[bid] = hits
        rows.append([bid, str(branch.get("condition") or "")[:120], len(hits), ",".join(str(x) for x in hits[:20]), unsupported, ",".join(str(d) for d in (branch.get("dimensions") or []))])
    path = ""
    if write:
        path = str(ws.report("kernel_coverage.csv"))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh); w.writerow(["branch_id", "condition", "R_kernel_count", "R_kernel_sample", "unsupported_evals", "dimensions"]); w.writerows(rows)
    covered = sum(1 for hits in r_kernel.values() if hits)
    read_dims = {str(d) for branch in branches for d in (branch.get("dimensions") or [])}
    try:
        silent_dimensions = [d for d in W.dim_names() if d not in read_dims]
    except Exception:
        silent_dimensions = []
    return {
        "ok": True,
        "source": source,
        "established": source.get("kind") not in {None, "", "missing"},
        "branches": len(branches),
        "covered": covered,
        "open": len(branches) - covered,
        "R_kernel": {k: len(v) for k, v in r_kernel.items()},
        "path": path,
        "silent_dimensions": silent_dimensions,
        "branches_by_key": {k: sorted(v) for k, v in branches_by_key.items()},
        "kernel_branches": [{"id": bid, "R_count": len(hits), "status": "witnessed" if hits else "open"} for bid, hits in r_kernel.items()],
    }
