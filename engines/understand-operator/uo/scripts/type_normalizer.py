"""Conservative C++ type-alias and template normalization."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

_ALIAS_RE = re.compile(
    r"\busing\s+([A-Za-z_]\w*)\s*=\s*([^;]+);|"
    r"\btypedef\s+([^;]+?)\s+([A-Za-z_]\w*)\s*;",
    re.DOTALL,
)
_TEMPLATE_CLASS_RE = re.compile(
    r"template\s*<(?P<params>.*?)>\s*(?:class|struct)\s+"
    r"(?P<name>[A-Za-z_]\w*)(?:\s*<(?P<specialization>.*?)>)?[^;{]*\{",
    re.DOTALL,
)
_MEMBER_ALIAS_RE = re.compile(
    r"\busing\s+([A-Za-z_]\w*)\s*=\s*([^;]+);|"
    r"\btypedef\s+([^;]+?)\s+([A-Za-z_]\w*)\s*;",
    re.DOTALL,
)


@dataclass(frozen=True)
class TemplateMemberAlias:
    owner: str
    member: str
    parameters: tuple[str, ...]
    expression: str
    specialization: tuple[str, ...] = ()


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


def collect_template_member_aliases(
    source_texts: Mapping[object, str] | None,
) -> dict[tuple[str, str], list[TemplateMemberAlias]]:
    out: dict[tuple[str, str], list[TemplateMemberAlias]] = {}
    for text in (source_texts or {}).values():
        source = _strip_comments(str(text or ""))
        for match in _TEMPLATE_CLASS_RE.finditer(source):
            end = _matching_brace(source, match.end() - 1)
            if end is None:
                continue
            params = tuple(_template_parameter_name(item) for item in _split_top_level(match.group("params"), ","))
            params = tuple(item for item in params if item)
            specialization = tuple(
                normalize_declared_type(item)
                for item in _split_top_level(match.group("specialization") or "", ",")
                if normalize_declared_type(item)
            )
            body = source[match.end():end]
            for alias_match in _MEMBER_ALIAS_RE.finditer(body):
                if alias_match.group(1):
                    member, expression = alias_match.group(1), alias_match.group(2)
                else:
                    member, expression = alias_match.group(4), alias_match.group(3)
                expression = normalize_declared_type(expression)
                if not expression:
                    continue
                record = TemplateMemberAlias(
                    owner=match.group("name"),
                    member=member,
                    parameters=params,
                    expression=expression,
                    specialization=specialization,
                )
                out.setdefault((record.owner, record.member), []).append(record)
    return out


def expand_type_candidates(
    type_name: str,
    aliases: Mapping[str, set[str]] | None = None,
    *,
    member_aliases: Mapping[tuple[str, str], list[TemplateMemberAlias]] | None = None,
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
            expanded = _expand_once(value, aliases or {}, member_aliases or {})
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
    parsed = _parse_template_instance(text)
    if parsed:
        return parsed[0].split("::")[-1]
    return text.split("::")[-1]


def normalize_declared_type(type_name: str) -> str:
    text = str(type_name or "").strip()
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|struct|class|register|extern)\b", " ", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("*& ")


def _expand_once(
    value: str,
    aliases: Mapping[str, set[str]],
    member_aliases: Mapping[tuple[str, str], list[TemplateMemberAlias]],
) -> set[str]:
    nested = _expand_template_member(value, member_aliases)
    if nested:
        return nested
    base = canonical_base(value)
    if base in aliases:
        return set(aliases[base])
    conditional = _conditional_branches(value)
    if conditional:
        return conditional
    return {value}


def _expand_template_member(
    value: str,
    member_aliases: Mapping[tuple[str, str], list[TemplateMemberAlias]],
) -> set[str]:
    split = _split_nested_member(value)
    if split is None:
        return set()
    owner_expr, member = split
    parsed = _parse_template_instance(owner_expr)
    if parsed is None:
        return set()
    owner, arguments = parsed
    records = member_aliases.get((owner.split("::")[-1], member), [])
    results: set[str] = set()
    for record in records:
        if record.specialization and not _specialization_matches(record.specialization, arguments, record.parameters):
            continue
        if len(record.parameters) != len(arguments):
            continue
        substitutions = dict(zip(record.parameters, arguments))
        expression = record.expression
        for parameter, argument in sorted(substitutions.items(), key=lambda item: -len(item[0])):
            expression = re.sub(rf"\b{re.escape(parameter)}\b", argument, expression)
        normalized = normalize_declared_type(expression)
        if normalized:
            results.add(normalized)
    return results


def _specialization_matches(
    specialization: tuple[str, ...], arguments: tuple[str, ...], parameters: tuple[str, ...]
) -> bool:
    if len(specialization) != len(arguments):
        return False
    parameter_set = set(parameters)
    for expected, actual in zip(specialization, arguments):
        if expected in parameter_set:
            continue
        if normalize_declared_type(expected) != normalize_declared_type(actual):
            return False
    return True


def _split_nested_member(value: str) -> tuple[str, str] | None:
    depth = 0
    split_at = -1
    index = 0
    while index < len(value) - 1:
        ch = value[index]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == ":" and value[index:index + 2] == "::" and depth == 0:
            split_at = index
            index += 1
        index += 1
    if split_at < 0:
        return None
    owner, member = value[:split_at], value[split_at + 2:]
    if not re.fullmatch(r"[A-Za-z_]\w*", member):
        return None
    return owner, member


def _parse_template_instance(value: str) -> tuple[str, tuple[str, ...]] | None:
    open_pos = value.find("<")
    if open_pos < 0:
        return None
    close_pos = _matching_angle(value, open_pos)
    if close_pos is None or close_pos != len(value) - 1:
        return None
    owner = value[:open_pos]
    arguments = tuple(
        normalize_declared_type(item)
        for item in _split_top_level(value[open_pos + 1:close_pos], ",")
    )
    return owner, arguments


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
    suffix = value[close_pos + 1:]
    if suffix not in {"::type", "::type_t", ""}:
        return set()
    args = _split_top_level(value[open_pos + 1:close_pos], ",")
    if len(args) != 3:
        return set()
    return {normalize_declared_type(args[1]), normalize_declared_type(args[2])} - {""}


def _template_parameter_name(clause: str) -> str:
    text = normalize_declared_type(clause.split("=", 1)[0])
    match = re.search(r"([A-Za-z_]\w*)$", text)
    return match.group(1) if match else ""


def _matching_brace(text: str, open_pos: int) -> int | None:
    depth = 0
    for index in range(open_pos, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


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
