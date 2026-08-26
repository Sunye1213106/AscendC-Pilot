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
GUARD_TARGET_INCONSISTENT = "GUARD_TARGET_INCONSISTENT"
PLAN_PROSE_CONTRACT_DRIFT = "PLAN_PROSE_CONTRACT_DRIFT"
PRIMARY_BEHAVIOR_UNCOVERED = "PRIMARY_BEHAVIOR_UNCOVERED"
REPLAY_NAMESPACE_MISUSE = "REPLAY_NAMESPACE_MISUSE"
TARGET_NOT_CHANGED = "TARGET_NOT_CHANGED"

_UNTESTABLE_KINDS = frozenset({"opaque", "control_gap", "harness_gap"})
_DERIVED_OR_ENV_KINDS = frozenset({"derived", "constraint", "environment", "env", "fact"})
_DERIVED_REASON_MARKERS = (
    "非列",
    "non-column",
    "not a column",
    "派生",
    "platform constant",
    "environment",
    "aicnum",
    "corenum",
)
_DEFAULT_EXPECTED = frozenset(
    {0, "0", 0.0, False, "false", "False", "DISABLED", "disabled", "OFF", "off", "NONE", "none"}
)
_ACTIVE_VALUES = frozenset({1, "1", True, "true", "True", "ON", "on", "ENABLED", "enabled"})

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

    for idx, row in enumerate(fence.get("constraints") or []):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip() or f"constraints[{idx}]"
        pred = row.get("predicate") if row.get("predicate") is not None else row.get("expr")
        for col in _case_fields(pred):
            if col.lower() not in allowed:
                errors.append(
                    f"{CONTROL_GAP}: {cid}: case field {col!r} is not an init.yaml column"
                )
            elif mapping is not None:
                mrow = _mapping_row_for(mapping, col)
                if not is_bound_control(mrow):
                    errors.append(
                        f"{CONTROL_GAP}: {cid}: case field {col!r} is not confirmed+active; "
                        "mark untestable + needs_binding"
                    )
        for field in predicate_fields(pred):
            err = _check_observe_field(field, owner=cid)
            if err:
                errors.append(err)
            else:
                errors.extend(_observe_vocab_error(field, owner=cid, observe_fields=observe_fields))

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


def validate_plan_semantics(
    fence: dict[str, Any],
    *,
    primary_observations: set[str] | None = None,
) -> list[str]:
    """Semantic Plan contract. Static; does not run Replay."""
    from testcase_agent.coverage.predicate import validate_predicate

    errors: list[str] = []
    errors.extend(_validate_constraints(fence, validate_predicate))
    errors.extend(_validate_environment(fence))
    errors.extend(_validate_untestable_kinds(fence))
    errors.extend(_validate_guard_target_consistency(fence))
    errors.extend(_validate_classifier_requires(fence))
    errors.extend(_validate_primary_behavior(fence, primary_observations=primary_observations))
    return errors


def _validate_constraints(fence: dict[str, Any], validate_predicate: Any) -> list[str]:
    rows = fence.get("constraints")
    if rows is None:
        return []
    if not isinstance(rows, list):
        return [f"{PLAN_INVALID}: constraints must be a list"]
    errors: list[str] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{PLAN_INVALID}: constraints[{idx}] is not a mapping")
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            errors.append(f"{PLAN_INVALID}: constraints[{idx}] missing id")
        elif cid in seen:
            errors.append(f"{PLAN_INVALID}: duplicate constraint id {cid}")
        if cid:
            seen.add(cid)
        pred = row.get("predicate") if row.get("predicate") is not None else row.get("expr")
        owner = cid or f"constraints[{idx}]"
        if pred is None:
            errors.append(f"{PLAN_INVALID}: {owner} missing predicate")
        else:
            errors.extend(validate_predicate(pred, path=f"constraints.{owner}"))
    return errors


def _validate_environment(fence: dict[str, Any]) -> list[str]:
    env = fence.get("environment")
    if env is None:
        return []
    if isinstance(env, dict):
        return []
    if not isinstance(env, list):
        return [f"{PLAN_INVALID}: environment must be a list or mapping"]
    errors: list[str] = []
    for idx, row in enumerate(env):
        if isinstance(row, dict):
            label = str(row.get("id") or row.get("name") or row.get("fact") or "").strip()
            if not label:
                errors.append(f"{PLAN_INVALID}: environment[{idx}] missing id/name/fact")
        elif not str(row or "").strip():
            errors.append(f"{PLAN_INVALID}: environment[{idx}] empty")
    return errors


def _validate_untestable_kinds(fence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for idx, row in enumerate(fence.get("untestable") or []):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        reason = str(row.get("reason") or "")
        owner = str(row.get("id") or "").strip() or f"untestable[{idx}]"
        if kind in _DERIVED_OR_ENV_KINDS:
            errors.append(
                f"{PLAN_INVALID}: {owner} kind {kind!r} is derived/environment; "
                "write constraints: or environment:, not untestable"
            )
            continue
        if kind and kind not in _UNTESTABLE_KINDS:
            errors.append(
                f"{PLAN_INVALID}: {owner} kind {kind!r} must be opaque|control_gap|harness_gap"
            )
            continue
        if not kind:
            blob = f"{owner} {reason}".lower()
            if any(marker.lower() in blob or marker in reason for marker in _DERIVED_REASON_MARKERS):
                errors.append(
                    f"{PLAN_INVALID}: {owner} looks derived/environment; "
                    "write constraints: or environment:, not untestable"
                )
    return errors


def _is_default_expected(expected: Any) -> bool:
    if expected is None:
        return False
    if isinstance(expected, (list, tuple, set, dict)):
        return False
    if isinstance(expected, float) and expected == 0.0:
        return True
    return expected in _DEFAULT_EXPECTED


def _target_asserts_default(target: dict[str, Any]) -> bool:
    evidence = target.get("evidence") if isinstance(target.get("evidence"), dict) else {}
    kind = str(evidence.get("kind") or "").strip()
    if kind == "replay_field":
        return _is_default_expected(evidence.get("expected"))
    if kind == "derived":
        pred = evidence.get("predicate") or evidence.get("expr")
        if isinstance(pred, dict) and str(pred.get("op") or "").lower() == "eq":
            return _is_default_expected(pred.get("value"))
        return False
    return False


def _predicate_has_activation_eq(pred: Any) -> bool:
    if not isinstance(pred, dict):
        return False
    op = str(pred.get("op") or "").lower()
    if op == "eq":
        field = str(pred.get("field") or "")
        return field.startswith("case.") and pred.get("value") in _ACTIVE_VALUES
    if op in {"and", "or"}:
        return any(_predicate_has_activation_eq(item) for item in (pred.get("args") or []))
    if op == "not":
        return _predicate_has_activation_eq(pred.get("arg"))
    return False


def _validate_guard_target_consistency(fence: dict[str, Any]) -> list[str]:
    """L3 Guard on an activation gate must not bind a Target whose expected is the default."""
    targets = {
        str(row.get("id") or "").strip(): row
        for row in (fence.get("targets") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    guards = {
        str(row.get("id") or "").strip(): row
        for row in (fence.get("guards") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    cov = fence.get("coverage") if isinstance(fence.get("coverage"), dict) else {}
    l3_ids = [gid for gid in _dim_refs(cov.get("L3")) if gid]
    errors: list[str] = []
    for gid in l3_ids:
        guard = guards.get(gid) or {}
        tid = str(guard.get("target") or "").strip()
        target = targets.get(tid) or {}
        if not target:
            continue
        if _target_asserts_default(target) and _predicate_has_activation_eq(guard.get("predicate")):
            errors.append(
                f"{GUARD_TARGET_INCONSISTENT}: {gid} activates the Target path "
                f"but {tid} expects the default/DISABLED value; invert the Target evidence"
            )
    return errors


def _validate_classifier_requires(fence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for did, dim in _dim_map(fence).items():
        classifier = dim.get("classifier") if isinstance(dim.get("classifier"), dict) else {}
        part_fields: set[str] = set()
        for part in dim.get("partitions") or []:
            if isinstance(part, dict):
                part_fields.update(predicate_fields(part.get("predicate")))
        for raw in classifier.get("requires") or []:
            req = str(raw or "").strip()
            if req.startswith("replay.") and req not in part_fields:
                errors.append(
                    f"{PLAN_INVALID}: {did}.classifier.requires {req!r} is Target evidence, "
                    "not a partition field"
                )
    return errors


def _target_covers_observation(target: dict[str, Any], obs: str) -> bool:
    evidence = target.get("evidence") if isinstance(target.get("evidence"), dict) else {}
    blob = json.dumps(
        {
            "id": target.get("id"),
            "field": evidence.get("field"),
            "expected": evidence.get("expected"),
            "predicate": evidence.get("predicate") or evidence.get("expr"),
        },
        default=str,
    )
    if obs not in blob and obs not in str(evidence.get("field") or ""):
        return False
    if _target_asserts_default(target):
        return False
    return True


def _blocking_test_harness_gap(fence: dict[str, Any]) -> bool:
    block = fence.get("test_harness_gap")
    if not isinstance(block, dict) or not block:
        block = fence.get("harness_intent")
    if not isinstance(block, dict) or not block:
        return False
    return not bool(block.get("done"))


def _validate_primary_behavior(
    fence: dict[str, Any],
    *,
    primary_observations: set[str] | None,
) -> list[str]:
    observations = {str(x).strip() for x in (primary_observations or set()) if str(x).strip()}
    blocking = _blocking_test_harness_gap(fence)
    untestable_blob = json.dumps(fence.get("untestable") or [], default=str)
    targets = [row for row in (fence.get("targets") or []) if isinstance(row, dict)]

    # Heuristic: a default-only Target plus untestable mentioning the same replay field
    # is uncovered primary behavior even without an explicit observation list.
    if not observations:
        for target in targets:
            if not _target_asserts_default(target):
                continue
            evidence = target.get("evidence") if isinstance(target.get("evidence"), dict) else {}
            symbol = replay_symbol(str(evidence.get("field") or ""))
            if not symbol:
                continue
            if symbol in untestable_blob and not blocking:
                observations.add(symbol)

    if not observations:
        return []

    errors: list[str] = []
    for obs in sorted(observations):
        if any(_target_covers_observation(target, obs) for target in targets):
            continue
        in_untestable = obs in untestable_blob
        if in_untestable and blocking:
            continue
        if in_untestable:
            errors.append(
                f"{PRIMARY_BEHAVIOR_UNCOVERED}: {obs} is untestable without a blocking "
                "test_harness_gap"
            )
            continue
        errors.append(
            f"{PRIMARY_BEHAVIOR_UNCOVERED}: {obs} has no executable Target "
            "(non-default evidence) or blocking test_harness_gap"
        )
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
    hint = _nearest_replay_names(symbol, allowed)
    tail = f"; 词表里最接近的是 {hint}" if hint else ""
    return [
        f"{OBSERVATION_GAP}: {owner}: replay field {name!r} is not a known Replay/TilingData field"
        f"{tail}"
    ]


def _nearest_replay_names(symbol: str, allowed: set[str], *, limit: int = 3) -> str:
    """Legal names sharing a case-insensitive fragment with the rejected one."""
    needle = symbol.lower()
    scored: list[tuple[int, str]] = []
    for cand in allowed:
        low = cand.lower()
        if low == needle:
            continue
        overlap = 0
        for size in range(min(len(needle), len(low)), 3, -1):
            if any(needle[i : i + size] in low for i in range(len(needle) - size + 1)):
                overlap = size
                break
        if overlap:
            scored.append((-overlap, cand))
    if not scored:
        return ""
    scored.sort()
    return ", ".join(name for _, name in scored[:limit])


def _packet_catalog(packet: dict[str, Any] | None) -> dict[str, Any]:
    doc = packet if isinstance(packet, dict) else {}
    cat = doc.get("observation_catalog")
    return cat if isinstance(cat, dict) else {}


def validate_against_packet(
    fence: dict[str, Any],
    packet: dict[str, Any] | None,
) -> list[str]:
    """Plan claims checked against what the scope packet actually declared.

    Two failure modes are cheap to catch here and expensive later: naming a
    dispatch entity under ``replay.`` (it has no TilingData leaf to decode), and
    pointing a pr_regression Target at an assignment the pin never touched.
    """
    doc = packet if isinstance(packet, dict) else {}
    if not doc:
        return []
    catalog = _packet_catalog(doc)
    errors: list[str] = []

    forbidden = {}
    for row in catalog.get("replay_forbidden") or []:
        if isinstance(row, dict) and str(row.get("name") or "").strip():
            forbidden[str(row["name"]).strip()] = row
    if forbidden:
        for owner, field in _all_replay_refs(fence):
            symbol = replay_symbol(field)
            if symbol and symbol in forbidden:
                row = forbidden[symbol]
                errors.append(
                    f"{REPLAY_NAMESPACE_MISUSE}: {owner}: {symbol!r} is a "
                    f"{row.get('kind') or 'dispatch'} entity, not a TilingData leaf; "
                    "use evidence kind dispatch_map or observe the writing helper's probe.*"
                )

    candidates = doc.get("behavior_candidates")
    if isinstance(candidates, list) and candidates:
        changed: set[str] = set()
        for row in candidates:
            if not isinstance(row, dict):
                continue
            name = str(row.get("symbol") or "").strip()
            if name:
                changed.add(name)
        kind = str(
            (doc.get("change_contract") or {}).get("kind")
            if isinstance(doc.get("change_contract"), dict)
            else ""
        ).strip()
        if kind == "pr_regression":
            for row in fence.get("targets") or []:
                if not isinstance(row, dict):
                    continue
                tid = str(row.get("id") or "").strip() or "target"
                names = {
                    replay_symbol(f)
                    for _owner, f in _target_replay_refs(tid, row)
                }
                names = {n for n in names if n}
                if not names:
                    continue
                if not (names & changed):
                    errors.append(
                        f"{TARGET_NOT_CHANGED}: {tid}: observes {sorted(names)} but the pin's "
                        "behavior_candidates are "
                        f"{sorted(changed)[:8]}; a pr_regression Target must point at an "
                        "assignment this change introduced or rewired"
                    )
    return errors


def _target_replay_refs(tid: str, row: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    field = str(evidence.get("field") or "").strip()
    if field:
        out.append((tid, field))
    pred = evidence.get("predicate") if evidence.get("predicate") is not None else evidence.get("expr")
    for item in predicate_fields(pred):
        out.append((tid, str(item)))
    return out


def _all_replay_refs(fence: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for row in fence.get("targets") or []:
        if isinstance(row, dict):
            out.extend(_target_replay_refs(str(row.get("id") or "target"), row))
    for row in fence.get("dimensions") or []:
        if not isinstance(row, dict):
            continue
        did = str(row.get("id") or "dimension")
        classifier = row.get("classifier") if isinstance(row.get("classifier"), dict) else {}
        for raw in classifier.get("requires") or []:
            out.append((f"{did}.classifier", str(raw)))
        for part in row.get("partitions") or []:
            if not isinstance(part, dict):
                continue
            pid = str(part.get("id") or "partition")
            for item in predicate_fields(part.get("predicate")):
                out.append((f"{did}.{pid}", str(item)))
    for row in fence.get("guards") or []:
        if not isinstance(row, dict):
            continue
        gid = str(row.get("id") or "guard")
        for item in predicate_fields(row.get("predicate")):
            out.append((gid, str(item)))
    for row in fence.get("constraints") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "constraint")
        pred = row.get("predicate") if row.get("predicate") is not None else row.get("expr")
        for item in predicate_fields(pred):
            out.append((cid, str(item)))
    return out


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
