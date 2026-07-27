"""Build semantic obligations from observations + candidates.

Only ambiguous cases become LLM obligations; clear facts close deterministically.
"""
from __future__ import annotations

import hashlib
from typing import Any


def _oid(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts if p)
    return "obl_" + hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def build_semantic_obligations(
    observations: dict[str, Any],
    candidates: dict[str, Any] | None = None,
    *,
    closed_relation_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Group observations into canonical obligations.

    Deterministic closures are listed separately; remaining items are llm_required
    only when multiple competing relation interpretations exist.
    """
    _ = candidates
    closed = closed_relation_ids or set()
    obs_list = [
        o for o in (observations.get("observations") or []) if isinstance(o, dict)
    ]

    # Group by function / receiver / local identity.
    groups: dict[str, list[dict[str, Any]]] = {}
    for o in obs_list:
        key = (
            str(o.get("function") or "")
            or str(o.get("receiver") or "")
            or str(o.get("local") or "")
            or str(o.get("type") or "")
        )
        groups.setdefault(key or "anon", []).append(o)

    deterministic: list[dict[str, Any]] = []
    llm_required: list[dict[str, Any]] = []

    for key, items in groups.items():
        types = {str(x.get("type") or "") for x in items}
        candidate_ids = sorted(
            {
                str(x.get("candidate_id") or "")
                for x in items
                if x.get("candidate_id")
            }
        )
        evidence_refs = sorted(
            {
                r
                for x in items
                for r in (x.get("evidence_refs") or [])
                if r
            }
        )

        # Clear binding-only macros / addr assigns → deterministic BINDS.
        # Still emit GUARDS/SELECTS_TEMPLATE when condition/template obs coexist.
        has_bind = bool(
            types
            & {
                "common_assign_macro",
                "address_of_nested_member",
                "get_tiling_data",
            }
        )
        has_cond = bool(
            types
            & {
                "layout_condition",
                "dtype_condition",
                "deterministic_or_sparse_condition",
                "branch_if",
                "template_alias",
            }
        )
        if has_bind and "setter_call" not in types and "key_macro_call" not in types:
            close = ["BINDS"]
            crels = ["BINDS", "READS"]
            if has_cond:
                if types & {
                    "layout_condition",
                    "dtype_condition",
                    "deterministic_or_sparse_condition",
                    "branch_if",
                }:
                    close.append("GUARDS")
                    crels.append("GUARDS")
                if "template_alias" in types or "get_tiling_data" in types:
                    close.append("SELECTS_TEMPLATE")
                    crels.append("SELECTS_TEMPLATE")
            obl = {
                "obligation_id": _oid("bind", key),
                "pool": "binding_relations",
                "entities": [key],
                "candidate_ids": candidate_ids,
                "candidate_relations": crels,
                "observations": [x.get("id") for x in items],
                "evidence_refs": evidence_refs,
                "llm_required": False,
                "close_as": close,
            }
            if obl["obligation_id"] not in closed:
                deterministic.append(obl)
            continue

        # Pure setters → WRITES.
        if types == {"setter_call"} or (
            "setter_call" in types and "address_of_nested_member" not in types
        ):
            obl = {
                "obligation_id": _oid("write", key),
                "pool": "writer_relations",
                "entities": [key],
                "candidate_ids": candidate_ids,
                "candidate_relations": ["WRITES"],
                "observations": [x.get("id") for x in items],
                "evidence_refs": evidence_refs,
                "llm_required": False,
                "close_as": ["WRITES"],
            }
            deterministic.append(obl)
            continue

        # Key macro → COMPOSES_KEY.
        if "key_macro_call" in types and "derived_assign" not in types:
            # Ambiguous if also only condition markers without key macro clarity.
            has_key = "key_macro_call" in types
            has_only_cond = types <= {
                "layout_condition",
                "dtype_condition",
                "deterministic_or_sparse_condition",
                "branch_if",
                "shape_dim_ref",
            }
            if has_key:
                obl = {
                    "obligation_id": _oid("key", key),
                    "pool": "key_relations",
                    "entities": [key],
                    "candidate_ids": candidate_ids,
                    "candidate_relations": ["COMPOSES_KEY", "CONTRIBUTES_TO_KEY"],
                    "observations": [x.get("id") for x in items],
                    "evidence_refs": evidence_refs,
                    "llm_required": False,
                    "close_as": ["COMPOSES_KEY"],
                }
                deterministic.append(obl)
                continue
            if has_only_cond:
                obl = {
                    "obligation_id": _oid("kdim", key),
                    "pool": "key_relations",
                    "entities": [key],
                    "candidate_ids": candidate_ids,
                    "candidate_relations": ["CONTRIBUTES_TO_KEY", "GUARDS"],
                    "observations": [x.get("id") for x in items],
                    "evidence_refs": evidence_refs,
                    "llm_required": False,
                    "close_as": ["CONTRIBUTES_TO_KEY", "GUARDS"],
                }
                deterministic.append(obl)
                continue

        # Alias vs derive conflict → LLM.
        if "alias_candidate" in types and "derived_assign" in types:
            llm_required.append(
                {
                    "obligation_id": _oid("alias_der", key),
                    "pool": "alias_vs_derive",
                    "entities": [key],
                    "candidate_ids": candidate_ids,
                    "candidate_relations": ["EQUIVALENT_TO", "DERIVES"],
                    "observations": [x.get("id") for x in items],
                    "evidence_refs": evidence_refs,
                    "llm_required": True,
                    "question": "alias vs derived dependency",
                }
            )
            continue

        if "alias_candidate" in types or "tdf_field_assign" in types:
            deterministic.append(
                {
                    "obligation_id": _oid("alias", key),
                    "pool": "alias_vs_derive",
                    "entities": [key],
                    "candidate_ids": candidate_ids,
                    "candidate_relations": ["EQUIVALENT_TO"],
                    "observations": [x.get("id") for x in items],
                    "evidence_refs": evidence_refs,
                    "llm_required": False,
                    "close_as": ["EQUIVALENT_TO"],
                }
            )
            continue

        if "derived_assign" in types:
            deterministic.append(
                {
                    "obligation_id": _oid("der", key),
                    "pool": "alias_vs_derive",
                    "entities": [key],
                    "candidate_ids": candidate_ids,
                    "candidate_relations": ["DERIVES"],
                    "observations": [x.get("id") for x in items],
                    "evidence_refs": evidence_refs,
                    "llm_required": False,
                    "close_as": ["DERIVES"],
                }
            )
            continue

        # Conditions / templates.
        if types & {
            "layout_condition",
            "dtype_condition",
            "deterministic_or_sparse_condition",
            "branch_if",
            "template_alias",
            "get_tiling_data",
        }:
            close = []
            crels = []
            if types & {
                "layout_condition",
                "dtype_condition",
                "deterministic_or_sparse_condition",
                "branch_if",
            }:
                close.append("GUARDS")
                crels.append("GUARDS")
            if "template_alias" in types or "get_tiling_data" in types:
                close.append("SELECTS_TEMPLATE")
                crels.append("SELECTS_TEMPLATE")
            if close:
                deterministic.append(
                    {
                        "obligation_id": _oid("cond", key),
                        "pool": "architecture_relations",
                        "entities": [key],
                        "candidate_ids": candidate_ids,
                        "candidate_relations": crels or ["GUARDS"],
                        "observations": [x.get("id") for x in items],
                        "evidence_refs": evidence_refs,
                        "llm_required": False,
                        "close_as": close,
                    }
                )
                continue

        # Mixed writer+binding or unclear → LLM.
        if len(types) > 1:
            llm_required.append(
                {
                    "obligation_id": _oid("mix", key),
                    "pool": "writer_relations",
                    "entities": [key],
                    "candidate_ids": candidate_ids,
                    "candidate_relations": sorted(
                        {
                            "BINDS",
                            "WRITES",
                            "READS",
                            "COMPOSES_KEY",
                            "CONTRIBUTES_TO_KEY",
                            "GUARDS",
                            "SELECTS_TEMPLATE",
                        }
                    ),
                    "observations": [x.get("id") for x in items],
                    "evidence_refs": evidence_refs,
                    "llm_required": True,
                    "question": "confirm which relations are evidenced",
                }
            )

    return {
        "version": 1,
        "deterministic_count": len(deterministic),
        "llm_required_count": len(llm_required),
        "deterministic": deterministic,
        "llm_required": llm_required,
        "obligations": deterministic + llm_required,
    }


__all__ = ["build_semantic_obligations"]
