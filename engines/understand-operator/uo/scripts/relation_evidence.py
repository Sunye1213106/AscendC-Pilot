"""校验 Relation 证据充分性，以及 LLM 决策相对 obligation 的越权约束。"""
from __future__ import annotations

import re
from typing import Any

from uo.scripts.receiver_binding import (
    GET_TILING_DATA_RE,
    RECV_ADDR_ASSIGN_RE,
    list_discovered_binding_macro_names,
)

_SET_CALL_RE = re.compile(r"\bset_[A-Za-z0-9_]+\s*\(")
_KEY_CONSTRUCT_RE = re.compile(
    r"GET_TPL_TILING_KEY|SetTilingKey\s*\(|\breturn\s+\w*[Kk]ey\b|GET_TILING_KEY"
)
_ARITH_RE = re.compile(
    r"[+*/%]|\bceil(?:_div)?\b|\bCeil\b|\bfloor\b|\bFloor\b|<<|>>|(?<![A-Za-z0-9_])-(?!>)"
)

_PRODUCT_ROLES = frozenset(
    {
        "tiling_writer",
        "key_writer",
        "receiver_binding",
        "key_dimension_source",
        "helper",
    }
)


def _text(item: dict[str, Any]) -> str:
    snip = str(item.get("evidence_snippet") or "").strip()
    if snip:
        return snip
    sw = item.get("source_window") if isinstance(item.get("source_window"), dict) else {}
    return str(sw.get("text") or item.get("text") or "")


def _result(*, authentic: bool, sufficient: bool, reason_code: str = "") -> dict[str, Any]:
    return {
        "authentic": authentic,
        "sufficient": sufficient,
        "supported": bool(authentic and sufficient),
        "reason_code": reason_code,
    }


def validate_relation_evidence(
    relation_type: str,
    *,
    text: str = "",
    item: dict[str, Any] | None = None,
    authentic: bool | None = None,
) -> dict[str, Any]:
    """返回 {authentic, sufficient, supported, reason_code}。"""
    rtype = str(relation_type or "").strip().upper()
    body = text or (_text(item) if item else "")
    auth = bool(authentic) if authentic is not None else bool(body.strip())
    if not auth:
        return _result(authentic=False, sufficient=False, reason_code="evidence_not_authentic")
    if not body.strip():
        return _result(authentic=True, sufficient=False, reason_code="evidence_window_empty")

    if rtype == "BINDS":
        discovered = list_discovered_binding_macro_names(body)
        has_discovered_inv = any(
            re.search(rf"(?m)^(?!\s*#\s*define).*?\b{re.escape(n)}\s*\(", body)
            for n in discovered
        )
        ok = bool(
            RECV_ADDR_ASSIGN_RE.search(body)
            or has_discovered_inv
            or (GET_TILING_DATA_RE.search(body) and RECV_ADDR_ASSIGN_RE.search(body))
        )
        if not ok and _SET_CALL_RE.search(body) and not RECV_ADDR_ASSIGN_RE.search(body):
            return _result(authentic=True, sufficient=False, reason_code="setter_cannot_prove_binds")
        return _result(
            authentic=True,
            sufficient=ok,
            reason_code="" if ok else "binds_evidence_insufficient",
        )

    if rtype == "WRITES":
        has_set = bool(_SET_CALL_RE.search(body))
        if GET_TILING_DATA_RE.search(body) and not has_set:
            return _result(authentic=True, sufficient=False, reason_code="get_tiling_data_not_writes")
        discovered = list_discovered_binding_macro_names(body)
        has_discovered_inv = any(
            re.search(rf"(?m)^(?!\s*#\s*define).*?\b{re.escape(n)}\s*\(", body)
            for n in discovered
        )
        if has_discovered_inv and not has_set:
            return _result(authentic=True, sufficient=False, reason_code="binding_macro_not_writes")
        return _result(
            authentic=True,
            sufficient=has_set,
            reason_code="" if has_set else "writes_evidence_insufficient",
        )

    if rtype == "COMPOSES_KEY":
        ok = bool(_KEY_CONSTRUCT_RE.search(body))
        # 仅有 key 相关名字不足以证明 COMPOSES_KEY
        if not ok and re.search(r"key|Key|KEY", body) and not _KEY_CONSTRUCT_RE.search(body):
            return _result(authentic=True, sufficient=False, reason_code="key_name_not_composes")
        return _result(
            authentic=True,
            sufficient=ok,
            reason_code="" if ok else "composes_key_evidence_insufficient",
        )

    if rtype == "CONTRIBUTES_TO_KEY":
        soft = bool(
            re.search(
                r"layoutType|inputDtype|isDeterministic|sparse|Template|splitAxis|OptionEnum",
                body,
                re.IGNORECASE,
            )
        )
        composed = bool(_KEY_CONSTRUCT_RE.search(body))
        ok = soft or composed
        return _result(
            authentic=True,
            sufficient=ok,
            reason_code="" if ok else "contributes_key_evidence_insufficient",
        )

    if rtype == "EQUIVALENT_TO":
        has_assign = bool(
            re.search(
                r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*[A-Za-z_][A-Za-z0-9_]*(?:->|\.)[A-Za-z_]",
                body,
            )
        )
        if has_assign and _ARITH_RE.search(body):
            return _result(authentic=True, sufficient=False, reason_code="derived_not_equivalent")
        return _result(
            authentic=True,
            sufficient=has_assign,
            reason_code="" if has_assign else "equivalent_evidence_insufficient",
        )

    if rtype == "DERIVES":
        ok = bool(_ARITH_RE.search(body) and "=" in body)
        return _result(
            authentic=True,
            sufficient=ok,
            reason_code="" if ok else "derives_evidence_insufficient",
        )

    if rtype == "GUARDS":
        ok = bool(re.search(r"\bif\s*\(|\bswitch\s*\(|==|!=|<|>", body))
        return _result(
            authentic=True,
            sufficient=ok,
            reason_code="" if ok else "guards_evidence_insufficient",
        )

    if rtype == "SELECTS_TEMPLATE":
        ok = bool(
            GET_TILING_DATA_RE.search(body)
            or re.search(r"WithTemplate|ASCENDC_TPL_|using\s+\w+\s*=", body)
        )
        return _result(
            authentic=True,
            sufficient=ok,
            reason_code="" if ok else "selects_template_evidence_insufficient",
        )

    if rtype == "GROUNDED_IN":
        ok = bool(
            re.search(
                r"GetAttr|GetInput|layout|dtype|shape|B\b|N\b|S\b|D\b",
                body,
                re.IGNORECASE,
            )
        )
        return _result(
            authentic=True,
            sufficient=ok,
            reason_code="" if ok else "grounded_in_evidence_insufficient",
        )

    if rtype in {"READS", "CALLS", "REACHABLE"}:
        return _result(authentic=True, sufficient=True)

    return _result(authentic=True, sufficient=False, reason_code="unknown_relation_unsupported")


def validate_relation_decision_against_obligation(
    decision: dict[str, Any],
    obligation: dict[str, Any],
    *,
    shard_obligation_ids: set[str] | None = None,
) -> dict[str, Any]:
    """校验 LLM relation 决策不得越权。"""
    if not isinstance(decision, dict) or not isinstance(obligation, dict):
        return {
            "ok": False,
            "error": "RELATION_CANDIDATE_OUT_OF_SCOPE",
            "message": "decision/obligation 必须为 dict",
        }
    oid = str(decision.get("obligation_id") or "").strip()
    expected = str(obligation.get("obligation_id") or "").strip()
    if oid and expected and oid != expected:
        return {
            "ok": False,
            "error": "RELATION_CANDIDATE_OUT_OF_SCOPE",
            "message": f"obligation_id 不匹配: {oid} != {expected}",
        }
    if shard_obligation_ids is not None and oid and oid not in shard_obligation_ids:
        return {
            "ok": False,
            "error": "RELATION_CANDIDATE_OUT_OF_SCOPE",
            "message": f"obligation_id {oid} 不属于当前 shard",
        }

    allowed_types = {
        str(x).upper()
        for x in (obligation.get("candidate_relations") or [])
        if str(x).strip()
    }
    allowed_entities = {
        str(x)
        for x in (obligation.get("allowed_entities") or obligation.get("entities") or [])
        if str(x).strip()
    }
    allowed_evidence = {
        str(x) for x in (obligation.get("evidence_refs") or []) if str(x).strip()
    }
    allowed_cands = {
        str(x) for x in (obligation.get("candidate_ids") or []) if str(x).strip()
    }

    errors: list[dict[str, str]] = []
    for rel in decision.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        rtype = str(rel.get("type") or "").upper()
        if allowed_types and rtype and rtype not in allowed_types:
            errors.append(
                {
                    "error": "RELATION_TYPE_OUT_OF_SCOPE",
                    "message": f"relation.type {rtype} 不在 candidate_relations",
                }
            )
        for side in ("subject", "object"):
            ent = str(rel.get(side) or "").strip()
            if not ent:
                continue
            # 禁止发明 input root
            if ent.startswith("input_root:") or ent.startswith("input:"):
                if allowed_entities and ent not in allowed_entities and not any(
                    ent.endswith(":" + e) or e == ent for e in allowed_entities
                ):
                    errors.append(
                        {
                            "error": "RELATION_ENTITY_OUT_OF_SCOPE",
                            "message": f"禁止发明 input root: {ent}",
                        }
                    )
            elif allowed_entities:
                bare = ent.split(":", 1)[-1]
                if ent not in allowed_entities and bare not in allowed_entities:
                    # unknown entity 不得自动注册
                    if ent.startswith("unknown:") or bare in {"unknown", "anon"}:
                        errors.append(
                            {
                                "error": "RELATION_ENTITY_OUT_OF_SCOPE",
                                "message": f"禁止未知 entity: {ent}",
                            }
                        )
                    elif ":" in ent and ent.split(":", 1)[0] not in {
                        "function",
                        "receiver",
                        "local",
                        "tiling_field",
                        "key",
                        "key_dimension",
                        "condition",
                        "branch",
                        "template",
                        "attr",
                        "optional",
                        "input",
                    }:
                        errors.append(
                            {
                                "error": "RELATION_ENTITY_OUT_OF_SCOPE",
                                "message": f"entity 越权: {ent}",
                            }
                        )
        for er in rel.get("evidence_refs") or []:
            er_s = str(er)
            if allowed_evidence and er_s and er_s not in allowed_evidence:
                errors.append(
                    {
                        "error": "RELATION_EVIDENCE_OUT_OF_SCOPE",
                        "message": f"evidence_ref 越权: {er_s}",
                    }
                )
        for cid in rel.get("candidate_ids") or []:
            c = str(cid)
            if allowed_cands and c and c not in allowed_cands:
                errors.append(
                    {
                        "error": "RELATION_CANDIDATE_OUT_OF_SCOPE",
                        "message": f"candidate_id 越权: {c}",
                    }
                )
        # 禁止直接输出产品 role
        role = str(rel.get("role") or "").strip()
        if role in _PRODUCT_ROLES:
            errors.append(
                {
                    "error": "RELATION_TYPE_OUT_OF_SCOPE",
                    "message": f"禁止直接输出产品 role: {role}",
                }
            )

    if errors:
        return {"ok": False, "error": errors[0]["error"], "errors": errors, "message": errors[0]["message"]}
    return {"ok": True, "errors": []}


__all__ = [
    "validate_relation_evidence",
    "validate_relation_decision_against_obligation",
]
