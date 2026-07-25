"""General call-target equivalence helpers (no project-specific names).

These helpers only *classify* candidate sets. They never invent a unique
runtime target for conditional owners. Same-file duplicates are mergeable
only when body fingerprints match.
"""
from __future__ import annotations

import hashlib
import re
from typing import Mapping

from uo.scripts.call_signature_facts import FunctionSignatureFacts
from uo.scripts.function_body import FunctionDefinition
from uo.scripts.type_normalizer import (
    canonical_base,
    expand_type_candidates,
    narrow_receiver_for_method_call,
    prune_non_object_types,
)


def receiver_owner_bases(
    receiver_type: str,
    aliases: Mapping[str, set[str]] | None = None,
) -> set[str]:
    expanded = expand_type_candidates(receiver_type, aliases, max_depth=5)
    usable = prune_non_object_types(set(expanded))
    return {canonical_base(item) for item in usable if canonical_base(item)}


def signature_key(
    fn: FunctionDefinition,
    signature_index: Mapping[str, FunctionSignatureFacts] | None = None,
) -> tuple:
    facts = (signature_index or {}).get(fn.stable_id)
    if facts is not None:
        tmpl = tuple((p.kind, p.name, p.default or "") for p in facts.template_parameters)
        params = tuple(facts.parameter_types)
        return (fn.name, tmpl, params, facts.min_arity, facts.max_arity)
    return (
        fn.name,
        str(fn.template_arity_or_signature or ""),
        str(fn.normalized_signature or ""),
        _signature_arity(fn.normalized_signature),
    )


def body_fingerprint(fn: FunctionDefinition) -> str:
    """Stable fingerprint of a definition body for duplicate detection."""
    if fn.snippet_hash:
        return f"snippet:{fn.snippet_hash}"
    text = str(fn.body_text or "")
    # Drop comments and whitespace so formatting-only duplicates still match.
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"\s+", "", text)
    return "body:" + hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def classify_equivalent_candidates(
    candidates: list[FunctionDefinition],
    *,
    receiver_type: str,
    aliases: Mapping[str, set[str]] | None,
    signature_index: Mapping[str, FunctionSignatureFacts] | None,
) -> tuple[str, str]:
    """Classify a candidate set without choosing a speculative target.

    Returns ``(kind, reason)`` where kind is one of:
    - ``\"\"``: no safe equivalence class
    - ``\"conditional\"``: same signature under conditional/alias owner expansion
    - ``\"identical_body_duplicate\"``: same file/signature and identical bodies
    """
    if len(candidates) < 2:
        return "", ""

    keys = {signature_key(fn, signature_index) for fn in candidates}
    if len(keys) != 1:
        return "", ""

    owners = {
        canonical_base(fn.class_or_namespace)
        for fn in candidates
        if canonical_base(fn.class_or_namespace)
    }
    receiver_owners = receiver_owner_bases(receiver_type, aliases)

    # Conditional/alias owners with the same signature remain multi-target.
    if receiver_owners and owners and owners <= receiver_owners and len(owners) > 1:
        return "conditional", "signature_equivalent_conditional_owners"

    files = {fn.file_path for fn in candidates}
    fingerprints = {body_fingerprint(fn) for fn in candidates}
    same_owner = len(owners) <= 1
    free_functions = not any(fn.class_or_namespace for fn in candidates)
    if len(files) == 1 and len(fingerprints) == 1 and (same_owner or free_functions):
        return "identical_body_duplicate", "same_file_identical_body_duplicate"

    return "", ""


def choose_equivalent_candidate(
    candidates: list[FunctionDefinition],
    *,
    receiver_type: str,
    aliases: Mapping[str, set[str]] | None,
    signature_index: Mapping[str, FunctionSignatureFacts] | None,
) -> tuple[FunctionDefinition | None, str]:
    """Backward-compatible wrapper: only identical-body duplicates yield a target."""
    kind, reason = classify_equivalent_candidates(
        candidates,
        receiver_type=receiver_type,
        aliases=aliases,
        signature_index=signature_index,
    )
    if kind == "identical_body_duplicate":
        chosen = sorted(candidates, key=lambda fn: fn.stable_id)[0]
        return chosen, reason
    return None, reason if kind == "conditional" else ""


def filter_candidates_by_receiver_owners(
    candidates: list[FunctionDefinition],
    receiver_type: str,
    aliases: Mapping[str, set[str]] | None = None,
) -> list[FunctionDefinition]:
    owners = receiver_owner_bases(receiver_type, aliases)
    if not owners or len(candidates) <= 1:
        return candidates
    typed = [
        fn
        for fn in candidates
        if canonical_base(fn.class_or_namespace) in owners
    ]
    return typed or candidates


def _signature_arity(signature: str) -> int:
    text = str(signature or "").strip()
    if not text.startswith("(") or not text.endswith(")"):
        return -1
    inner = text[1:-1].strip()
    if not inner or inner == "void":
        return 0
    depth = 0
    count = 1
    for ch in inner:
        if ch in "(<[{":
            depth += 1
        elif ch in ")>]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            count += 1
    return count


__all__ = [
    "body_fingerprint",
    "choose_equivalent_candidate",
    "classify_equivalent_candidates",
    "filter_candidates_by_receiver_owners",
    "narrow_receiver_for_method_call",
    "prune_non_object_types",
    "receiver_owner_bases",
    "signature_key",
]
