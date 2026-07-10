from __future__ import annotations

from typing import Any


def _matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if key not in actual:
            return False
        if actual[key] != value:
            return False
    return True


def _apply_constants(key: dict[str, Any], constants: dict[str, Any]) -> dict[str, Any]:
    merged = dict(key)
    for k, v in constants.items():
        merged.setdefault(k, v)
    return merged


def _violates_legal(key: dict[str, Any], rules: list[dict[str, Any]]) -> str | None:
    for rule in rules:
        cond = rule.get("if", {})
        if not isinstance(cond, dict) or not cond:
            continue
        if _matches(cond, key):
            then = rule.get("then", {})
            forbid = rule.get("forbid")
            if forbid is True:
                return rule.get("note") or rule.get("id", "unreachable rule")
            if isinstance(then, dict):
                for tk, tv in then.items():
                    if key.get(tk) is not None and key.get(tk) != tv:
                        return f"{rule.get('id')}: requires {tk}={tv}, got {key.get(tk)}"
    return None


def _family_guard_ok(candidate: dict[str, Any], factor_space: dict[str, Any]) -> str | None:
    fam_id = candidate.get("family_id") or candidate.get("expected_key", {}).get("family_id")
    if not fam_id:
        return None
    guard = (factor_space.get("family_guards", {}) or {}).get(fam_id, {})
    reach = guard.get("reachability")
    # Unreachable families are kept only as unreachable_proof targets, not as normal cases.
    if reach in ("unreachable", "excluded") and candidate.get("source") != "unreachable_proof":
        return f"family {fam_id} is {reach}"
    g = guard.get("guard", {}) or {}
    expected = candidate.get("expected_key", {}) or {}
    # Only enforce guard fields that are already present on the candidate key.
    present = {k: v for k, v in g.items() if k in expected}
    if present and not _matches(present, expected):
        return f"family guard mismatch for {fam_id}"
    # Merge missing guard fields into expected_key for better realization/probe.
    if g:
        merged = dict(expected)
        for k, v in g.items():
            merged.setdefault(k, v)
        candidate["expected_key"] = merged
    return None


def _has_realization(candidate: dict[str, Any], rule_model: dict[str, Any]) -> str | None:
    realization = rule_model.get("input_realization", {}) or {}
    expected = candidate.get("expected_key", {})
    if not expected:
        return "empty expected_key"
    missing = [f for f in expected if f not in realization and f != "family_id"]
    if missing and len(missing) == len(expected):
        return None  # allow generic realization fallback
    return None


def prune_candidates(
    raw: dict[str, Any],
    factor_space: dict[str, Any],
    rule_model: dict[str, Any],
) -> dict[str, Any]:
    constants = factor_space.get("constants", {}) or {}
    rules = rule_model.get("rules", [])
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for cand in raw.get("candidates", []):
        key = _apply_constants(dict(cand.get("expected_key", {})), constants)
        cand = {**cand, "expected_key": key}

        # L2 negatives are expected to violate rules; keep them with annotation.
        if cand.get("expect_reject") or cand.get("level") == "L2":
            valid.append(cand)
            continue

        reason = _violates_legal(key, rules)
        if reason:
            rejected.append({"candidate_id": cand["candidate_id"], "reason": reason})
            continue
        reason = _family_guard_ok(cand, factor_space)
        if reason:
            rejected.append({"candidate_id": cand["candidate_id"], "reason": reason})
            continue
        reason = _has_realization(cand, rule_model)
        if reason:
            rejected.append({"candidate_id": cand["candidate_id"], "reason": reason})
            continue
        valid.append(cand)

    return {
        "version": 1,
        "op_name": raw.get("op_name"),
        "valid": valid,
        "rejected": rejected,
        "valid_count": len(valid),
        "rejected_count": len(rejected),
    }
