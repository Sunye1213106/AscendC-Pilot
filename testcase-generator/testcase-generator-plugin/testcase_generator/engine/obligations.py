from __future__ import annotations

from typing import Any


def _obligation_id(prefix: str, idx: int) -> str:
    return f"{prefix}_{idx:03d}"


def expand_obligations(snapshot: dict[str, Any]) -> dict[str, Any]:
    tiling = snapshot.get("tiling", {})
    coverage_model = tiling.get("coverage_model", {})
    families_doc = tiling.get("families", {})
    key_space = tiling.get("key_space", {})
    data_model = tiling.get("data_model", {})

    family_obligations: list[dict[str, Any]] = []
    for idx, item in enumerate(coverage_model.get("family_obligations", []) or [], start=1):
        family_obligations.append(
            {
                "id": item.get("id") or _obligation_id("FAM", idx),
                "type": "family",
                "family_id": item.get("family_id"),
                "reachability": item.get("reachability"),
                "reason": item.get("reason", ""),
                "evidence_refs": item.get("evidence_refs", []),
            }
        )

    # Also include reachable families from families.yaml if not listed
    known_ids = {o["family_id"] for o in family_obligations if o.get("family_id")}
    families = families_doc.get("families", {}) or {}
    for fam_id, fam in families.items():
        reach = fam.get("reachability", "unknown")
        if fam_id in known_ids:
            continue
        if reach in ("unreachable", "excluded"):
            family_obligations.append(
                {
                    "id": _obligation_id("FAM", len(family_obligations) + 1),
                    "type": "family",
                    "family_id": fam_id,
                    "reachability": reach,
                    "reason": fam.get("unreachable_reason", "declared unreachable in families.yaml"),
                    "evidence_refs": [],
                }
            )
        elif reach in ("reachable", "reachable_narrow", "runtime_conditional", "unknown"):
            family_obligations.append(
                {
                    "id": _obligation_id("FAM", len(family_obligations) + 1),
                    "type": "family",
                    "family_id": fam_id,
                    "reachability": reach,
                    "reason": "family present in families.yaml",
                    "evidence_refs": [],
                }
            )

    key_field_obligations: list[dict[str, Any]] = []
    key_field_src = coverage_model.get("key_field_obligations", {}) or {}
    fields = key_space.get("fields", {}) or {}
    idx = 1
    for field_name, spec in key_field_src.items():
        values = spec.get("values") or (fields.get(field_name, {}) or {}).get("domain", [])
        for value in values:
            key_field_obligations.append(
                {
                    "id": _obligation_id("KFV", idx),
                    "type": "key_field_value",
                    "field": field_name,
                    "value": value,
                    "min_cases": spec.get("min_cases", 1),
                    "notes": spec.get("notes", ""),
                }
            )
            idx += 1

    key_relation_obligations: list[dict[str, Any]] = []
    for idx, item in enumerate(coverage_model.get("key_relation_obligations", []) or [], start=1):
        key_relation_obligations.append(
            {
                "id": item.get("id") or _obligation_id("KREL", idx),
                "type": "key_relation",
                "name": item.get("name", f"relation_{idx}"),
                "fields": item.get("fields", []),
                "combinations": item.get("combinations", []),
                "reason": item.get("reason", ""),
            }
        )

    tilingdata_obligations: list[dict[str, Any]] = []
    for idx, item in enumerate(coverage_model.get("tilingdata_obligations", []) or [], start=1):
        tilingdata_obligations.append(
            {
                "id": item.get("id") or _obligation_id("TD", idx),
                "type": "tilingdata",
                "block": item.get("block"),
                "fields": item.get("fields", []),
                "boundary_values": item.get("boundary_values", []),
                "families": item.get("families", []),
                "reason": item.get("reason", ""),
            }
        )

    unreachable_proof_obligations: list[dict[str, Any]] = []
    for idx, item in enumerate(key_space.get("unreachable", []) or [], start=1):
        unreachable_proof_obligations.append(
            {
                "id": _obligation_id("UNR", idx),
                "type": "unreachable_proof",
                "constraint": item.get("constraint", ""),
                "reason": item.get("reason", ""),
                "evidence_refs": item.get("evidence_refs", []),
            }
        )
    for fam_id, fam in families.items():
        if fam.get("reachability") in ("unreachable", "excluded"):
            unreachable_proof_obligations.append(
                {
                    "id": _obligation_id("UNR", len(unreachable_proof_obligations) + 1),
                    "type": "unreachable_proof",
                    "constraint": f"family:{fam_id}",
                    "reason": fam.get("unreachable_reason", ""),
                    "evidence_refs": [],
                }
            )

    seed_cases = coverage_model.get("seed_cases", []) or []

    all_obligations = (
        family_obligations
        + key_field_obligations
        + key_relation_obligations
        + tilingdata_obligations
        + unreachable_proof_obligations
    )

    return {
        "version": 1,
        "op_name": snapshot.get("op_name"),
        "source": "kb_snapshot.yaml",
        "coverage_policy": coverage_model.get("coverage_policy", {}),
        "summary": {
            "total": len(all_obligations),
            "family": len(family_obligations),
            "key_field_value": len(key_field_obligations),
            "key_relation": len(key_relation_obligations),
            "tilingdata": len(tilingdata_obligations),
            "unreachable_proof": len(unreachable_proof_obligations),
            "seed_cases": len(seed_cases),
        },
        "family_obligations": family_obligations,
        "key_field_obligations": key_field_obligations,
        "key_relation_obligations": key_relation_obligations,
        "tilingdata_obligations": tilingdata_obligations,
        "unreachable_proof_obligations": unreachable_proof_obligations,
        "seed_cases": seed_cases,
        "all_obligations": all_obligations,
    }


def plan_summary_text(obligations: dict[str, Any]) -> str:
    s = obligations.get("summary", {})
    lines = [
        f"# Coverage Plan Summary — {obligations.get('op_name', '')}",
        "",
        f"- total obligations: {s.get('total', 0)}",
        f"- family: {s.get('family', 0)}",
        f"- key_field_value: {s.get('key_field_value', 0)}",
        f"- key_relation: {s.get('key_relation', 0)}",
        f"- tilingdata: {s.get('tilingdata', 0)}",
        f"- unreachable_proof: {s.get('unreachable_proof', 0)}",
        f"- seed_cases: {s.get('seed_cases', 0)}",
        "",
        "Human review options: approve | approve_with_extra_constraints | add_obligation | remove_obligation | stop",
    ]
    return "\n".join(lines)
