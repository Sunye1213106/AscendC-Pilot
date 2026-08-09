# -*- coding: utf-8 -*-
"""Kernel-branch domain coverage over witness keys.

Loads branches from UO ``views/kernel.yaml`` (or DB projection), evaluates
constexpr conditions via ``finite_predicate`` on each witness key's dims, and
writes ``kernel_coverage.csv`` / returns R_kernel.
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


def _uo_root(ws: W.Workspace) -> Path | None:
    arch = (os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "arch35").strip()
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(ws.root, arch=arch)
    except Exception:
        cand = ws.root / ".ascendc-pilot" / arch / "uo"
        return cand if cand.is_dir() else None


def _load_view_doc(uo: Path, *rel_candidates: str) -> dict[str, Any]:
    """YAML on disk first, then the DB view blob (DB is the product authority)."""
    for rel in rel_candidates:
        path = uo / rel
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(doc, dict):
                return doc
    db = uo / "indexes" / "kb_graph.sqlite"
    if db.is_file():
        try:
            from uo_init.kb_index import load_view_blob

            for rel in rel_candidates:
                blob = load_view_blob(db, rel.replace("\\", "/"))
                if isinstance(blob, dict) and blob:
                    return blob
        except Exception:
            pass
    return {}


def load_kernel_branches(uo: Path | None) -> list[dict[str, Any]]:
    if uo is None:
        return []
    doc = _load_view_doc(uo, "views/kernel.yaml", "kernel/branches.yaml")
    rows = list(doc.get("branches") or doc.get("nodes") or [])
    # Prefer constexpr-shaped rows when present.
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("stage") and row.get("stage") != "constexpr":
            continue
        out.append(row)
    return out or [r for r in rows if isinstance(r, dict)]


def _condition_to_expr(branch: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort map of kernel branch condition → finite_predicate expr."""
    raw = branch.get("finite_predicate") or branch.get("predicate")
    if isinstance(raw, dict) and raw.get("op"):
        return raw
    dims = list(branch.get("dimensions") or [])
    cond = str(branch.get("condition") or "").strip()
    # Simple patterns: Dim == Val / Dim != Val
    for dim in dims:
        for op, token in (("eq", "=="), ("ne", "!=")):
            needle = f"{dim} {token}"
            if needle in cond:
                rhs = cond.split(token, 1)[1].strip().rstrip(";")
                rhs = rhs.strip("() ")
                if rhs.isdigit() or (rhs.startswith("-") and rhs[1:].isdigit()):
                    value: Any = int(rhs)
                elif rhs.lower() in {"true", "false"}:
                    value = rhs.lower() == "true"
                else:
                    value = rhs.strip("'\"")
                return {"op": op, "field": dim, "value": value}
    if dims and cond:
        # Unsupported structured form — mark for UNKNOWN rather than false exclude.
        return {"op": "eq", "field": dims[0], "value": "__UNSUPPORTED__"}
    return None


def evaluate_branch(
    branch: dict[str, Any],
    dims: dict[str, Any],
) -> FP.Evaluation:
    expr = _condition_to_expr(branch)
    if expr is None:
        return FP.Evaluation(FP.Truth.UNSUPPORTED, {"reason": "no_condition"})
    if expr.get("value") == "__UNSUPPORTED__":
        return FP.Evaluation(FP.Truth.UNSUPPORTED, {"reason": "condition_unparsed", "raw": branch.get("condition")})
    # Coerce dim values: decode often yields strings.
    values = {str(k): v for k, v in dims.items()}
    for k, v in list(values.items()):
        if isinstance(v, str) and v.isdigit():
            values[k] = int(v)
        elif isinstance(v, str) and v.startswith("-") and v[1:].isdigit():
            values[k] = int(v)
    return FP.evaluate(expr, values)


def compute_r_kernel(
    ws: W.Workspace | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """For each kernel branch, collect witness keys whose dims satisfy it."""
    ws = (ws or W.default_workspace()).ensure()
    uo = _uo_root(ws)
    branches = load_kernel_branches(uo)
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
                hits.append(int(k))
                branches_by_key.setdefault(int(k), []).append(bid)
            elif ev.result in (FP.Truth.UNSUPPORTED, FP.Truth.UNKNOWN):
                unsupported += 1
        r_kernel[bid] = hits
        rows.append([
            bid,
            str(branch.get("condition") or "")[:120],
            len(hits),
            ",".join(str(x) for x in hits[:20]),
            unsupported,
            ",".join(str(d) for d in (branch.get("dimensions") or [])),
        ])

    path = ""
    if write:
        path = str(ws.report("kernel_coverage.csv"))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([
                "branch_id", "condition", "R_kernel_count", "R_kernel_sample",
                "unsupported_evals", "dimensions",
            ])
            w.writerows(rows)

    covered = sum(1 for hits in r_kernel.values() if hits)
    # Dimensions no branch reads at all: a defect lead, not a coverage number.
    read_dims = {
        str(d)
        for branch in branches
        for d in (branch.get("dimensions") or [])
    }
    try:
        silent_dimensions = [d for d in W.dim_names() if d not in read_dims]
    except Exception:
        # No resolvable TilingKey schema here; the branch numbers still stand.
        silent_dimensions = []
    return {
        "ok": True,
        "branches": len(branches),
        "covered": covered,
        "open": len(branches) - covered,
        "R_kernel": {k: len(v) for k, v in r_kernel.items()},
        "path": path,
        "silent_dimensions": silent_dimensions,
        # key → branch ids it triggers, for the per-TilingKey closure rows.
        "branches_by_key": {k: sorted(v) for k, v in branches_by_key.items()},
        "kernel_branches": [
            {
                "id": bid,
                "R_count": len(hits),
                "status": "witnessed" if hits else "open",
            }
            for bid, hits in r_kernel.items()
        ],
    }
