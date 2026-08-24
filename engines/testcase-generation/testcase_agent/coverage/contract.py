# -*- coding: utf-8 -*-
"""Plan → Solve executability contract. Validator proves; compiler must not repair."""

from __future__ import annotations

import json
from typing import Any

from .predicate import predicate_fields

CASE_REFINABLE = "CASE_REFINABLE"
CONTROL_GAP = "HARNESS_CONTROL_GAP"
OBSERVATION_GAP = "HARNESS_OBSERVATION_GAP"
PLAN_INVALID = "PLAN_INVALID"

_OBSERVE_PREFIXES = ("case.", "replay.", "probe.")
_REPLAY_ENVELOPE = frozenset({"tiling_key", "key", "ok", "reject"})


def case_column(field: str) -> str | None:
    name = str(field or "").strip()
    if name.startswith("case."):
        col = name[5:].strip()
        return col or None
    return None


def replay_symbol(field: str) -> str | None:
    name = str(field or "").strip()
    if name.startswith("replay."):
        rest = name[7:].strip()
        return rest or None
    if name.startswith(_OBSERVE_PREFIXES) or "." in name:
        return None
    return name or None


def _dim_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in plan.get("dimensions") or []:
        if isinstance(row, dict) and str(row.get("id") or "").strip():
            out[str(row["id"]).strip()] = row
    return out


def _target_ids(plan: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for row in plan.get("targets") or []:
        if isinstance(row, dict):
            tid = str(row.get("id") or "").strip()
            if tid:
                out.append(tid)
    return out


def _dim_refs(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        raw = raw.get("dimensions") or raw.get("dims") or raw.get("guards") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            out.extend(_dim_refs(item.get("dims") or item.get("dimensions") or item.get("id")))
        elif isinstance(item, list):
            out.extend(str(x).strip() for x in item if str(x).strip())
        else:
            vid = str(item or "").strip()
            if vid:
                out.append(vid)
    return out


def _case_fields(pred: Any) -> set[str]:
    cols: set[str] = set()
    for field in predicate_fields(pred):
        col = case_column(field)
        if col:
            cols.add(col)
    return cols


def _eq_in_domain(pred: Any) -> tuple[str, set[Any], bool] | None:
    """Return (field, values, negated) for a simple eq/in leaf, else None."""
    if not isinstance(pred, dict):
        return None
    op = str(pred.get("op") or "").lower()
    if op == "not":
        inner = _eq_in_domain(pred.get("arg"))
        if inner is None:
            return None
        field, values, negated = inner
        return field, values, not negated
    field = str(pred.get("field") or "").strip()
    if not field:
        return None
    if op == "eq":
        if "value" not in pred:
            return None
        return field, {pred.get("value")}, False
    if op == "in":
        values = pred.get("values")
        if not isinstance(values, list) or not values:
            return None
        return field, set(values), False
    return None


def partition_overlap_errors(dim: dict[str, Any]) -> list[str]:
    did = str(dim.get("id") or "").strip() or "dimension"
    parts = [p for p in (dim.get("partitions") or []) if isinstance(p, dict)]
    errors: list[str] = []
    keys: list[tuple[str, str]] = []
    domains: list[tuple[str, tuple[str, set[Any], bool] | None]] = []
    for part in parts:
        pid = str(part.get("id") or "").strip()
        pred = part.get("predicate")
        keys.append((pid, json.dumps(pred, sort_keys=True, default=str)))
        domains.append((pid, _eq_in_domain(pred)))
    for i, (pid_a, key_a) in enumerate(keys):
        for pid_b, key_b in keys[i + 1 :]:
            if pid_a and pid_b and key_a == key_b:
                errors.append(f"{PLAN_INVALID}: {did}: partitions {pid_a} and {pid_b} overlap")
    for i, (pid_a, dom_a) in enumerate(domains):
        if dom_a is None:
            continue
        field_a, vals_a, neg_a = dom_a
        for pid_b, dom_b in domains[i + 1 :]:
            if dom_b is None:
                continue
            field_b, vals_b, neg_b = dom_b
            if field_a != field_b or neg_a != neg_b:
                continue
            if vals_a & vals_b:
                errors.append(f"{PLAN_INVALID}: {did}: partitions {pid_a} and {pid_b} overlap")
    return errors


def validate_executability(
    fence: dict[str, Any],
    *,
    init_columns: list[str],
    mapping: dict[str, Any] | None = None,
    observe_fields: set[str] | None = None,
) -> list[str]:
    """Structural + construct/observe contract. Does not repair."""
    from testcase_agent.products import is_bound_control, _mapping_row_for, _check_observe_field

    errors: list[str] = []
    allowed = {c.lower() for c in init_columns}
    extra = {str(c).strip().lower() for c in (fence.get("added_columns") or []) if str(c).strip()}
    allowed |= extra
    dims = _dim_map(fence)
    target_ids = _target_ids(fence)
    target_set = set(target_ids)

    pointed: set[str] = set()
    dim_case_fields: dict[str, set[str]] = {}
    for did, dim in dims.items():
        tgt = str(dim.get("target") or "").strip()
        if not tgt:
            errors.append(f"{PLAN_INVALID}: {did}: target required")
        elif tgt not in target_set:
            errors.append(f"{PLAN_INVALID}: {did}: target {tgt!r} is not a declared Target")
        else:
            pointed.add(tgt)
        controls = {str(c).strip() for c in (dim.get("controls") or []) if str(c).strip()}
        union_case: set[str] | None = None
        for part in dim.get("partitions") or []:
            if not isinstance(part, dict):
                continue
            pid = str(part.get("id") or "").strip() or "partition"
            pred = part.get("predicate")
            cols = _case_fields(pred)
            if union_case is None:
                union_case = set(cols)
            elif cols != union_case:
                errors.append(
                    f"{PLAN_INVALID}: {did}: partitions must cut the same case columns "
                    f"(H6); {pid} uses {sorted(cols)} vs {sorted(union_case)}"
                )
            for col in cols:
                if col.lower() not in allowed:
                    errors.append(
                        f"{CONTROL_GAP}: {did}.{pid}: case field {col!r} is not an init.yaml column"
                    )
                    continue
                if col not in controls and col.lower() not in {c.lower() for c in controls}:
                    errors.append(
                        f"{CONTROL_GAP}: {did}.{pid}: case field {col!r} must be listed in controls"
                    )
                if mapping is not None:
                    mrow = _mapping_row_for(mapping, col)
                    if not is_bound_control(mrow):
                        errors.append(
                            f"{CONTROL_GAP}: {did}.{pid}: case field {col!r} is not confirmed+active; "
                            "mark untestable + needs_binding"
                        )
            for field in predicate_fields(pred):
                err = _check_observe_field(field, owner=f"{did}.{pid}")
                if err:
                    errors.append(err)
                    continue
                errors.extend(
                    _observe_vocab_error(field, owner=f"{did}.{pid}", observe_fields=observe_fields)
                )
        classifier = dim.get("classifier") if isinstance(dim.get("classifier"), dict) else {}
        for raw in classifier.get("requires") or []:
            field = str(raw or "").strip()
            err = _check_observe_field(field, owner=f"{did}.classifier")
            if err:
                errors.append(err)
            else:
                errors.extend(
                    _observe_vocab_error(field, owner=f"{did}.classifier", observe_fields=observe_fields)
                )
        dim_case_fields[did] = union_case or set()
        errors.extend(partition_overlap_errors(dim))

    if dims:
        for tid in target_ids:
            if tid not in pointed:
                errors.append(
                    f"{PLAN_INVALID}: target {tid} is not pointed to by any Dimension (H2)"
                )

    for idx, row in enumerate(fence.get("untestable") or []):
        if not isinstance(row, dict):
            continue
        uid = str(row.get("id") or "").strip()
        if uid and uid in target_set:
            errors.append(f"{PLAN_INVALID}: untestable[{idx}] id {uid} overlaps targets (H2b)")

    for row in fence.get("guards") or []:
        if not isinstance(row, dict):
            continue
        gid = str(row.get("id") or "").strip() or "guard"
        controls = {str(c).strip() for c in (row.get("controls") or []) if str(c).strip()}
        pred = row.get("predicate")
        for col in _case_fields(pred):
            if col.lower() not in allowed:
                errors.append(f"{CONTROL_GAP}: {gid}: case field {col!r} is not an init.yaml column")
                continue
            if col not in controls and col.lower() not in {c.lower() for c in controls}:
                errors.append(f"{CONTROL_GAP}: {gid}: case field {col!r} must be listed in controls")
            if mapping is not None:
                mrow = _mapping_row_for(mapping, col)
                if not is_bound_control(mrow):
                    errors.append(
                        f"{CONTROL_GAP}: {gid}: case field {col!r} is not confirmed+active; "
                        "mark untestable + needs_binding"
                    )
        for field in predicate_fields(pred):
            err = _check_observe_field(field, owner=gid)
            if err:
                errors.append(err)
            else:
                errors.extend(_observe_vocab_error(field, owner=gid, observe_fields=observe_fields))

    for row in fence.get("targets") or []:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("id") or "").strip() or "target"
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        kind = str(evidence.get("kind") or "").strip()
        field = str(evidence.get("field") or "").strip()
        if field:
            errors.extend(_observe_vocab_error(field, owner=tid, observe_fields=observe_fields))
        if kind == "derived":
            pred = evidence.get("predicate") or evidence.get("expr")
            for col in _case_fields(pred):
                if col.lower() not in allowed:
                    errors.append(
                        f"{CONTROL_GAP}: {tid}: case field {col!r} is not an init.yaml column"
                    )
                elif mapping is not None:
                    mrow = _mapping_row_for(mapping, col)
                    if not is_bound_control(mrow):
                        errors.append(
                            f"{CONTROL_GAP}: {tid}: case field {col!r} is not confirmed+active; "
                            "mark untestable + needs_binding"
                        )
            for item in predicate_fields(pred):
                errors.extend(_observe_vocab_error(item, owner=tid, observe_fields=observe_fields))

    cov = fence.get("coverage") if isinstance(fence.get("coverage"), dict) else {}
    l1 = cov.get("L1")
    combos = (l1.get("combinations") if isinstance(l1, dict) else l1) or []
    if isinstance(combos, list):
        for combo in combos:
            ids = _dim_refs(combo)
            if not ids:
                continue
            if len(ids) != 2 or len(set(ids)) != 2:
                errors.append(
                    f"{PLAN_INVALID}: coverage.L1 must name exactly two unique Dimensions, got {ids}"
                )
            errors.extend(_combo_target_and_h7(ids, dims, dim_case_fields, level="L1"))
    l2_raw = cov.get("L2")
    tuples = (l2_raw.get("tuples") or l2_raw.get("combinations") or []) if isinstance(l2_raw, dict) else (l2_raw or [])
    if isinstance(tuples, list):
        for item in tuples:
            ids = _dim_refs(item)
            if not ids:
                continue
            if len(ids) < 3 or len(set(ids)) != len(ids):
                errors.append(
                    f"{PLAN_INVALID}: coverage.L2 must name unique Dimensions (len>=3), got {ids}"
                )
            errors.extend(_combo_target_and_h7(ids, dims, dim_case_fields, level="L2"))
    return errors


def _combo_target_and_h7(
    ids: list[str],
    dims: dict[str, dict[str, Any]],
    dim_case_fields: dict[str, set[str]],
    *,
    level: str,
) -> list[str]:
    errors: list[str] = []
    targets: list[str] = []
    for did in ids:
        dim = dims.get(did) or {}
        tgt = str(dim.get("target") or "").strip()
        if tgt:
            targets.append(tgt)
    if len(set(targets)) > 1:
        errors.append(
            f"{PLAN_INVALID}: coverage.{level} Dimensions {ids} belong to different Targets {targets}"
        )
    seen: dict[str, str] = {}
    for did in ids:
        for col in dim_case_fields.get(did) or set():
            other = seen.get(col.lower())
            if other and other != did:
                errors.append(
                    f"{PLAN_INVALID}: coverage.{level} Dimensions {other} and {did} both constrain {col!r} (H7)"
                )
            seen[col.lower()] = did
    return errors


def _observe_vocab_error(field: str, *, owner: str, observe_fields: set[str] | None) -> list[str]:
    if observe_fields is None:
        return []
    name = str(field or "").strip()
    if not name or name.startswith("case.") or name.startswith("probe."):
        return []
    if not name.startswith("replay.") and "." in name:
        return []
    symbol = replay_symbol(name)
    if not symbol:
        return []
    allowed = {str(x).strip() for x in observe_fields if str(x).strip()} | set(_REPLAY_ENVELOPE)
    if symbol in allowed:
        return []
    return [
        f"{OBSERVATION_GAP}: {owner}: replay field {name!r} is not a known Replay/TilingData field"
    ]


def obligation_identity(row: dict[str, Any]) -> str:
    payload = {
        "level": row.get("level"),
        "kind": row.get("kind"),
        "target": row.get("target"),
        "dimensions": row.get("dimensions"),
        "expected": row.get("expected"),
        "tiling_key": row.get("tiling_key"),
        "guard": row.get("guard"),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    import hashlib

    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
