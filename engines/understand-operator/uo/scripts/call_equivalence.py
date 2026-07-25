"""General call-target equivalence helpers (no project-specific names).

These rules only collapse candidates when evidence proves they are alternatives
of the same call signature under conditional/alias receiver expansion or
same-file duplicate definitions.
"""
from __future__ import annotations

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

# Re-export narrow helper so call-graph can import from one module.


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


def choose_equivalent_candidate(
    candidates: list[FunctionDefinition],
    *,
    receiver_type: str,
    aliases: Mapping[str, set[str]] | None,
    signature_index: Mapping[str, FunctionSignatureFacts] | None,
) -> tuple[FunctionDefinition | None, str]:
    """Return a representative when all candidates are signature-equivalent alternatives."""
    if len(candidates) < 2:
        return None, ""

    keys = {signature_key(fn, signature_index) for fn in candidates}
    if len(keys) != 1:
        loose = {
            (
                fn.name,
                re.sub(r"\s+", "", fn.normalized_signature or ""),
                re.sub(r"\s+", "", fn.template_arity_or_signature or ""),
                fn.file_path,
            )
            for fn in candidates
        }
        if len(loose) == 1:
            chosen = sorted(candidates, key=lambda fn: fn.stable_id)[0]
            return chosen, "same_file_identical_signature_duplicate"
        return None, ""

    owners = {
        canonical_base(fn.class_or_namespace)
        for fn in candidates
        if canonical_base(fn.class_or_namespace)
    }
    receiver_owners = receiver_owner_bases(receiver_type, aliases)

    if receiver_owners and owners and owners <= receiver_owners:
        chosen = sorted(candidates, key=lambda fn: fn.stable_id)[0]
        return chosen, "signature_equivalent_conditional_owners"

    files = {fn.file_path for fn in candidates}
    if len(files) == 1 and len(owners) <= 1:
        chosen = sorted(candidates, key=lambda fn: fn.stable_id)[0]
        return chosen, "same_file_identical_signature_duplicate"

    if len(files) == 1 and not any(fn.class_or_namespace for fn in candidates):
        chosen = sorted(candidates, key=lambda fn: fn.stable_id)[0]
        return chosen, "same_file_identical_signature_duplicate"

    return None, ""


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


# Re-export for call-graph convenience.
__all__ = [
    "choose_equivalent_candidate",
    "filter_candidates_by_receiver_owners",
    "narrow_receiver_for_method_call",
    "prune_non_object_types",
    "receiver_owner_bases",
    "signature_key",
]
