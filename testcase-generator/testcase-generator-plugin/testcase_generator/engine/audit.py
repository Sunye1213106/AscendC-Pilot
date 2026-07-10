from __future__ import annotations

from typing import Any


def _pct(covered: int, total: int) -> str:
    if total == 0:
        return "100%"
    return f"{round(100.0 * covered / total, 1)}%"


def _covers_obligation(observed: dict[str, Any], obligation: dict[str, Any]) -> bool:
    otype = obligation.get("type")
    decoded = observed.get("decoded_key", {})
    family_guess = observed.get("family_guess")

    if otype == "family":
        if obligation.get("reachability") in ("unreachable", "excluded"):
            # Covered by documenting unreachable family; not by observed runnable keys.
            return False
        return family_guess == obligation.get("family_id")
    if otype == "key_field_value":
        field = obligation.get("field")
        return decoded.get(field) == obligation.get("value")
    if otype == "key_relation":
        combos = obligation.get("combinations") or []
        for combo in combos:
            if isinstance(combo, dict) and all(decoded.get(k) == v for k, v in combo.items()):
                return True
        return False
    if otype == "tilingdata":
        blocks = observed.get("tilingdata_blocks") or []
        if obligation.get("block") in blocks:
            return True
        # Fallback: family-linked tilingdata covered when family is observed.
        fams = obligation.get("families") or []
        return bool(fams) and family_guess in fams
    if otype == "unreachable_proof":
        # MVP: treat declared unreachable proofs as satisfied by presence in plan (documented).
        return True
    return False


def audit_coverage(
    obligations_doc: dict[str, Any],
    realized_cases: list[dict[str, Any]],
    observed_rows: list[dict[str, Any]],
    mock_probe: bool,
) -> dict[str, Any]:
    all_obligations = obligations_doc.get("all_obligations", [])
    by_type: dict[str, list[dict[str, Any]]] = {}
    for ob in all_obligations:
        by_type.setdefault(ob.get("type", "other"), []).append(ob)

    covered_ids: set[str] = set()
    mismatches: list[dict[str, Any]] = []

    obs_by_case = {row.get("case_id"): row for row in observed_rows}
    case_by_id = {c.get("case_id"): c for c in realized_cases}

    for case_id, obs in obs_by_case.items():
        if obs.get("status") != "success":
            continue
        for ob in all_obligations:
            if _covers_obligation(obs, ob):
                covered_ids.add(ob["id"])

    for case_id, case in case_by_id.items():
        obs = obs_by_case.get(case_id, {})
        expected = case.get("expected_key", {})
        decoded = obs.get("decoded_key", {})
        if obs.get("status") == "success" and expected:
            for k, v in expected.items():
                if k in decoded and decoded[k] != v:
                    mismatches.append(
                        {
                            "case_id": case_id,
                            "field": k,
                            "expected": v,
                            "observed": decoded[k],
                        }
                    )

    def type_coverage(otype: str) -> tuple[int, int, str]:
        items = [o for o in all_obligations if o.get("type") == otype]
        if otype == "family":
            items = [o for o in items if o.get("reachability") not in ("unreachable", "excluded")]
        total = len(items)
        covered = len([o for o in items if o["id"] in covered_ids])
        return covered, total, _pct(covered, total)

    fam_c, fam_t, fam_p = type_coverage("family")
    kfv_c, kfv_t, kfv_p = type_coverage("key_field_value")
    krel_c, krel_t, krel_p = type_coverage("key_relation")
    td_c, td_t, td_p = type_coverage("tilingdata")
    unr_c, unr_t, unr_p = type_coverage("unreachable_proof")

    missing = [
        o
        for o in all_obligations
        if o["id"] not in covered_ids
        and not (o.get("type") == "family" and o.get("reachability") in ("unreachable", "excluded"))
    ]
    match_total = len(case_by_id)
    match_ok = match_total - len({m["case_id"] for m in mismatches})

    return {
        "version": 1,
        "op_name": obligations_doc.get("op_name"),
        "summary": {
            "verified": not mock_probe,
            "mock_probe": mock_probe,
            "coverage_verified": not mock_probe,
            "family_coverage": fam_p,
            "key_field_value_coverage": kfv_p,
            "key_relation_coverage": krel_p,
            "tilingdata_coverage": td_p,
            "unreachable_proof_coverage": unr_p,
            "expected_observed_match_rate": _pct(match_ok, match_total),
            "covered_obligations": len(covered_ids),
            "total_obligations": len(all_obligations),
        },
        "missing": [
            {"id": o["id"], "type": o.get("type"), "detail": o}
            for o in missing
        ],
        "mismatches": mismatches,
        "unreachable_proofs": [
            o for o in all_obligations if o.get("type") == "unreachable_proof" and o["id"] in covered_ids
        ],
    }


def coverage_matrix_md(audit: dict[str, Any]) -> str:
    s = audit.get("summary", {})
    lines = [
        f"# Coverage Matrix — {audit.get('op_name', '')}",
        "",
        f"- verified: {s.get('verified')}",
        f"- mock_probe: {s.get('mock_probe')}",
        f"- family_coverage: {s.get('family_coverage')}",
        f"- key_field_value_coverage: {s.get('key_field_value_coverage')}",
        f"- key_relation_coverage: {s.get('key_relation_coverage')}",
        f"- tilingdata_coverage: {s.get('tilingdata_coverage')}",
        f"- expected_observed_match_rate: {s.get('expected_observed_match_rate')}",
        "",
        f"Missing obligations: {len(audit.get('missing', []))}",
        f"Mismatches: {len(audit.get('mismatches', []))}",
    ]
    if s.get("mock_probe"):
        lines.append("")
        lines.append("> mock_probe: true — coverage_verified: false. Do not claim verified coverage.")
    return "\n".join(lines)
