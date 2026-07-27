"""Role-evidence sufficiency checks (authentic ≠ sufficient).

Authority: policies/evidence + extract_plan Gate.
Does not invent operator-specific names; pattern-based only.
"""
from __future__ import annotations

import re
from typing import Any

# Writer / sink write patterns
_SET_CALL_RE = re.compile(r"\bset_[A-Za-z0-9_]+\s*\(")
_TILING_WRITE_RE = re.compile(
    r"(?:tilingData|TilingData|tiling_data)\s*->|"
    r"->\s*set_[A-Za-z0-9_]+\s*\(|"
    r"GetTilingData\s*<",
    re.IGNORECASE,
)
_RECV_ASSIGN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*&?\s*[A-Za-z_][A-Za-z0-9_]*\s*->"
    r"\s*[A-Za-z_][A-Za-z0-9_]*"
)
_KEY_CONSTRUCT_RE = re.compile(
    r"GET_TPL_TILING_KEY|SetTilingKey\s*\(|\breturn\s+\w*[Kk]ey\b|"
    r"GET_TILING_KEY|TilingKey\s*=",
)
_KEY_DIM_RE = re.compile(
    r"TemplateType|OptionEnum|splitAxis|layoutType|isTnd|attenMask|"
    r"deterSparse|s1Template|s2Template|dTemplate|inputDtype",
    re.IGNORECASE,
)
_RECV_BINDING_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*\s*=\s*&\s*[A-Za-z_][A-Za-z0-9_]*\s*->"
    r"\s*[A-Za-z_][A-Za-z0-9_]*\s*;|"
    r"GetTilingData\s*<|"
    r"TILING_DATA_COMMON_ASSIGN",
)
_COMMON_ASSIGN_RE = re.compile(r"TILING_DATA_COMMON_ASSIGN")

WRITER_LIKE_ROLES = frozenset(
    {"tiling_writer", "workspace_writer", "provenance_helper"}
)
KEY_WRITER_ROLES = frozenset({"key_writer"})
KEY_DIM_ROLES = frozenset({"key_dimension_source"})
RECV_BINDING_ROLES = frozenset({"receiver_binding", "macro_binding"})


def _window_text(item: dict[str, Any], candidate: dict[str, Any] | None = None) -> str:
    snip = str(item.get("evidence_snippet") or "").strip()
    if snip:
        return snip
    sw = item.get("source_window") if isinstance(item.get("source_window"), dict) else {}
    if sw.get("text"):
        return str(sw.get("text") or "")
    if candidate:
        csw = candidate.get("source_window") if isinstance(candidate.get("source_window"), dict) else {}
        if csw.get("text"):
            return str(csw.get("text") or "")
        for ev in candidate.get("evidence") or []:
            if isinstance(ev, str) and len(ev) > 40:
                return ev
    return ""


def validate_role_evidence(
    item: dict[str, Any],
    *,
    role: str = "",
    candidate: dict[str, Any] | None = None,
    candidate_kind: str = "",
    authentic: bool | None = None,
) -> dict[str, Any]:
    """Return {authentic, sufficient, reason_code}.

    ``authentic`` may be precomputed by disk-window proof; when None, treat
    non-empty window text as authentic-enough for sufficiency scanning.
    """
    role_s = str(role or item.get("role") or "").strip()
    kind = str(candidate_kind or item.get("candidate_kind") or "").strip()
    text = _window_text(item, candidate)
    auth = bool(authentic) if authentic is not None else bool(text.strip())
    if not auth:
        return {
            "authentic": False,
            "sufficient": False,
            "reason_code": "evidence_not_authentic",
        }
    if not text.strip():
        return {
            "authentic": True,
            "sufficient": False,
            "reason_code": "evidence_window_empty",
        }

    # Macros / bindings: do not require function shape.
    if kind in {"macro_binding", "receiver_binding"} or role_s in RECV_BINDING_ROLES:
        if _RECV_BINDING_RE.search(text) or _COMMON_ASSIGN_RE.search(text) or _SET_CALL_RE.search(text):
            return {"authentic": True, "sufficient": True, "reason_code": ""}
        return {
            "authentic": True,
            "sufficient": False,
            "reason_code": "receiver_binding_evidence_insufficient",
        }

    if role_s in KEY_WRITER_ROLES:
        if _KEY_CONSTRUCT_RE.search(text):
            return {"authentic": True, "sufficient": True, "reason_code": ""}
        return {
            "authentic": True,
            "sufficient": False,
            "reason_code": "key_writer_evidence_insufficient",
        }

    if role_s in KEY_DIM_ROLES or kind == "key_dimension_source":
        if _KEY_DIM_RE.search(text) or _KEY_CONSTRUCT_RE.search(text):
            return {"authentic": True, "sufficient": True, "reason_code": ""}
        # Dimension sources may only affect conditions — allow softer match.
        if re.search(r"\bif\s*\(|\bswitch\s*\(|enum|Template", text):
            return {"authentic": True, "sufficient": True, "reason_code": ""}
        return {
            "authentic": True,
            "sufficient": False,
            "reason_code": "key_dimension_evidence_insufficient",
        }

    if role_s in WRITER_LIKE_ROLES or kind in {"function_writer", "receiver_sink"}:
        has_set = bool(_SET_CALL_RE.search(text))
        has_write = bool(_TILING_WRITE_RE.search(text))
        has_recv = bool(_RECV_ASSIGN_RE.search(text))
        if has_set or (has_write and has_recv) or (has_write and has_set):
            return {"authentic": True, "sufficient": True, "reason_code": ""}
        if has_write:
            return {"authentic": True, "sufficient": True, "reason_code": ""}
        return {
            "authentic": True,
            "sufficient": False,
            "reason_code": "writer_evidence_insufficient",
        }

    if role_s in {"ignore", "helper"} or kind in {"helper", "duplicate"}:
        return {"authentic": True, "sufficient": True, "reason_code": ""}

    # Receivers promoted as sinks.
    if item.get("is_tiling_sink") is True:
        if _SET_CALL_RE.search(text) or _RECV_ASSIGN_RE.search(text):
            return {"authentic": True, "sufficient": True, "reason_code": ""}
        return {
            "authentic": True,
            "sufficient": False,
            "reason_code": "writer_evidence_insufficient",
        }

    return {"authentic": True, "sufficient": True, "reason_code": ""}


__all__ = [
    "validate_role_evidence",
]
