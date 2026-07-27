"""Validate whether evidence supports a specific Relation (not a product role)."""
from __future__ import annotations

import re
from typing import Any

from uo.scripts.receiver_binding import (
    COMMON_ASSIGN_MACRO_RE,
    GET_TILING_DATA_RE,
    RECV_ADDR_ASSIGN_RE,
)

_SET_CALL_RE = re.compile(r"\bset_[A-Za-z0-9_]+\s*\(")
_KEY_CONSTRUCT_RE = re.compile(
    r"GET_TPL_TILING_KEY|SetTilingKey\s*\(|\breturn\s+\w*[Kk]ey\b|GET_TILING_KEY"
)
_ARITH_RE = re.compile(
    r"[+*/%]|\bceil(?:_div)?\b|\bCeil\b|\bfloor\b|\bFloor\b|<<|>>|(?<![A-Za-z0-9_])-(?!>)"
)


def _text(item: dict[str, Any]) -> str:
    snip = str(item.get("evidence_snippet") or "").strip()
    if snip:
        return snip
    sw = item.get("source_window") if isinstance(item.get("source_window"), dict) else {}
    return str(sw.get("text") or item.get("text") or "")


def validate_relation_evidence(
    relation_type: str,
    *,
    text: str = "",
    item: dict[str, Any] | None = None,
    authentic: bool | None = None,
) -> dict[str, Any]:
    """Return {authentic, supported, reason_code}.

    Unknown relation types are unsupported (fail-closed).
    """
    rtype = str(relation_type or "").strip().upper()
    body = text or (_text(item) if item else "")
    auth = bool(authentic) if authentic is not None else bool(body.strip())
    if not auth:
        return {
            "authentic": False,
            "supported": False,
            "reason_code": "evidence_not_authentic",
        }
    if not body.strip():
        return {
            "authentic": True,
            "supported": False,
            "reason_code": "evidence_window_empty",
        }

    if rtype == "BINDS":
        ok = bool(
            RECV_ADDR_ASSIGN_RE.search(body)
            or COMMON_ASSIGN_MACRO_RE.search(body)
            or (GET_TILING_DATA_RE.search(body) and RECV_ADDR_ASSIGN_RE.search(body))
        )
        # Setter alone cannot prove binding.
        if not ok and _SET_CALL_RE.search(body) and not RECV_ADDR_ASSIGN_RE.search(body):
            return {
                "authentic": True,
                "supported": False,
                "reason_code": "setter_cannot_prove_binds",
            }
        return {
            "authentic": True,
            "supported": ok,
            "reason_code": "" if ok else "binds_evidence_insufficient",
        }

    if rtype == "WRITES":
        has_set = bool(_SET_CALL_RE.search(body))
        # GetTilingData alone is NOT a write.
        if GET_TILING_DATA_RE.search(body) and not has_set:
            return {
                "authentic": True,
                "supported": False,
                "reason_code": "get_tiling_data_not_writes",
            }
        if COMMON_ASSIGN_MACRO_RE.search(body) and not has_set:
            return {
                "authentic": True,
                "supported": False,
                "reason_code": "common_assign_not_writes",
            }
        return {
            "authentic": True,
            "supported": has_set,
            "reason_code": "" if has_set else "writes_evidence_insufficient",
        }

    if rtype == "COMPOSES_KEY":
        ok = bool(_KEY_CONSTRUCT_RE.search(body))
        return {
            "authentic": True,
            "supported": ok,
            "reason_code": "" if ok else "composes_key_evidence_insufficient",
        }

    if rtype == "CONTRIBUTES_TO_KEY":
        # Soft: mentions key-related dims / conditions without necessarily composing.
        soft = bool(
            re.search(
                r"layoutType|inputDtype|isDeterministic|sparse|Template|splitAxis|OptionEnum",
                body,
                re.IGNORECASE,
            )
        )
        composed = bool(_KEY_CONSTRUCT_RE.search(body))
        # If it fully composes, contributes is secondary — still supported as soft.
        ok = soft or composed
        return {
            "authentic": True,
            "supported": ok,
            "reason_code": "" if ok else "contributes_key_evidence_insufficient",
        }

    if rtype == "EQUIVALENT_TO":
        # Simple field assign without arithmetic.
        has_assign = bool(
            re.search(
                r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*[A-Za-z_][A-Za-z0-9_]*(?:->|\.)[A-Za-z_]",
                body,
            )
        )
        if has_assign and _ARITH_RE.search(body):
            return {
                "authentic": True,
                "supported": False,
                "reason_code": "derived_not_equivalent",
            }
        return {
            "authentic": True,
            "supported": has_assign,
            "reason_code": "" if has_assign else "equivalent_evidence_insufficient",
        }

    if rtype == "DERIVES":
        ok = bool(_ARITH_RE.search(body) and "=" in body)
        return {
            "authentic": True,
            "supported": ok,
            "reason_code": "" if ok else "derives_evidence_insufficient",
        }

    if rtype == "GUARDS":
        ok = bool(re.search(r"\bif\s*\(|\bswitch\s*\(|==|!=|<|>", body))
        return {
            "authentic": True,
            "supported": ok,
            "reason_code": "" if ok else "guards_evidence_insufficient",
        }

    if rtype == "SELECTS_TEMPLATE":
        ok = bool(
            GET_TILING_DATA_RE.search(body)
            or re.search(r"WithTemplate|ASCENDC_TPL_|using\s+\w+\s*=", body)
        )
        return {
            "authentic": True,
            "supported": ok,
            "reason_code": "" if ok else "selects_template_evidence_insufficient",
        }

    if rtype == "GROUNDED_IN":
        # Grounding is structural; lexical support is GetAttr / shape / attr reads.
        ok = bool(
            re.search(
                r"GetAttr|GetInput|layout|dtype|shape|B\b|N\b|S\b|D\b",
                body,
                re.IGNORECASE,
            )
        )
        return {
            "authentic": True,
            "supported": ok,
            "reason_code": "" if ok else "grounded_in_evidence_insufficient",
        }

    if rtype in {"READS", "CALLS", "REACHABLE"}:
        return {"authentic": True, "supported": True, "reason_code": ""}

    return {
        "authentic": True,
        "supported": False,
        "reason_code": "unknown_relation_unsupported",
    }


__all__ = ["validate_relation_evidence"]
