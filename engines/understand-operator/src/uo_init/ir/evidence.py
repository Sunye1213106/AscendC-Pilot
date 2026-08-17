# -*- coding: utf-8 -*-
"""Evidence axes for CodeMap facts: source / semantic_state / trust.

Stamp is O(1) on attrs at upsert/link time. No extra source or AST walk.

Axes (do not substitute for each other):

* ``evidence.source`` — where the observation came from
* ``semantic_state`` — candidate / resolved / unresolved
* ``trust`` — whether the fact may close semantics
* ``status`` on Entity/Relation — product lifecycle (extracted/confirmed/…)
* ``provenance`` — human pass label
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

SOURCE_CLANG_AST = "clang_ast"
SOURCE_DSL = "deterministic_dsl"
SOURCE_LEXICAL = "lexical"
SOURCE_HEURISTIC = "heuristic"
SOURCE_UNSPECIFIED = "unspecified"

STATE_CANDIDATE = "candidate"
STATE_RESOLVED = "resolved"
STATE_UNRESOLVED = "unresolved"

TRUST_AUTHORITATIVE = "authoritative"
TRUST_DERIVED = "derived"
TRUST_ADVISORY = "advisory"
TRUST_LEGACY_UNKNOWN = "legacy_unknown"

SOURCES = frozenset(
    {SOURCE_CLANG_AST, SOURCE_DSL, SOURCE_LEXICAL, SOURCE_HEURISTIC, SOURCE_UNSPECIFIED}
)
STATES = frozenset({STATE_CANDIDATE, STATE_RESOLVED, STATE_UNRESOLVED})
TRUSTS = frozenset(
    {TRUST_AUTHORITATIVE, TRUST_DERIVED, TRUST_ADVISORY, TRUST_LEGACY_UNKNOWN}
)

TRUST_RANK = {
    TRUST_ADVISORY: 0,
    TRUST_LEGACY_UNKNOWN: 1,
    TRUST_DERIVED: 2,
    TRUST_AUTHORITATIVE: 3,
}

# Provenances that mint the same kind as Clang facts but come from regex/name.
ADVISORY_PROVENANCE = frozenset(
    {
        "source_kernel_call_bound",
        "source_kernel_macro_call_bound",
        "source_kernel_call_bound_v2",
        "source_kernel_macro_call_bound_v2",
        "source_kernel_call_bound_v3",
        "source_kernel_call_dispatch_set_v3",
        "source_call_site",
        "source_tpl_name_match",
        "source_tpl_name_match_verified",
        "source_tilingdata_read_verified",
        "source_tilingdata_host_write_verified",
        "source_tilingdata_host_write",
        "source_tilingdata_read_qualified",
        "source_tiling_data_class_complete",
        "source_tiling_data_member_complete",
        "source_tiling_data_class",
        "source_tilingdata_setter",
        "source_kernel_abi_position",
        "source_kernel_abi_position_verified",
        "source_host_defuse",
        "source_host_defuse_dependency",
        "source_single_kernel_selects",
        "source_kernel_frontier_bound",
        "source_untyped_tiling_data_read",
        "lexical_regex",
        "lexical_source_calls",
        "lexical_free_catalog",
    }
)

_ADVISORY_MARKERS = ("lexical", "heuristic", "regex", "inferred")
_CLANG_MARKERS = ("clang_ast", "clang_walk", "clang")
_DSL_MARKERS = (
    "source_tpl_args",
    "source_get_tpl",
    "source_get_tiling_data",
    "source_register_tiling",
    "source_tiling_registration",
    "source_tiling_key_is",
    "begin_tiling_data",
    "source_tiling_data_macro",
)


class EvidenceError(ValueError):
    """Mint/derive contract violation."""


def weaker_trust(left: str, right: str) -> str:
    a = str(left or TRUST_LEGACY_UNKNOWN)
    b = str(right or TRUST_LEGACY_UNKNOWN)
    return a if TRUST_RANK.get(a, 1) <= TRUST_RANK.get(b, 1) else b


def is_authoritative_trust(trust: str) -> bool:
    return str(trust or "") in {TRUST_AUTHORITATIVE, TRUST_DERIVED}


def parse_trust(value: Any) -> str:
    """Read trust from an attrs dict or JSON blob. O(1), no I/O."""
    if isinstance(value, (bytes, str)):
        try:
            value = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            return ""
    if isinstance(value, Mapping):
        return str(value.get("trust") or "")
    return ""


def is_advisory(value: Any) -> bool:
    return parse_trust(value) == TRUST_ADVISORY


def build_context_id(variant: Mapping[str, Any] | None) -> str:
    """Stable id for one BuildContext / compile variant. Computed once per run."""
    doc = dict(variant or {})
    payload = {
        "architecture": str(doc.get("architecture") or ""),
        "name": str(doc.get("name") or ""),
        "dtype_variant": str(doc.get("dtype_variant") or ""),
        "host_defines": list(doc.get("host_defines") or []),
        "kernel_defines": list(doc.get("kernel_defines") or []),
        "include_paths": list(doc.get("include_paths") or []),
        "compile_flags": list(doc.get("compile_flags") or []),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def infer_from_provenance(provenance: str) -> tuple[str, str]:
    """Map a pass label to (source, trust). Lexical markers beat clang."""
    prov = str(provenance or "").strip()
    if not prov:
        return SOURCE_UNSPECIFIED, TRUST_LEGACY_UNKNOWN
    lower = prov.lower()
    if prov in ADVISORY_PROVENANCE or any(mark in lower for mark in _ADVISORY_MARKERS):
        source = SOURCE_HEURISTIC if "heuristic" in lower else SOURCE_LEXICAL
        return source, TRUST_ADVISORY
    if any(mark in lower for mark in _CLANG_MARKERS):
        return SOURCE_CLANG_AST, TRUST_AUTHORITATIVE
    if any(mark in lower for mark in _DSL_MARKERS):
        return SOURCE_DSL, TRUST_DERIVED
    return SOURCE_UNSPECIFIED, TRUST_LEGACY_UNKNOWN


def stamp_attrs(
    attrs: dict[str, Any] | None,
    *,
    source: str | None = None,
    semantic_state: str | None = None,
    trust: str | None = None,
    build_context_id: str = "",
    variant: Mapping[str, Any] | None = None,
    evidence_ids: Iterable[str] | None = None,
    infer: bool = True,
) -> dict[str, Any]:
    """Fill missing evidence fields on one attr dict. Never upgrades trust."""
    out = dict(attrs or {})
    provenance = str(out.get("provenance") or "")
    inferred_source, inferred_trust = (
        infer_from_provenance(provenance)
        if infer
        else (SOURCE_UNSPECIFIED, TRUST_LEGACY_UNKNOWN)
    )
    if source in SOURCES:
        out["evidence_source"] = source
    elif str(out.get("evidence_source") or "") not in SOURCES:
        out["evidence_source"] = inferred_source
    if semantic_state in STATES:
        out["semantic_state"] = semantic_state
    elif str(out.get("semantic_state") or "") not in STATES:
        out["semantic_state"] = STATE_RESOLVED
    if trust in TRUSTS:
        existing = str(out.get("trust") or "")
        out["trust"] = weaker_trust(existing, trust) if existing in TRUSTS else trust
    elif str(out.get("trust") or "") not in TRUSTS:
        out["trust"] = inferred_trust
    ctx = str(build_context_id or out.get("build_context_id") or "")
    if ctx:
        out["build_context_id"] = ctx
    if variant:
        out.setdefault("compile_variant", dict(variant))
    if evidence_ids is not None:
        ids = [str(x) for x in evidence_ids if str(x)]
        if ids:
            out["evidence_ids"] = ids
    return out


def merge_attrs(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Union attrs; trust is min; never promote advisory to derived."""
    out = dict(existing)
    incoming = dict(incoming)
    old_trust = str(out.get("trust") or TRUST_LEGACY_UNKNOWN)
    new_trust = str(incoming.get("trust") or old_trust)
    incoming.pop("trust", None)
    out.update(incoming)
    out["trust"] = weaker_trust(old_trust, new_trust)
    return out


def mint_payload(
    *,
    provenance: str,
    source: str,
    trust: str,
    semantic_state: str = STATE_RESOLVED,
    build_context_id: str = "",
    extra: Mapping[str, Any] | None = None,
    evidence_ids: Iterable[str] | None = None,
    derivation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(extra or {})
    payload["provenance"] = provenance
    if derivation is not None:
        payload["derivation"] = dict(derivation)
    return stamp_attrs(
        payload,
        source=source,
        semantic_state=semantic_state,
        trust=trust,
        build_context_id=build_context_id,
        evidence_ids=evidence_ids,
        infer=False,
    )


def derive_trust(input_trusts: Iterable[str]) -> str:
    ranks = [TRUST_RANK.get(str(t or TRUST_LEGACY_UNKNOWN), 1) for t in input_trusts]
    if not ranks:
        return TRUST_ADVISORY
    weakest = min(ranks)
    for name, rank in TRUST_RANK.items():
        if rank == weakest:
            return name
    return TRUST_ADVISORY


def assert_semantic_mint(*, source: str, trust: str) -> None:
    if trust == TRUST_AUTHORITATIVE and source != SOURCE_CLANG_AST:
        raise EvidenceError(
            f"authoritative mint requires clang_ast, got source={source!r}"
        )
    if trust == TRUST_DERIVED and source not in {SOURCE_DSL, SOURCE_CLANG_AST}:
        raise EvidenceError(
            f"derived mint requires clang_ast or deterministic_dsl, got source={source!r}"
        )
    if source in {SOURCE_LEXICAL, SOURCE_HEURISTIC} and trust in {
        TRUST_AUTHORITATIVE,
        TRUST_DERIVED,
    }:
        raise EvidenceError(
            f"lexical/heuristic cannot mint trust={trust!r}"
        )


def summarize_graph(entities: Iterable[Any], relations: Iterable[Any]) -> dict[str, Any]:
    """One linear pass over in-memory entities/relations. No source I/O."""
    rows: list[dict[str, Any]] = []
    for item in list(entities) + list(relations):
        attrs = dict(getattr(item, "attrs", None) or {})
        attrs["id"] = getattr(item, "id", attrs.get("id", ""))
        attrs["status"] = getattr(item, "status", attrs.get("status", ""))
        rows.append(attrs)
    return summarize_trust(rows)


def summarize_trust(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """One linear pass over in-memory attrs. No source I/O."""
    counts = {name: 0 for name in TRUSTS}
    leak = 0
    false_promotion = 0
    accepted = 0
    for rec in records:
        attrs = rec if "trust" in rec or "provenance" in rec else dict(rec.get("attrs") or rec)
        trust = str(attrs.get("trust") or "")
        source = str(attrs.get("evidence_source") or "")
        status = str(rec.get("status") or attrs.get("status") or "")
        if trust not in TRUSTS:
            trust = TRUST_LEGACY_UNKNOWN
        counts[trust] = counts.get(trust, 0) + 1
        if is_authoritative_trust(trust):
            accepted += 1
        if trust == TRUST_ADVISORY and status == "confirmed":
            leak += 1
        if source in {SOURCE_LEXICAL, SOURCE_HEURISTIC} and trust in {
            TRUST_AUTHORITATIVE,
            TRUST_DERIVED,
        }:
            false_promotion += 1
    return {
        "by_trust": counts,
        "accepted_semantic_fact_count": accepted,
        "heuristic_semantic_leak_count": leak,
        "lexical_false_promotion_count": false_promotion,
    }


def validate_trust_records(records: Iterable[Mapping[str, Any]]) -> list[str]:
    """Hard invariant: lexical/heuristic must not carry derived/authoritative trust."""
    errors: list[str] = []
    for rec in records:
        attrs = rec if "evidence_source" in rec else dict(rec.get("attrs") or rec)
        source = str(attrs.get("evidence_source") or "")
        trust = str(attrs.get("trust") or "")
        if source in {SOURCE_LEXICAL, SOURCE_HEURISTIC} and trust in {
            TRUST_AUTHORITATIVE,
            TRUST_DERIVED,
        }:
            errors.append(
                f"lexical_false_promotion id={rec.get('id') or attrs.get('id') or ''} "
                f"source={source} trust={trust}"
            )
    return errors
