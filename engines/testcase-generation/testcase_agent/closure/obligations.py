# -*- coding: utf-8 -*-
"""Per-reachable-key TilingData + Kernel branch outcome obligations.

Evidence status taxonomy (reuse; never invent a second set):
  COVERED | PROVEN_UNREACHABLE | UNRESOLVED | CONSTRUCT_FAIL |
  REPLAY_MISMATCH | RUNTIME_FAIL | ORACLE_FAIL

Solver failure is NEVER recorded as PROVEN_UNREACHABLE.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import yaml

from testcase_agent.closure import finite_predicate as FP
from testcase_agent.closure import kernel_domain as KD
from testcase_agent.closure import ledger
from testcase_agent.closure import tilingdata_domain as TD
from testcase_agent.closure import workspace as W

EVIDENCE_STATUSES = (
    "COVERED",
    "PROVEN_UNREACHABLE",
    "UNRESOLVED",
    "CONSTRUCT_FAIL",
    "REPLAY_MISMATCH",
    "RUNTIME_FAIL",
    "ORACLE_FAIL",
)


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    # nearest-rank
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return float(ordered[k])


def _hist(values: list[int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50": _percentile(values, 50),
        "p90": _percentile(values, 90),
        "max": max(values) if values else 0,
        "mean": float(statistics.fmean(values)) if values else 0.0,
    }


def _specialize_branch(branch: dict[str, Any], dims: dict[str, Any]) -> dict[str, Any]:
    """Constant-propagate key dims into a branch; classify residual obligation."""
    stage = str(branch.get("stage") or "").lower()
    bid = str(branch.get("id") or branch.get("name") or "")
    ev = KD.evaluate_branch(branch, dims)
    key_dims = list(branch.get("dimensions") or [])
    td_fields = list(branch.get("tilingdata_fields") or [])
    if ev.result is FP.Truth.TRUE:
        return {
            "branch_id": bid,
            "classification": "fixed_true",
            "stage": stage,
            "status": "COVERED" if stage == "constexpr" else "UNRESOLVED",
            "note": "key_dims_fix_true",
        }
    if ev.result is FP.Truth.FALSE:
        return {
            "branch_id": bid,
            "classification": "fixed_false" if key_dims and not td_fields else "unreachable_under_key",
            "stage": stage,
            "status": "PROVEN_UNREACHABLE" if key_dims and not td_fields and stage == "constexpr" else "UNRESOLVED",
            "note": "key_dims_fix_false",
        }
    if ev.result is FP.Truth.UNSUPPORTED:
        return {
            "branch_id": bid,
            "classification": "runtime_predicate" if td_fields or stage == "runtime" else "unresolved",
            "stage": stage,
            "status": "UNRESOLVED",
            "tilingdata_fields": td_fields,
            "condition": str(branch.get("condition") or ""),
        }
    # UNKNOWN — treat as runtime obligation when TilingData is involved.
    return {
        "branch_id": bid,
        "classification": "runtime_predicate",
        "stage": stage or "runtime",
        "status": "UNRESOLVED",
        "tilingdata_fields": td_fields,
        "condition": str(branch.get("condition") or ""),
    }


def _td_obligations_for_key(fields: list[dict[str, Any]], dims: dict[str, Any]) -> list[dict[str, Any]]:
    del dims  # live-ness under key is over-approx until producer chain lands
    out: list[dict[str, Any]] = []
    for fld in fields:
        name = str(fld.get("name") or "")
        if not name:
            continue
        fclass = str(fld.get("field_class") or "").lower()
        risk = list(fld.get("risk_markers") or [])
        priority = bool(fld.get("coverage_priority"))
        if fclass == "derived":
            continue
        if fclass == "payload" and not risk and not priority:
            continue
        if fclass not in {"control", "boundary", "payload", ""}:
            continue
        value_classes = list(fld.get("value_classes") or [])
        if not value_classes:
            # Without extracted classes, still ask for a non-default / default pair
            # on control/boundary fields, and on payload fields that carry risk
            # markers / coverage_priority (overflow/tail/align/zero/min/max).
            if fclass in {"control", "boundary"} or priority or risk:
                value_classes = [
                    {"field": name, "op": "==", "value": 0, "predicate": f"{name} == 0"},
                    {"field": name, "op": "!=", "value": 0, "predicate": f"{name} != 0"},
                ]
            else:
                continue
        for vc in value_classes:
            pred = str(vc.get("predicate") or f"{name} {vc.get('op')} {vc.get('value')}")
            out.append(
                {
                    "id": f"TD::{name}::{pred}",
                    "field": name,
                    "field_class": fclass or "control",
                    "predicate": pred,
                    "op": vc.get("op"),
                    "value": vc.get("value"),
                    "status": "UNRESOLVED",
                }
            )
    return out


def project_key_obligations(
    key: int,
    *,
    branches: list[dict[str, Any]] | None = None,
    fields: list[dict[str, Any]] | None = None,
    base_witness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project TD + Kernel obligations for one reachable tiling key."""
    try:
        dims = W.decode(int(key))
    except Exception as exc:
        return {
            "tiling_key": int(key),
            "reachable": True,
            "status": "UNRESOLVED",
            "error": f"decode_failed:{exc}",
            "tilingdata_obligations": [],
            "kernel_obligations": [],
        }
    branches = branches if branches is not None else KD.load_kernel_branches()
    fields = fields if fields is not None else TD.load_tilingdata_fields()
    specialized = [_specialize_branch(b, dims) for b in branches]
    kernel_obligations: list[dict[str, Any]] = []
    for row in specialized:
        if row.get("classification") != "runtime_predicate":
            continue
        bid = str(row.get("branch_id") or "")
        cond = str(row.get("condition") or "")
        for outcome, label in ((True, "T"), (False, "F")):
            kernel_obligations.append(
                {
                    "id": f"KB::{bid}:{label}",
                    "branch_id": bid,
                    "outcome": outcome,
                    "predicate": cond if outcome else f"!({cond})" if cond else "",
                    "tilingdata_fields": list(row.get("tilingdata_fields") or []),
                    "status": "UNRESOLVED",
                }
            )
    td_obligations = _td_obligations_for_key(fields, dims)
    active_td = sorted(
        {
            str(f.get("name"))
            for f in fields
            if isinstance(f, dict)
            and (
                str(f.get("field_class") or "") in {"control", "boundary"}
                or (str(f.get("field_class") or "") == "payload" and f.get("risk_markers"))
            )
        }
    )
    # Base witness covers nothing until joint replay observes outcomes; keep hook.
    covered_ids: set[str] = set()
    if base_witness and base_witness.get("covers"):
        covered_ids = {str(x) for x in base_witness.get("covers") or []}
    for obl in td_obligations + kernel_obligations:
        if obl["id"] in covered_ids:
            obl["status"] = "COVERED"
    return {
        "tiling_key": int(key),
        "reachable": True,
        "dims": {str(k): str(v) for k, v in dims.items()},
        "base_witness": base_witness or {},
        "active_td_fields": active_td,
        "branch_specialization": specialized,
        "tilingdata_obligations": td_obligations,
        "kernel_obligations": kernel_obligations,
        "counts": {
            "active_td_fields": len(active_td),
            "td_obligations": len(td_obligations),
            "runtime_branch_outcomes": len(kernel_obligations),
            "uncovered": sum(
                1
                for o in td_obligations + kernel_obligations
                if o.get("status") != "COVERED"
            ),
        },
    }


def collect_obligations(ws: W.Workspace | None = None, *, write: bool = True, max_keys: int = 0) -> dict[str, Any]:
    """Collector: no case generation — only inventory + histograms over R."""
    ws = (ws or W.default_workspace()).ensure()
    Rset = sorted(ledger.load_R(ws))
    Eset = ledger.load_E(ws)
    if max_keys and max_keys > 0:
        Rset = Rset[:max_keys]
    branches = KD.load_kernel_branches(ws=ws)
    fields = TD.load_tilingdata_fields(ws=ws)
    per_key: list[dict[str, Any]] = []
    active_td_hist: list[int] = []
    td_obl_hist: list[int] = []
    kb_hist: list[int] = []
    uncovered_hist: list[int] = []
    for key in Rset:
        row = project_key_obligations(int(key), branches=branches, fields=fields)
        per_key.append(row)
        c = row.get("counts") or {}
        active_td_hist.append(int(c.get("active_td_fields") or 0))
        td_obl_hist.append(int(c.get("td_obligations") or 0))
        kb_hist.append(int(c.get("runtime_branch_outcomes") or 0))
        uncovered_hist.append(int(c.get("uncovered") or 0))

    # Lower bound on additional cases ≈ max uncovered obligations if no set-cover,
    # and ≈ uncovered/4 under the 4~6 case/key engineering budget heuristic.
    uncovered_total = sum(uncovered_hist)
    case_lower_naive = uncovered_total  # one case per obligation
    case_lower_joint = sum(max(1, (u + 3) // 4) for u in uncovered_hist) if uncovered_hist else 0

    inventory = {
        "schema": "tg-obligation-inventory/v1",
        "reachable_keys": len(Rset),
        "unreachable_e_keys": len(Eset),
        "note": "E keys inherit unreachability proofs and get no runtime obligations",
        "histograms": {
            "active_td_field_per_key": _hist(active_td_hist),
            "td_obligation_per_key": _hist(td_obl_hist),
            "runtime_branch_outcome_per_key": _hist(kb_hist),
            "uncovered_obligation_per_key": _hist(uncovered_hist),
        },
        "case_count_bounds": {
            "naive_one_per_obligation": case_lower_naive,
            "joint_cover_approx_uncovered_div4": case_lower_joint,
            "engineering_budget_4_to_6_per_key": {
                "min": len(Rset) * 4,
                "max": len(Rset) * 6,
            },
            "stop_if_over_10_per_key": len(Rset) * 10,
        },
        "global_inventory": {
            "kernel_branches": len(branches),
            "tilingdata_fields": len(fields),
        },
        "keys": per_key,
    }
    path = ""
    summary_path = ""
    if write:
        path = str(ws.report("obligation_inventory.yaml"))
        Path(path).write_text(yaml.safe_dump(inventory, allow_unicode=True, sort_keys=False), encoding="utf-8")
        summary = {
            "schema": "tg-obligation-summary/v1",
            "reachable_keys": inventory["reachable_keys"],
            "histograms": inventory["histograms"],
            "case_count_bounds": inventory["case_count_bounds"],
            "global_inventory": inventory["global_inventory"],
        }
        summary_path = str(ws.report("obligation_summary.yaml"))
        Path(summary_path).write_text(yaml.safe_dump(summary, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # Compact JSONL for tooling
        jsonl = ws.report("obligation_inventory.jsonl")
        with open(jsonl, "w", encoding="utf-8") as fh:
            for row in per_key:
                slim = {
                    "tiling_key": row["tiling_key"],
                    "counts": row.get("counts"),
                    "td": [o["id"] for o in row.get("tilingdata_obligations") or []],
                    "kb": [o["id"] for o in row.get("kernel_obligations") or []],
                }
                fh.write(json.dumps(slim, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "path": path,
        "summary_path": summary_path,
        "reachable_keys": len(Rset),
        "histograms": inventory["histograms"],
        "case_count_bounds": inventory["case_count_bounds"],
    }
