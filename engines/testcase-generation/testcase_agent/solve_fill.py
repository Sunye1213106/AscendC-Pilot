# -*- coding: utf-8 -*-
"""Expand LLM solve-fill (tg-solve-fill/v1) into case rows.

Plan already named the cells. Solve only inverts arms the Plan predicates
cannot spell as case.* eq maps (probe/replay). The engine merges those
seeds onto init defaults and instantiates every OPEN obligation.
"""
from __future__ import annotations

from typing import Any

from testcase_agent.coverage.compile import compile_obligations
from testcase_agent.plan_fill import AssembleError, ensure_v3

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


def _case_col(field: str) -> str | None:
    text = _s(field)
    if text.startswith("probe.") or text.startswith("replay."):
        return None
    if text.startswith("case."):
        return text.split(".", 1)[-1] or None
    if text and "." not in text:
        return text
    return None


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
    col = _case_col(field)
    if not col:
        return seed, False
    if op in {"", "eq"} and "value" in pred:
        seed[col] = pred.get("value")
        return seed, True
    if op == "ge" and pred.get("value") is not None:
        seed[col] = pred.get("value")
        return seed, True
    if op == "gt" and pred.get("value") is not None:
        try:
            seed[col] = int(pred.get("value")) + 1
            return seed, True
        except (TypeError, ValueError):
            return seed, False
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
    rows = fill.get("guard_witnesses")
    if not isinstance(rows, list) or not rows:
        rows = fill.get("guard_hits") or []
    for row in rows:
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


def _int_offset(value: Any, delta: int) -> Any | None:
    try:
        return int(value) + delta
    except (TypeError, ValueError):
        return None


def falsify_predicate(pred: Any, init: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    """Return a case seed that makes ``pred`` FALSE. probe/replay cannot be seeded."""
    if not isinstance(pred, dict) or not pred:
        return {}, False
    op = _s(pred.get("op")).lower()
    field = _s(pred.get("field") or pred.get("left"))
    if op in {"and", "all"}:
        for item in pred.get("args") or pred.get("all") or []:
            seed, ok = falsify_predicate(item, init)
            if ok and seed:
                return seed, True
        return {}, False
    if op in {"or", "any"}:
        seed: dict[str, Any] = {}
        for item in pred.get("args") or pred.get("any") or []:
            part, ok = falsify_predicate(item, init)
            if not ok or not part:
                return {}, False
            merged, conflict = _merge(seed, part)
            if conflict:
                return {}, False
            seed = merged
        return seed, bool(seed)
    if op == "not":
        return seed_from_predicate(pred.get("arg"))
    col = _case_col(field)
    if not col:
        return {}, False
    if op in {"", "eq"}:
        wit = _ne_witness(init, col, pred.get("value"))
        if wit is not None:
            return {col: wit}, True
        return {}, False
    if op == "ne":
        if "value" not in pred:
            return {}, False
        return {col: pred.get("value")}, True
    if op == "in":
        values = list(pred.get("values") or [])
        for val in _domain_values(init, col):
            if not any(_eq_val(val, banned) for banned in values):
                return {col: val}, True
        wit = _ne_witness(init, col, values[0] if values else None)
        if wit is not None and not any(_eq_val(wit, banned) for banned in values):
            return {col: wit}, True
        return {}, False
    if op == "not_in":
        values = list(pred.get("values") or [])
        if values:
            return {col: values[0]}, True
        return {}, False
    if op == "ge":
        off = _int_offset(pred.get("value"), -1)
        if off is not None:
            return {col: off}, True
        return {}, False
    if op == "gt":
        if pred.get("value") is None:
            return {}, False
        return {col: pred.get("value")}, True
    if op == "le":
        off = _int_offset(pred.get("value"), 1)
        if off is not None:
            return {col: off}, True
        return {}, False
    if op == "lt":
        if pred.get("value") is None:
            return {}, False
        return {col: pred.get("value")}, True
    if op == "is_null":
        wit = _ne_witness(init, col, None)
        if wit is not None:
            return {col: wit}, True
        return {col: 0}, True
    if op == "is_present":
        return {col: None}, True
    return {}, False


def _guard_seed(guard: dict[str, Any], fill_seed: dict[str, Any], init: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    """Violating seed for L3: fill_seed > negate_hint > falsify_predicate."""
    if fill_seed:
        return dict(fill_seed), True
    hint = guard.get("negate_hint") if isinstance(guard.get("negate_hint"), dict) else {}
    if hint:
        return {str(k): v for k, v in hint.items()}, True
    pred = guard.get("predicate") if isinstance(guard.get("predicate"), dict) else {}
    seed, ok = falsify_predicate(pred, init)
    if ok and seed:
        return seed, True
    return {}, False


def constraint_seed(
    plan: dict[str, Any],
    init: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """Seed case columns from plan.constraints. Unseedable predicates are listed, not dropped silently."""
    del init
    seed: dict[str, Any] = {}
    unseedable: list[str] = []
    owners: dict[str, str] = {}
    rows = plan.get("constraints") or []
    if not isinstance(rows, list):
        return seed, unseedable, owners
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        cid = _s(row.get("id")) or f"constraints[{idx}]"
        pred = row.get("predicate") if row.get("predicate") is not None else row.get("expr")
        part, ok = seed_from_predicate(pred)
        if not ok or not part:
            unseedable.append(cid)
            continue
        for col, val in part.items():
            if col in seed and not _eq_val(seed[col], val):
                other = owners.get(col, "?")
                raise AssembleError(
                    [f"PLAN_UNCONSTRUCTIBLE: constraint {other} vs {cid} on {col}"]
                )
            seed[col] = val
            owners[col] = cid
    return seed, unseedable, owners


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
    cseed, unseedable, c_owners = constraint_seed(plan_v3, init)
    global_base, conflict = _merge(dict(baseline), cseed)
    if conflict:
        raise AssembleError(
            [f"PLAN_UNCONSTRUCTIBLE: baseline vs constraint {c_owners.get(conflict, '')} on {conflict}"]
        )
    notes: list[str] = []
    if unseedable:
        notes.append(f"constraint_unseedable: {', '.join(unseedable)}")
    if fill.get("unreachable"):
        notes.append("ignored_llm_unreachable")
    guard_hits = _guard_hit_map(fill)
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
                unreachable.append({"obligation": oid, "reason": f"guard {gid} has no violating seed"})
                continue
            merged = dict(global_base)
            merged.update(gseed)
            rows.append(_pad_row(merged, columns, defaults, oid))
            continue

        cell = obl.get("dimensions") if isinstance(obl.get("dimensions"), dict) else {}
        merged = dict(global_base)
        conflict_col = None
        conflict_did = ""
        conflict_arm = ""
        for did, arm in cell.items():
            overlay = arm_seed.get((_s(did), _s(arm)))
            if overlay is None:
                conflict_col = f"{did}.{arm}"
                conflict_did, conflict_arm = _s(did), _s(arm)
                break
            merged, conflict_col = _merge(merged, overlay)
            if conflict_col:
                conflict_did, conflict_arm = _s(did), _s(arm)
                break
        if conflict_col:
            if conflict_col in c_owners:
                reason = (
                    f"constraint {c_owners[conflict_col]} conflicts with "
                    f"{conflict_did}.{conflict_arm} on {conflict_col}"
                )
            else:
                reason = f"seed conflict on {conflict_col}"
            unreachable.append(
                {
                    "obligation": oid,
                    "dimensions": dict(cell),
                    "reason": reason,
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
        "notes": notes,
        "stats": {
            "obligations": len(obligations),
            "rows": len(rows),
            "unreachable": len(unreachable),
            "constraint_columns": sorted(c_owners),
            "constraint_unseedable": list(unseedable),
        },
    }
