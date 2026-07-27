"""Shared receiver → TilingData binding extraction and canonical owner identity.

Used by propose_extract_plan, extract_host_subgraph, and reconcile_bridge.
Canonical Bridge identity prefers root_tiling_type + nested_path (+ leaf),
not member_type alone.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

# recv_ = &tilingData->nestedField
RECV_ADDR_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*&\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)\s*;"
)
# recv_ = tilingData->GetX() / GetMember()
RECV_GETTER_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*->\s*(Get[A-Za-z0-9_]*)\s*\(\s*\)\s*;"
)
GET_TILING_DATA_RE = re.compile(
    r"(?:GetTilingData|context_->GetTilingData)\s*<\s*([A-Za-z_][A-Za-z0-9_:]*)\s*>"
)
# Type *recv_ = nullptr;  /  Type* recv_;
MEMBER_PTR_DECL_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_:]*)\s*\*+\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|;)"
)
# Macro bodies often embed the same assignments.
MACRO_ASSIGN_BODY_RE = RECV_ADDR_ASSIGN_RE
# TND/BASE_TILING_DATA_COMMON_ASSIGN(...) — treat as macro_binding evidence.
COMMON_ASSIGN_MACRO_RE = re.compile(
    r"\b((?:TND_|BASE_)?TILING_DATA_COMMON_ASSIGN)\s*\("
)


def normalize_type_name(name: str) -> str:
    t = str(name or "").strip()
    if not t:
        return ""
    t = t.replace("::", ".")
    if "." in t:
        t = t.split(".")[-1]
    return t


def canonical_owner_key(
    *,
    root_type: str = "",
    nested_path: str = "",
    member_type: str = "",
) -> dict[str, str]:
    root = normalize_type_name(root_type)
    nested = str(nested_path or "").strip().strip(".")
    member = normalize_type_name(member_type)
    return {
        "root_type": root,
        "nested_path": nested,
        "member_type": member,
    }


def owner_identity_string(key: dict[str, Any] | None) -> str:
    """Stable normalized owner identity for Bridge obligation keys."""
    if not isinstance(key, dict):
        return ""
    root = normalize_type_name(str(key.get("root_type") or ""))
    nested = str(key.get("nested_path") or "").strip().strip(".")
    member = normalize_type_name(str(key.get("member_type") or ""))
    if root and nested:
        return f"{root}::{nested}".casefold()
    if member:
        return member.casefold()
    if root:
        return root.casefold()
    return ""


def field_identity_parts(
    *,
    owner_key: dict[str, Any] | None,
    field_leaf: str,
) -> tuple[str, str]:
    """Return (normalized_owner_identity, normalized_field_path)."""
    leaf = str(field_leaf or "").strip()
    key = owner_key if isinstance(owner_key, dict) else {}
    nested = str(key.get("nested_path") or "").strip().strip(".")
    owner = owner_identity_string(key)
    if nested and leaf and not leaf.startswith(nested + "."):
        field_path = f"{nested}.{leaf}"
    else:
        field_path = leaf
    return owner, field_path.casefold()


def extract_root_tiling_types(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in GET_TILING_DATA_RE.finditer(text or ""):
        typ = normalize_type_name(m.group(1))
        if typ and typ.casefold() not in seen:
            seen.add(typ.casefold())
            out.append(typ)
    return out


def extract_member_ptr_types(text: str) -> dict[str, str]:
    """Map receiver name → declared member pointer type."""
    out: dict[str, str] = {}
    for typ, recv in MEMBER_PTR_DECL_RE.findall(text or ""):
        ntyp = normalize_type_name(typ)
        if not ntyp or ntyp in {"auto", "const", "static", "constexpr", "return"}:
            continue
        if "tiling" not in ntyp.casefold() and "param" not in ntyp.casefold() and not ntyp.endswith("Params"):
            # Keep broad but skip obvious non-tiling primitives.
            if ntyp.casefold() in {"int", "uint32_t", "int64_t", "bool", "float", "double", "size_t", "void"}:
                continue
        out[str(recv)] = ntyp
    return out


def extract_receiver_bindings(
    text: str,
    *,
    file_path: str = "",
    extraction_unit: str = "",
    class_or_namespace: str = "",
    start_line: int = 0,
    member_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Public alias for extract_receiver_bindings_from_text (shared module API)."""
    return extract_receiver_bindings_from_text(
        text,
        file_path=file_path,
        extraction_unit=extraction_unit,
        class_or_namespace=class_or_namespace,
        start_line=start_line,
        member_types=member_types,
    )


def extract_receiver_bindings_from_text(
    text: str,
    *,
    file_path: str = "",
    extraction_unit: str = "",
    class_or_namespace: str = "",
    start_line: int = 0,
    member_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Parse recv=&var->field / GetTilingData / COMMON_ASSIGN into structured bindings."""
    roots = extract_root_tiling_types(text)
    root_default = roots[0] if roots else ""
    decls = dict(member_types or {})
    decls.update(extract_member_ptr_types(text))
    bindings: dict[str, dict[str, Any]] = {}

    def _upsert(recv: str, nested: str, *, evidence: str) -> None:
        recv_s = str(recv or "").strip()
        nested_s = str(nested or "").strip()
        if not recv_s or not nested_s:
            return
        member = decls.get(recv_s, "")
        key = canonical_owner_key(
            root_type=root_default,
            nested_path=nested_s,
            member_type=member,
        )
        aliases = []
        if member:
            aliases.append(member)
        item = {
            "receiver": recv_s,
            "member_type": member,
            "root_tiling_types": list(roots),
            "nested_field": nested_s,
            "canonical_owner_key": key,
            "type_aliases": aliases,
            "file_path": str(file_path or "").replace("\\", "/"),
            "extraction_unit": str(extraction_unit or class_or_namespace or ""),
            "class_or_namespace": str(class_or_namespace or ""),
            "start_line": int(start_line or 0),
            "evidence": [evidence],
            "score": 0.9,
            "role_suggested": "receiver_binding",
        }
        prev = bindings.get(recv_s)
        if prev is None:
            bindings[recv_s] = item
            return
        # Merge roots / aliases; keep higher score.
        prev_roots = list(prev.get("root_tiling_types") or [])
        for r in roots:
            if r not in prev_roots:
                prev_roots.append(r)
        prev["root_tiling_types"] = prev_roots
        if member and not prev.get("member_type"):
            prev["member_type"] = member
            prev["canonical_owner_key"] = key
        ev = list(prev.get("evidence") or [])
        if evidence not in ev:
            ev.append(evidence)
        prev["evidence"] = ev
        if float(item.get("score") or 0) > float(prev.get("score") or 0):
            prev["score"] = item["score"]

    for recv, _var, nested in RECV_ADDR_ASSIGN_RE.findall(text or ""):
        _upsert(recv, nested, evidence="recv_addr_assign")
    for recv, _var, getter in RECV_GETTER_ASSIGN_RE.findall(text or ""):
        # Getter name GetFoo → nested guess Foo / foo
        nested = getter[3:] if getter.startswith("Get") and len(getter) > 3 else getter
        if nested:
            nested = nested[0].lower() + nested[1:] if nested[0].isupper() else nested
        _upsert(recv, nested, evidence="recv_getter_assign")

    # Form 3: COMMON_ASSIGN macros — mark receivers already present; emit stub if only macro.
    for macro in COMMON_ASSIGN_MACRO_RE.findall(text or ""):
        if bindings:
            for item in bindings.values():
                ev = list(item.get("evidence") or [])
                tag = f"macro:{macro}"
                if tag not in ev:
                    ev.append(tag)
                item["evidence"] = ev
                item["role_suggested"] = "receiver_binding"
                item["candidate_kind"] = "macro_binding"
                item["score"] = max(float(item.get("score") or 0), 0.9)
        else:
            # Macro present without parsed recv= — still emit a typed placeholder binding.
            key = canonical_owner_key(root_type=root_default, nested_path="", member_type="")
            bindings[f"__macro__{macro}"] = {
                "receiver": "",
                "member_type": "",
                "root_tiling_types": list(roots),
                "nested_field": "",
                "canonical_owner_key": key,
                "type_aliases": [],
                "file_path": str(file_path or "").replace("\\", "/"),
                "extraction_unit": str(extraction_unit or class_or_namespace or ""),
                "class_or_namespace": str(class_or_namespace or ""),
                "start_line": int(start_line or 0),
                "evidence": [f"macro:{macro}"],
                "score": 0.85,
                "role_suggested": "receiver_binding",
                "candidate_kind": "macro_binding",
                "macro_name": macro,
            }

    return list(bindings.values())


def index_bindings_by_receiver(bindings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for b in bindings or []:
        if not isinstance(b, dict):
            continue
        recv = str(b.get("receiver") or b.get("name") or "").strip()
        if recv:
            out[recv] = b
    return out


def binding_candidate_id(binding: dict[str, Any]) -> str:
    raw = "|".join(
        [
            "receiver_binding",
            str(binding.get("extraction_unit") or ""),
            str(binding.get("file_path") or ""),
            str(binding.get("receiver") or ""),
            str(binding.get("nested_field") or ""),
            str(binding.get("start_line") or 0),
            str((binding.get("canonical_owner_key") or {}).get("root_type") or ""),
        ]
    )
    return "CAND_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


__all__ = [
    "COMMON_ASSIGN_MACRO_RE",
    "GET_TILING_DATA_RE",
    "MEMBER_PTR_DECL_RE",
    "RECV_ADDR_ASSIGN_RE",
    "RECV_GETTER_ASSIGN_RE",
    "binding_candidate_id",
    "canonical_owner_key",
    "extract_member_ptr_types",
    "extract_receiver_bindings",
    "extract_receiver_bindings_from_text",
    "extract_root_tiling_types",
    "field_identity_parts",
    "index_bindings_by_receiver",
    "normalize_type_name",
    "owner_identity_string",
]
