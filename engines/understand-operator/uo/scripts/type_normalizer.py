"""Conservative C++ type-alias and template normalization."""
from __future__ import annotations

import re
from typing import Mapping

_ALIAS_RE = re.compile(
    r"\busing\s+([A-Za-z_]\w*)\s*=\s*([^;]+);|"
    r"\btypedef\s+([^;]+?)\s+([A-Za-z_]\w*)\s*;",
    re.DOTALL,
)


def collect_type_aliases(source_texts: Mapping[object, str] | None) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for text in (source_texts or {}).values():
        source = _strip_comments(str(text or ""))
        for match in _ALIAS_RE.finditer(source):
            if match.group(1):
                name, expression = match.group(1), match.group(2)
            else:
                name, expression = match.group(4), match.group(3)
            normalized = normalize_declared_type(expression)
            if normalized:
                aliases.setdefault(name, set()).add(normalized)
    return aliases


def expand_type_candidates(
    type_name: str,
    aliases: Mapping[str, set[str]] | None = None,
    *,
    max_depth: int = 2,
) -> set[str]:
    seed = normalize_declared_type(type_name)
    if not seed:
        return set()
    current = {seed}
    seen = set(current)
    for _ in range(max(0, max_depth)):
        changed = False
        next_values: set[str] = set()
        for value in current:
            expanded = _expand_once(value, aliases or {})
            next_values.update(expanded)
            if expanded != {value}:
                changed = True
        next_values = {normalize_declared_type(item) for item in next_values if normalize_declared_type(item)}
        seen.update(next_values)
        current = next_values or current
        if not changed:
            break
    leaves = {value for value in current if value}
    return leaves or seen


def canonical_base(type_name: str) -> str:
    text = normalize_declared_type(type_name)
    if not text:
        return ""
    depth = 0
    out: list[str] = []
    for ch in text:
        if ch == "<":
            depth += 1
            continue
        if ch == ">":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).split("::")[-1]


def normalize_declared_type(type_name: str) -> str:
    text = str(type_name or "").strip()
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|struct|class|register|extern)\b", " ", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("*& ")


_NON_OBJECT_TYPES = frozenset(
    {
        "",
        "void",
        "nullptr",
        "nullptr_t",
        "std::nullptr_t",
        "null_ptr",
        "NULL",
    }
)


def prune_non_object_types(type_names: set[str]) -> set[str]:
    """Drop branches that cannot host method calls (nullptr_t/void/...)."""
    out: set[str] = set()
    for raw in type_names:
        text = normalize_declared_type(raw)
        base = canonical_base(text)
        if not text or text in _NON_OBJECT_TYPES or base in _NON_OBJECT_TYPES:
            continue
        out.add(text)
    return out


def narrow_receiver_for_method_call(
    receiver_type: str,
    aliases: Mapping[str, set[str]] | None = None,
) -> str:
    """Narrow conditional/alias receivers to a unique object type when possible."""
    if not receiver_type:
        return ""
    expanded = expand_type_candidates(receiver_type, aliases, max_depth=3)
    usable = prune_non_object_types(set(expanded))
    if not usable:
        return receiver_type
    bases = {canonical_base(item) for item in usable if canonical_base(item)}
    if len(bases) == 1:
        return sorted(usable, key=lambda value: (len(value), value))[0]
    return receiver_type


def _expand_once(value: str, aliases: Mapping[str, set[str]]) -> set[str]:
    base = canonical_base(value)
    if base in aliases:
        return set(aliases[base])
    conditional = _conditional_branches(value)
    if conditional:
        return conditional
    return {value}


def _conditional_branches(value: str) -> set[str]:
    marker = "std::conditional<"
    start = value.find(marker)
    if start < 0:
        marker = "conditional<"
        start = value.find(marker)
    if start < 0:
        return set()
    open_pos = start + len(marker) - 1
    close_pos = _matching_angle(value, open_pos)
    if close_pos is None:
        return set()
    suffix = value[close_pos + 1 :]
    if suffix not in {"::type", "::type_t", ""}:
        return set()
    args = _split_top_level(value[open_pos + 1 : close_pos], ",")
    if len(args) != 3:
        return set()
    return {normalize_declared_type(args[1]), normalize_declared_type(args[2])} - {""}


def _matching_angle(text: str, open_pos: int) -> int | None:
    depth = 0
    for index in range(open_pos, len(text)):
        if text[index] == "<":
            depth += 1
        elif text[index] == ">":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_top_level(text: str, delimiter: str) -> list[str]:
    out: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    pairs = {")": "(", "]": "[", "}": "{", ">": "<"}
    for index, ch in enumerate(text):
        if ch in depths:
            depths[ch] += 1
        elif ch in pairs:
            key = pairs[ch]
            depths[key] = max(0, depths[key] - 1)
        elif ch == delimiter and not any(depths.values()):
            out.append(text[start:index])
            start = index + 1
    out.append(text[start:])
    return out


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", text)
