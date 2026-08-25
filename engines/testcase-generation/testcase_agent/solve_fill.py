# -*- coding: utf-8 -*-
"""Expand LLM solve-fill (tg-solve-fill/v1) into case rows.

Plan already named the cells. Solve only inverts arms the Plan predicates
cannot spell as case.* eq maps (probe/replay). The engine merges those
seeds onto init defaults and instantiates every OPEN obligation.
"""
from __future__ import annotations

from typing import Any

from testcase_agent.coverage.compile import compile_obligations
from testcase_agent.plan_fill import AssembleError, ensure_v3, load_yaml

SOLVE_FILL_SCHEMA = "tg-solve-fill/v1"


def is_solve_fill(doc: Any) -> bool:
    if not isinstance(doc, dict):
        return False
    schema = str(doc.get("schema") or "").strip()
    if schema == SOLVE_FILL_SCHEMA:
        return True
    return bool(doc.get("hits") or doc.get("baseline")) and "rows" not in doc


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _eq_val(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        if int(left) == int(right) and str(left).lstrip("+-").isdigit() and str(right).lstrip("+-").isdigit():
            return True
    except (TypeError, ValueError):
        pass
    return str(left).strip() == str(right).strip()


def seed_from_predicate(pred: Any) -> tuple[dict[str, Any], bool]:
    """Return (case seed, complete). complete=False when probe/replay must be inverted."""
    seed: dict[str, Any] = {}
    complete = True
    if not isinstance(pred, dict) or not pred:
        return seed, False

    op = _s(pred.get("op")).lower()
    field = _s(pred.get("field") or pred.get("left"))
    if op in {"and", "all"}:
        ok = True
        for item in pred.get("args") or pred.get("all") or []:
            part, part_ok = seed_from_predicate(item)
            if not part_ok:
                complete = False
            for col, val in part.items():
                if col in seed and not _eq_val(seed[col], val):
                    return {}, False
                seed[col] = val
            ok = ok and part_ok
        return seed, complete and ok and bool(seed)
    if op in {"or", "any"}:
        return seed, False
    if field.startswith("probe.") or field.startswith("replay."):
        return seed, False
    col = field.split(".", 1)[-1] if field.startswith("case.") else ""
    if not col:
        if field and "." not in field:
            col = field
        else:
            return seed, False
    if op in {"", "eq"} and "value" in pred:
        seed[col] = pred.get("value")
        return seed, True
    if op in {"ge", "gt"} and pred.get("value") is not None:
        seed[col] = pred.get("value")
        return seed, True
    if op == "le" and pred.get("value") is not None:
        seed[col] = pred.get("value")
        return seed, True
    if op == "lt" and pred.get("value") is not None:
        try:
            seed[col] = int(pred.get("value")) - 1
            return seed, True
        except (TypeError, ValueError):
            return seed, False
    if op == "in":
        values = list(pred.get("values") or [])
        if values:
            seed[col] = values[0]
            return seed, True
        return seed, False
    if op == "ne":
        return seed, False
    return seed, False


def _dim_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in plan.get("dimensions") or []:
        if isinstance(row, dict) and _s(row.get("id")):
            out[_s(row.get("id"))] = row
    return out


def _part_map(dim: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in dim.get("partitions") or []:
        if isinstance(row, dict) and _s(row.get("id")):
            out[_s(row.get("id"))] = row
    return out


def _init_defaults(init: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(init, dict):
        return {}
    raw = init.get("defaults")
    return dict(raw) if isinstance(raw, dict) else {}


def _init_columns(init: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    if isinstance(init, dict):
        for item in init.get("columns") or []:
            name = _s(item.get("name") if isinstance(item, dict) else item)
            if name:
                names.append(name)
    return names


def _domains(init: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(init, dict):
        return {}
    raw = init.get("domains")
    return raw if isinstance(raw, dict) else {}


def _domain_values(init: dict[str, Any] | None, col: str) -> list[Any]:
    node = _domains(init).get(col)
    if isinstance(node, dict):
        for key in ("values", "enum", "members"):
            raw = node.get(key)
            if isinstance(raw, list) and raw:
                return list(raw)
        profile = node.get("profile") if isinstance(node.get("profile"), dict) else {}
        raw = profile.get("values") or profile.get("enum")
        if isinstance(raw, list) and raw:
            return list(raw)
    return []


def _guard_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in plan.get("guards") or []:
        if isinstance(row, dict) and _s(row.get("id")):
            out[_s(row.get("id"))] = row
    return out


def index_plan(plan: dict[str, Any], init: dict[str, Any] | None = None) -> dict[str, Any]:
    """Engine-owned Solve index: which arms auto-seed, which need LLM hits."""
    dims = _dim_map(plan)
    auto: list[dict[str, Any]] = []
    needs_hit: list[dict[str, Any]] = []
    for did, dim in dims.items():
        cuts = list((dim.get("classifier") or {}).get("requires") or [])
        for pid, part in _part_map(dim).items():
            seed, complete = seed_from_predicate(part.get("predicate") or {})
            row = {"dim": did, "arm": pid, "cuts": cuts, "seed": seed}
            if complete and seed:
                auto.append(row)
            else:
                needs_hit.append(row)
    guards = []
    for gid, guard in _guard_map(plan).items():
        seed, ok = _guard_seed(guard, {}, init)
        guards.append({"id": gid, "seed": seed, "auto": bool(ok and seed)})
    return {"auto": auto, "needs_hit": needs_hit, "guards": guards}


def _hit_map(fill: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in fill.get("hits") or []:
        if not isinstance(row, dict):
            continue
        did, arm = _s(row.get("dim")), _s(row.get("arm"))
        seed = row.get("seed") if isinstance(row.get("seed"), dict) else {}
        if did and arm:
            out[(did, arm)] = dict(seed)
    return out


def _guard_hit_map(fill: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in fill.get("guard_hits") or []:
        if not isinstance(row, dict):
            continue
        gid = _s(row.get("id"))
        seed = row.get("seed") if isinstance(row.get("seed"), dict) else {}
        if gid:
            out[gid] = dict(seed)
    return out


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    out = dict(base)
    for col, val in overlay.items():
        if col in out and not _eq_val(out[col], val):
            return out, col
        out[col] = val
    return out, None


def _ne_witness(init: dict[str, Any] | None, col: str, banned: Any) -> Any | None:
    for val in _domain_values(init, col):
        if not _eq_val(val, banned):
            return val
    defaults = _init_defaults(init)
    cur = defaults.get(col)
    if cur is not None and not _eq_val(cur, banned):
        return cur
    return None


def _guard_seed(guard: dict[str, Any], fill_seed: dict[str, Any], init: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    if fill_seed:
        return dict(fill_seed), True
    pred = guard.get("predicate") if isinstance(guard.get("predicate"), dict) else {}
    seed, complete = seed_from_predicate(pred)
    if complete and seed:
        return seed, True
    if _s(pred.get("op")).lower() == "ne":
        field = _s(pred.get("field"))
        col = field.split(".", 1)[-1] if field.startswith("case.") else field
        wit = _ne_witness(init, col, pred.get("value"))
        if col and wit is not None:
            return {col: wit}, True
    hint = guard.get("negate_hint") if isinstance(guard.get("negate_hint"), dict) else {}
    # negate_hint is the HIT side; miss is the predicate. If still empty, fail.
    del hint
    return seed, bool(seed)


def _pad_row(seed: dict[str, Any], columns: list[str], defaults: dict[str, Any], oid: str) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for col in columns:
        if col in seed:
            row[col] = seed[col]
        elif col in defaults:
            row[col] = defaults[col]
        else:
            row[col] = ""
    if "Testcase_Name" in columns:
        row["Testcase_Name"] = oid
    else:
        row["Testcase_Name"] = oid
    return row


def _extra_unreachable(fill: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in fill.get("unreachable") or []:
        if isinstance(row, dict):
            out.append(row)
    return out


def _matches_unreach(cell: dict[str, str], spec: dict[str, Any]) -> bool:
    parts = spec.get("partitions") if isinstance(spec.get("partitions"), dict) else {}
    if not parts:
        parts = {k: v for k, v in spec.items() if _s(k).startswith("D-")}
    if not parts:
        return False
    for did, arm in parts.items():
        if _s(cell.get(_s(did))) != _s(arm):
            return False
    return True


def assemble_solve(
    fill: dict[str, Any],
    plan: dict[str, Any],
    init: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    plan_v3 = ensure_v3(plan, init)
    idx = index_plan(plan_v3, init)
    hit_map = _hit_map(fill)
    for need in idx["needs_hit"]:
        key = (need["dim"], need["arm"])
        if key not in hit_map or not hit_map[key]:
            errors.append(f"missing hit seed for {need['dim']}.{need['arm']}")
    if errors:
        raise AssembleError(errors)

    dims = _dim_map(plan_v3)
    arm_seed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in idx["auto"]:
        arm_seed[(row["dim"], row["arm"])] = dict(row["seed"])
    for key, seed in hit_map.items():
        cur = dict(arm_seed.get(key) or {})
        cur.update(seed)
        arm_seed[key] = cur

    columns = _init_columns(init)
    defaults = _init_defaults(init)
    extra_defaults = fill.get("defaults") if isinstance(fill.get("defaults"), dict) else {}
    defaults = {**defaults, **extra_defaults}
    baseline = fill.get("baseline") if isinstance(fill.get("baseline"), dict) else {}
    guard_hits = _guard_hit_map(fill)
    extra_unreach = _extra_unreachable(fill)
    obligations = compile_obligations(plan_v3)
    rows: list[dict[str, Any]] = []
    unreachable: list[dict[str, Any]] = []

    for obl in obligations:
        oid = _s(obl.get("id"))
        level = _s(obl.get("level"))
        if level == "L3":
            gid = ""
            expected = obl.get("expected") if isinstance(obl.get("expected"), dict) else {}
            guards = expected.get("guards") if isinstance(expected.get("guards"), dict) else {}
            if len(guards) == 1:
                gid = next(iter(guards))
            if not gid:
                gid = _s(obl.get("guard"))
            guard = _guard_map(plan_v3).get(gid) or {}
            gseed, ok = _guard_seed(guard, guard_hits.get(gid) or {}, init)
            if not ok:
                unreachable.append({"obligation": oid, "reason": f"guard {gid} has no miss seed"})
                continue
            merged, conflict = _merge(dict(baseline), gseed)
            if conflict:
                unreachable.append({"obligation": oid, "reason": f"guard {gid} conflicts on {conflict}"})
                continue
            rows.append(_pad_row(merged, columns, defaults, oid))
            continue

        cell = obl.get("dimensions") if isinstance(obl.get("dimensions"), dict) else {}
        if any(_matches_unreach({_s(k): _s(v) for k, v in cell.items()}, spec) for spec in extra_unreach):
            reason = next(
                (_s(spec.get("reason")) for spec in extra_unreach if _matches_unreach(cell, spec)),
                "owner marked unreachable",
            )
            unreachable.append({"obligation": oid, "dimensions": dict(cell), "reason": reason})
            continue
        merged = dict(baseline)
        conflict_col = None
        for did, arm in cell.items():
            overlay = arm_seed.get((_s(did), _s(arm)))
            if overlay is None:
                conflict_col = f"{did}.{arm}"
                break
            merged, conflict_col = _merge(merged, overlay)
            if conflict_col:
                break
        if conflict_col:
            unreachable.append(
                {
                    "obligation": oid,
                    "dimensions": dict(cell),
                    "reason": f"seed conflict on {conflict_col}",
                }
            )
            continue
        rows.append(_pad_row(merged, columns, defaults, oid))

    return {
        "schema": "tg-cases/pending",
        "columns": columns or sorted({k for r in rows for k in r}),
        "rows": rows,
        "unreachable": unreachable,
        "index": idx,
        "stats": {
            "obligations": len(obligations),
            "rows": len(rows),
            "unreachable": len(unreachable),
        },
    }
