# -*- coding: utf-8 -*-
"""Joint TilingData + Kernel obligation solving with set-cover minimization.

One candidate case must satisfy TD and Kernel obligations together. Solving
targets concrete predicates (e.g. ``s1Inner * dAlign > ubSize``), never an
abstract ``branch_123 = true`` free variable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from testcase_agent.closure import construct
from testcase_agent.closure import obligations as OBL
from testcase_agent.closure import producer_chain as PC
from testcase_agent.closure import workspace as W


def _greedy_set_cover(universe: set[str], sets: list[tuple[str, set[str]]]) -> list[str]:
    remaining = set(universe)
    chosen: list[str] = []
    pool = [(cid, set(cov)) for cid, cov in sets]
    while remaining and pool:
        pool.sort(key=lambda item: len(item[1] & remaining), reverse=True)
        cid, cov = pool.pop(0)
        hit = cov & remaining
        if not hit:
            break
        chosen.append(cid)
        remaining -= hit
    return chosen


def build_candidates_for_key(
    key: int,
    *,
    projection: dict[str, Any] | None = None,
    ws: W.Workspace | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Construct candidate cases that jointly target uncovered obligations."""
    ws = (ws or W.default_workspace()).ensure()
    projection = projection or OBL.project_key_obligations(int(key))
    uncovered = [
        o
        for o in list(projection.get("tilingdata_obligations") or [])
        + list(projection.get("kernel_obligations") or [])
        if o.get("status") != "COVERED"
    ]
    resolved = [PC.resolve_obligation(o, ws=ws) for o in uncovered]
    # Reuse construct_case for the key; joint cover treats the base construction
    # as a multi-obligation carrier that set-cover can keep or drop later.
    try:
        inst = W.decode(int(key))
    except Exception as exc:
        return {
            "tiling_key": int(key),
            "ok": False,
            "status": "CONSTRUCT_FAIL",
            "error": f"decode_failed:{exc}",
            "candidates": [],
            "resolved_obligations": resolved,
        }
    cases = []
    try:
        built = construct.build(inst, seed=seed)
    except Exception as exc:
        return {
            "tiling_key": int(key),
            "ok": False,
            "status": "CONSTRUCT_FAIL",
            "error": str(exc)[:300],
            "candidates": [],
            "resolved_obligations": resolved,
        }
    if not isinstance(built, list):
        built = [built] if built else []
    for idx, case in enumerate(built):
        # Optimistic cover estimate: a single constructed case can hit many
        # obligations; actual cover comes from real replay observed bitmap.
        case_id = f"k{key}_c{idx}"
        claimed = {str(o.get("id")) for o in uncovered}
        payload: Any
        if isinstance(case, dict):
            payload = case
        elif hasattr(case, "__dict__"):
            payload = {k: getattr(case, k) for k in dir(case) if not k.startswith("_") and not callable(getattr(case, k))}
            # Keep Case objects compact
            payload = {
                "repr": repr(case)[:500],
                "type": type(case).__name__,
            }
        else:
            payload = {"raw": repr(case)[:500]}
        cases.append(
            {
                "case_id": case_id,
                "tiling_key": int(key),
                "case": payload,
                "solver_goals": [r.get("solver_goal") for r in resolved if r.get("solver_goal")],
                "claimed_covers": sorted(claimed),
                "status": "UNRESOLVED",  # until replay observes
            }
        )
    return {
        "tiling_key": int(key),
        "ok": True,
        "status": "UNRESOLVED",
        "uncovered": len(uncovered),
        "candidates": cases,
        "resolved_obligations": resolved,
        "build_path": construct.last_build_path(),
    }


def select_minimal_cases(
    candidates: list[dict[str, Any]],
    *,
    observed_covers: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Minimum set cover over observed (or claimed) obligation bitmaps."""
    observed_covers = observed_covers or {}
    universe: set[str] = set()
    sets: list[tuple[str, set[str]]] = []
    for cand in candidates:
        cid = str(cand.get("case_id") or "")
        cov = set(observed_covers.get(cid) or cand.get("claimed_covers") or [])
        universe |= cov
        sets.append((cid, cov))
    chosen = _greedy_set_cover(universe, sets)
    return {
        "ok": True,
        "selected_case_ids": chosen,
        "obligation_universe": sorted(universe),
        "selected_count": len(chosen),
        "algorithm": "greedy_set_cover",
    }


def joint_cover_keys(
    keys: list[int] | None = None,
    *,
    ws: W.Workspace | None = None,
    write: bool = True,
    max_keys: int = 0,
) -> dict[str, Any]:
    """Build joint candidates + set-cover selection for reachable keys."""
    from testcase_agent.closure import ledger

    ws = (ws or W.default_workspace()).ensure()
    if keys is None:
        keys = sorted(ledger.load_R(ws))
    if max_keys and max_keys > 0:
        keys = list(keys)[:max_keys]
    per_key = []
    selected_total = 0
    for key in keys:
        built = build_candidates_for_key(int(key), ws=ws)
        selection = select_minimal_cases(list(built.get("candidates") or []))
        selected_total += int(selection.get("selected_count") or 0)
        per_key.append({**built, "selection": selection})
    doc = {
        "schema": "tg-joint-cover/v1",
        "keys": len(keys),
        "selected_cases_total": selected_total,
        "avg_selected_per_key": (selected_total / len(keys)) if keys else 0.0,
        "per_key": per_key,
        "policy": {
            "joint": True,
            "solve_concrete_predicates": True,
            "abstract_branch_vars_forbidden": True,
            "set_cover": "greedy",
        },
    }
    path = ""
    if write:
        path = str(ws.report("joint_cover.yaml"))
        Path(path).write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "path": path, "keys": len(keys), "selected_cases_total": selected_total, "avg_selected_per_key": doc["avg_selected_per_key"]}
