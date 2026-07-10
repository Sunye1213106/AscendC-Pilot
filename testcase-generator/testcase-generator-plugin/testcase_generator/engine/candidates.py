from __future__ import annotations

from itertools import combinations, product
from typing import Any


def _candidate_id(prefix: str, idx: int) -> str:
    return f"{prefix}{idx:03d}"


def _key_snapshot_from_obligation(obligation: dict[str, Any]) -> dict[str, Any]:
    otype = obligation.get("type")
    if otype == "key_field_value":
        return {obligation.get("field", ""): obligation.get("value")}
    if otype == "family":
        return {"family_id": obligation.get("family_id")}
    if otype == "key_relation":
        combos = obligation.get("combinations") or []
        if combos and isinstance(combos[0], dict):
            return dict(combos[0])
        return {"relation": obligation.get("name")}
    if otype == "tilingdata":
        snap: dict[str, Any] = {"tilingdata_block": obligation.get("block")}
        for field in obligation.get("fields", [])[:1]:
            snap[field] = True
        return snap
    if otype == "unreachable_proof":
        return {"unreachable": obligation.get("constraint")}
    return {}


def _seed_candidates(seed_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, seed in enumerate(seed_cases, start=1):
        out.append(
            {
                "candidate_id": seed.get("id") or _candidate_id("S", idx),
                "source": "seed",
                "family_id": seed.get("family_id"),
                "expected_key": seed.get("key_snapshot", {}),
                "covers": [f"seed:{seed.get('id', idx)}"],
                "level": "L0",
                "expect_reject": False,
            }
        )
    return out


def _family_rep_candidates(factor_space: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    idx = 1
    for fam_id, fam in (factor_space.get("family_guards", {}) or {}).items():
        reach = fam.get("reachability", "unknown")
        if reach in ("unreachable", "excluded"):
            continue
        snap = dict(fam.get("guard", {}) or {})
        snap["family_id"] = fam_id
        # Prefer first value from key_pattern lists when present
        for k, v in (fam.get("key_pattern", {}) or {}).items():
            if k not in snap:
                snap[k] = v[0] if isinstance(v, list) and v else v
        out.append(
            {
                "candidate_id": _candidate_id("F", idx),
                "source": "family_rep",
                "family_id": fam_id,
                "expected_key": snap,
                "covers": [f"family_rep:{fam_id}"],
                "level": "L0",
                "expect_reject": False,
            }
        )
        idx += 1
    return out


def _critical_single_field_candidates(factor_space: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    fields = factor_space.get("tiling_key_fields", {}) or {}
    critical = factor_space.get("critical_single_fields", []) or []
    idx = 1
    for name in critical:
        spec = fields.get(name) or {}
        domain = spec.get("domain") or []
        if name in (factor_space.get("numeric_overlay") or {}) and not domain:
            domain = [True]
        for value in domain[:3]:
            out.append(
                {
                    "candidate_id": _candidate_id("K", idx),
                    "source": "critical_single",
                    "family_id": None,
                    "expected_key": {name: value},
                    "covers": [f"critical:{name}={value}"],
                    "level": "L0",
                    "expect_reject": False,
                }
            )
            idx += 1
    return out


def _targeted_candidates(obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, ob in enumerate(obligations, start=1):
        otype = ob.get("type")
        if otype == "unreachable_proof":
            continue
        if otype == "family" and ob.get("reachability") in ("unreachable", "excluded"):
            continue
        snap = _key_snapshot_from_obligation(ob)
        fam_id = ob.get("family_id") or snap.get("family_id")
        if otype == "tilingdata" and ob.get("families"):
            fam_id = fam_id or ob["families"][0]
            snap.setdefault("family_id", fam_id)
        out.append(
            {
                "candidate_id": _candidate_id("C", idx),
                "source": "targeted",
                "family_id": fam_id,
                "expected_key": snap,
                "covers": [ob.get("id", f"obligation_{idx}")],
                "level": "L1",
                "expect_reject": False,
            }
        )
    return out


def _pairwise_candidates(factor_space: dict[str, Any], levels: set[str]) -> list[dict[str, Any]]:
    """L1 pairwise within family-local domains. Not L2."""
    if "L1" not in levels and "PAIRWISE" not in levels:
        return []

    fields = factor_space.get("tiling_key_fields", {}) or {}
    solver = factor_space.get("solver", {}) or {}
    preferred = solver.get("pairwise_candidate_fields") or [
        n for n, spec in fields.items() if spec.get("domain") and spec.get("constant") is None
    ]
    names = [n for n in preferred if n in fields and fields[n].get("domain")][:4]
    if len(names) < 2:
        return []

    out: list[dict[str, Any]] = []
    idx = 1
    # Pairwise: all 2-field combinations, limited domain values
    for a, b in combinations(names, 2):
        da = list(fields[a]["domain"])[:3]
        db = list(fields[b]["domain"])[:3]
        for va, vb in product(da, db):
            snap = {a: va, b: vb}
            out.append(
                {
                    "candidate_id": _candidate_id("P", idx),
                    "source": "pairwise",
                    "family_id": None,
                    "expected_key": snap,
                    "covers": [f"pairwise:{a}x{b}"],
                    "level": "L1",
                    "expect_reject": False,
                }
            )
            idx += 1
            if idx > 40:
                return out

    # Also try family-local pairwise: inject family guard then pair
    for fam_id, fam in (factor_space.get("family_guards", {}) or {}).items():
        if fam.get("reachability") in ("unreachable", "excluded"):
            continue
        guard = dict(fam.get("guard", {}) or {})
        local_names = [n for n in names if n not in guard][:2]
        if len(local_names) < 2:
            continue
        a, b = local_names[0], local_names[1]
        for va, vb in product(list(fields[a]["domain"])[:2], list(fields[b]["domain"])[:2]):
            snap = {**guard, a: va, b: vb, "family_id": fam_id}
            out.append(
                {
                    "candidate_id": _candidate_id("P", idx),
                    "source": "pairwise_family_local",
                    "family_id": fam_id,
                    "expected_key": snap,
                    "covers": [f"pairwise:{fam_id}:{a}x{b}"],
                    "level": "L1",
                    "expect_reject": False,
                }
            )
            idx += 1
            if idx > 60:
                return out
    return out


def _l2_negative_candidates(
    obligations_doc: dict[str, Any],
    factor_space: dict[str, Any],
    rule_model: dict[str, Any],
) -> list[dict[str, Any]]:
    """L2 = unreachable proofs + intentional legal violations (expect_reject)."""
    out: list[dict[str, Any]] = []
    idx = 1

    for ob in obligations_doc.get("unreachable_proof_obligations", []) or []:
        constraint = ob.get("constraint")
        snap: dict[str, Any]
        if isinstance(constraint, dict):
            snap = dict(constraint)
        elif isinstance(constraint, str) and constraint.startswith("family:"):
            snap = {"family_id": constraint.split(":", 1)[1]}
        else:
            snap = {"unreachable": constraint}
        out.append(
            {
                "candidate_id": _candidate_id("N", idx),
                "source": "unreachable_proof",
                "family_id": snap.get("family_id"),
                "expected_key": snap,
                "covers": [ob.get("id", f"unr_{idx}")],
                "level": "L2",
                "expect_reject": True,
            }
        )
        idx += 1

    # Intentional legal violations for documentation / negative dry-run
    for rule in rule_model.get("constraints", rule_model.get("rules", [])) or []:
        if rule.get("type") != "legal":
            continue
        cond = rule.get("if", {})
        then = rule.get("then", {})
        if not isinstance(cond, dict) or not isinstance(then, dict) or not then:
            continue
        # Build a key that satisfies if but violates first then-field
        snap = dict(cond)
        for tk, tv in then.items():
            if isinstance(tv, (int, float, bool, str)):
                # flip simple enums: prefer 1 if required 0, else 0
                snap[tk] = 1 if tv == 0 else 0
                break
        out.append(
            {
                "candidate_id": _candidate_id("N", idx),
                "source": "legal_violation",
                "family_id": None,
                "expected_key": snap,
                "covers": [f"neg:{rule.get('id')}"],
                "level": "L2",
                "expect_reject": True,
            }
        )
        idx += 1
        if idx > 20:
            break
    return out


def build_candidates(
    obligations_doc: dict[str, Any],
    factor_space: dict[str, Any],
    levels: list[str] | None = None,
    rule_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    level_set = {x.strip().upper() for x in (levels or ["L0", "L1"])}
    all_obligations = obligations_doc.get("all_obligations", [])
    seed_cases = obligations_doc.get("seed_cases", [])
    rule_model = rule_model or {}

    candidates: list[dict[str, Any]] = []
    if "L0" in level_set:
        candidates.extend(_seed_candidates(seed_cases))
        candidates.extend(_family_rep_candidates(factor_space))
        candidates.extend(_critical_single_field_candidates(factor_space))
    if "L1" in level_set:
        candidates.extend(_targeted_candidates(all_obligations))
        candidates.extend(_pairwise_candidates(factor_space, level_set))
    if "L2" in level_set:
        candidates.extend(_l2_negative_candidates(obligations_doc, factor_space, rule_model))

    return {
        "version": 1,
        "op_name": obligations_doc.get("op_name"),
        "levels": sorted(level_set),
        "level_semantics": {
            "L0": "threshold: seed + family reps + critical single-field",
            "L1": "functional: targeted obligations + pairwise",
            "L2": "negative/unreachable proofs (not pairwise)",
        },
        "candidates": candidates,
        "count": len(candidates),
        "counts_by_level": {
            "L0": len([c for c in candidates if c.get("level") == "L0"]),
            "L1": len([c for c in candidates if c.get("level") == "L1"]),
            "L2": len([c for c in candidates if c.get("level") == "L2"]),
        },
    }
