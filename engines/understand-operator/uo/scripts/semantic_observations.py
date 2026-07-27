"""Deterministic observations from source windows / candidates.

Observations record visible code facts only — never final roles.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from uo.scripts.receiver_binding import (
    GET_TILING_DATA_RE,
    RECV_ADDR_ASSIGN_RE,
    extract_receiver_bindings_from_text,
    extract_root_tiling_types,
    list_discovered_binding_macro_names,
)

_SET_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*set_([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
_KEY_MACRO_RE = re.compile(r"\b(GET_TPL_TILING_KEY|GET_TILING_KEY|SetTilingKey)\s*\(")
_RETURN_KEY_RE = re.compile(r"\breturn\s+\w*[Kk]ey\b")
_GETATTR_RE = re.compile(
    r"\bGet(?:Optional)?(?:Attr|InputDesc|InputShape|InputDtype|IntAttr|BoolAttr|FloatAttr)\s*(?:<[^>]+>)?\s*\("
)
_LAYOUT_CMP_RE = re.compile(
    r"\b(layoutType|layout|inputFormat|INPUT_FORMAT_\w+|FORMAT_\w+)\b",
    re.IGNORECASE,
)
_DTYPE_RE = re.compile(r"\b(inputDtype|dtype|DataType|ge::DataType)\b", re.IGNORECASE)
_DETER_RE = re.compile(r"\b(isDeterministic|deterministic|deterSparse|sparseMode|sparse_mode)\b", re.IGNORECASE)
_SHAPE_DIM_RE = re.compile(
    r"\b([bBnNsSdD]|batch|seqLen|headNum|headDim|s1|s2|n2)\b"
)
_CEIL_DIV_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*.*(?:ceil|Ceil|CEIL|/|\*).*;"
)
_SIMPLE_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?:tilingData|tiling_data|[A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*"
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*;"
)
_IF_RE = re.compile(r"\bif\s*\(")
_TEMPLATE_USING_RE = re.compile(
    r"\busing\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*<"
)


def _obs_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    h = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}_{h}"


def _window_text(item: dict[str, Any]) -> str:
    snip = str(item.get("evidence_snippet") or "").strip()
    if snip:
        return snip
    sw = item.get("source_window") if isinstance(item.get("source_window"), dict) else {}
    return str(sw.get("text") or "")


def _evidence_ref(item: dict[str, Any], idx: int = 0) -> str:
    cid = str(item.get("candidate_id") or "").strip()
    if cid:
        return f"CAND:{cid}"
    fp = str(item.get("file_path") or "").replace("\\", "/")
    start = int(item.get("start_line") or 0)
    return f"SRC:{fp}:{start}:{idx}"


def observe_text(
    text: str,
    *,
    function: str = "",
    file_path: str = "",
    evidence_ref: str = "",
    candidate_id: str = "",
) -> list[dict[str, Any]]:
    """Extract atomic observations from a source window."""
    out: list[dict[str, Any]] = []
    if not text.strip():
        return out
    eref = evidence_ref or _evidence_ref(
        {"candidate_id": candidate_id, "file_path": file_path, "start_line": 0}
    )

    for m in GET_TILING_DATA_RE.finditer(text):
        root = str(m.group(1) or "").strip()
        out.append(
            {
                "id": _obs_id("obs_gtd", function, root, eref),
                "type": "get_tiling_data",
                "function": function,
                "root_type": root,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    # 算子仓自定义 binding 宏：仅当同窗口可见 #define 时观测，禁止硬编码宏名
    for macro in list_discovered_binding_macro_names(text):
        if not re.search(rf"(?m)^(?!\s*#\s*define).*?\b{re.escape(macro)}\s*\(", text):
            continue
        out.append(
            {
                "id": _obs_id("obs_ca", function, macro, eref),
                "type": "receiver_binding_macro",
                "function": function,
                "macro": macro,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    for b in extract_receiver_bindings_from_text(text, file_path=file_path) or []:
        if not isinstance(b, dict):
            continue
        recv = str(b.get("receiver") or "").strip()
        nested = str(b.get("nested_field") or "").strip()
        roots = list(b.get("root_tiling_types") or extract_root_tiling_types(text) or [])
        out.append(
            {
                "id": _obs_id("obs_bind", function, recv, nested, eref),
                "type": "address_of_nested_member",
                "function": function,
                "receiver": recv,
                "nested_field": nested,
                "root_tiling_types": roots,
                "member_type": b.get("member_type"),
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    # Also catch raw addr assigns even if extract_receiver_bindings misses context.
    for m in RECV_ADDR_ASSIGN_RE.finditer(text):
        recv, root_obj, nested = m.group(1), m.group(2), m.group(3)
        oid = _obs_id("obs_addr", function, recv, nested, eref)
        if any(o.get("id") == oid for o in out):
            continue
        if any(
            o.get("type") == "address_of_nested_member" and o.get("receiver") == recv
            for o in out
        ):
            continue
        out.append(
            {
                "id": oid,
                "type": "address_of_nested_member",
                "function": function,
                "receiver": recv,
                "nested_field": nested,
                "root_object": root_obj,
                "root_tiling_types": extract_root_tiling_types(text),
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    for m in _SET_CALL_RE.finditer(text):
        recv, field = m.group(1), m.group(2)
        out.append(
            {
                "id": _obs_id("obs_set", function, recv, field, eref),
                "type": "setter_call",
                "function": function,
                "receiver": recv,
                "field": field,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    if _KEY_MACRO_RE.search(text) or _RETURN_KEY_RE.search(text):
        out.append(
            {
                "id": _obs_id("obs_key", function, eref),
                "type": "key_macro_call",
                "function": function,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    for m in _GETATTR_RE.finditer(text):
        out.append(
            {
                "id": _obs_id("obs_getattr", function, m.group(0), eref),
                "type": "getattr_call",
                "function": function,
                "snippet": m.group(0)[:80],
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    if _LAYOUT_CMP_RE.search(text):
        out.append(
            {
                "id": _obs_id("obs_layout", function, eref),
                "type": "layout_condition",
                "function": function,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )
    if _DTYPE_RE.search(text):
        out.append(
            {
                "id": _obs_id("obs_dtype", function, eref),
                "type": "dtype_condition",
                "function": function,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )
    if _DETER_RE.search(text):
        out.append(
            {
                "id": _obs_id("obs_deter", function, eref),
                "type": "deterministic_or_sparse_condition",
                "function": function,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    for m in _SHAPE_DIM_RE.finditer(text):
        dim = m.group(1)
        # Only emit once per dim symbol in this window.
        if any(o.get("type") == "shape_dim_ref" and o.get("dim") == dim for o in out):
            continue
        out.append(
            {
                "id": _obs_id("obs_dim", function, dim, eref),
                "type": "shape_dim_ref",
                "function": function,
                "dim": dim,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    for m in _IF_RE.finditer(text):
        out.append(
            {
                "id": _obs_id("obs_if", function, str(m.start()), eref),
                "type": "branch_if",
                "function": function,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )
        break  # one branch marker per window is enough as observation

    for m in _TEMPLATE_USING_RE.finditer(text):
        out.append(
            {
                "id": _obs_id("obs_tmpl", function, m.group(1), eref),
                "type": "template_alias",
                "function": function,
                "alias": m.group(1),
                "base": m.group(2),
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    for m in _SIMPLE_ASSIGN_RE.finditer(text):
        local, path = m.group(1), m.group(2)
        # Skip addr-of nested (already covered).
        if f"{local} =" in text and f"&" in text.split(local, 1)[-1][:40]:
            continue
        out.append(
            {
                "id": _obs_id("obs_eq", function, local, path, eref),
                "type": "tdf_field_assign",
                "function": function,
                "local": local,
                "tdf_path": path,
                "file_path": file_path,
                "evidence_refs": [eref],
                "candidate_id": candidate_id or None,
            }
        )

    for m in _CEIL_DIV_RE.finditer(text):
        local = m.group(1)
        line = m.group(0)
        if any(op in line for op in ("+", "-", "*", "/", "%", "ceil", "Ceil", "<<", ">>")):
            # Heuristic: assignment with arithmetic → derive observation
            out.append(
                {
                    "id": _obs_id("obs_der", function, local, eref),
                    "type": "derived_assign",
                    "function": function,
                    "local": local,
                    "file_path": file_path,
                    "evidence_refs": [eref],
                    "candidate_id": candidate_id or None,
                }
            )

    return out


def build_observations_from_candidates(candidates: dict[str, Any]) -> dict[str, Any]:
    """Scan all candidate sections and emit observation document."""
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    sections = [
        "writer_candidates",
        "receiver_candidates",
        "alias_candidates",
        "receiver_binding_candidates",
        "extra_entry_candidates",
    ]
    for section in sections:
        for item in candidates.get(section) or []:
            if not isinstance(item, dict):
                continue
            text = _window_text(item)
            name = str(item.get("name") or item.get("receiver") or item.get("local") or "").strip()
            fp = str(item.get("file_path") or "").replace("\\", "/")
            cid = str(item.get("candidate_id") or "").strip()
            eref = _evidence_ref(item)
            for obs in observe_text(
                text,
                function=name,
                file_path=fp,
                evidence_ref=eref,
                candidate_id=cid,
            ):
                oid = str(obs.get("id") or "")
                if oid and oid not in seen:
                    seen.add(oid)
                    obs["section"] = section
                    # 保留真实源码窗口作为证据（禁止后续合成）
                    if text and not obs.get("evidence_snippet"):
                        obs["evidence_snippet"] = text
                    sw = item.get("source_window") if isinstance(item.get("source_window"), dict) else None
                    if sw and not obs.get("source_window"):
                        obs["source_window"] = dict(sw)
                    # 正则发现默认中置信；结构化完整字段可升 high
                    if "confidence" not in obs:
                        obs["confidence"] = "medium"
                    observations.append(obs)
            # Alias candidates: emit equivalence observation from fields.
            if section == "alias_candidates":
                local = str(item.get("local") or "").strip()
                leaf = str(item.get("tdf_leaf") or item.get("tdf_path") or "").strip()
                if local and leaf:
                    oid = _obs_id("obs_alias", local, leaf, cid)
                    if oid not in seen:
                        seen.add(oid)
                        observations.append(
                            {
                                "id": oid,
                                "type": "alias_candidate",
                                "local": local,
                                "tdf_leaf": leaf,
                                "tdf_path": item.get("tdf_path") or leaf,
                                "file_path": fp,
                                "evidence_refs": [eref],
                                "candidate_id": cid or None,
                                "section": section,
                                "evidence_snippet": text or f"{local} = tilingData->{leaf};",
                                "confidence": "high",
                            }
                        )
    return {
        "version": 1,
        "observation_count": len(observations),
        "observations": observations,
    }


__all__ = [
    "observe_text",
    "build_observations_from_candidates",
]
