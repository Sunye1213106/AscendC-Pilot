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
_MEMBER_ALIAS_RE = _ALIAS_RE


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
            name, expression = ((match.group(1), match.group(2)) if match.group(1) else (match.group(4), match.group(3)))
            normalized = normalize_declared_type(expression)
            if normalized:
                aliases.setdefault(name, set()).add(normalized)
    return aliases


def collect_template_member_aliases(source_texts: Mapping[object, str] | None) -> dict[tuple[str, str], list[TemplateMemberAlias]]:
    out: dict[tuple[str, str], list[TemplateMemberAlias]] = {}
    for text in (source_texts or {}).values():
        source = _strip_comments(str(text or ""))
        for match in _TEMPLATE_CLASS_RE.finditer(source):
            end = _matching_delimiter(source, match.end() - 1, "{", "}")
            if end is None:
                continue
            params = tuple(filter(None, (_template_parameter_name(x) for x in _split_top_level(match.group("params"), ","))))
            specialization = tuple(normalize_declared_type(x) for x in _split_top_level(match.group("specialization") or "", ",") if normalize_declared_type(x))
            body = source[match.end():end]
            for alias_match in _MEMBER_ALIAS_RE.finditer(body):
                member, expression = ((alias_match.group(1), alias_match.group(2)) if alias_match.group(1) else (alias_match.group(4), alias_match.group(3)))
                expression = normalize_declared_type(expression)
                if expression:
                    record = TemplateMemberAlias(match.group("name"), member, params, expression, specialization)
                    out.setdefault((record.owner, record.member), []).append(record)
    return out


def expand_type_candidates(type_name: str, aliases: Mapping[str, set[str]] | None = None, *, member_aliases: Mapping[tuple[str, str], list[TemplateMemberAlias]] | None = None, max_depth: int = 2) -> set[str]:
    seed = normalize_declared_type(type_name)
    if not seed:
        return set()
    current = {seed}
    for _ in range(max(0, max_depth)):
        next_values: set[str] = set()
        changed = False
        for value in current:
            expanded = _expand_once(value, aliases or {}, member_aliases or {})
            next_values.update(expanded)
            changed |= expanded != {value}
        current = {normalize_declared_type(x) for x in next_values if normalize_declared_type(x)} or current
        if not changed:
            break
    return current


def canonical_base(type_name: str) -> str:
    text = normalize_declared_type(type_name)
    nested = _split_nested_member(text)
    if nested:
        text = nested[0]
    parsed = _parse_template_instance(text)
    return (parsed[0] if parsed else text).split("::")[-1]


def normalize_declared_type(type_name: str) -> str:
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|struct|class|register|extern)\b", " ", str(type_name or "").strip())
    return re.sub(r"\s+", "", text).strip("*& ")


def _expand_once(value: str, aliases: Mapping[str, set[str]], member_aliases: Mapping[tuple[str, str], list[TemplateMemberAlias]]) -> set[str]:
    nested = _expand_template_member(value, member_aliases)
    if nested:
        return nested
    base = canonical_base(value)
    if base in aliases:
        return set(aliases[base])
    conditional = _conditional_branches(value)
    return conditional or {value}


def _expand_template_member(value: str, member_aliases: Mapping[tuple[str, str], list[TemplateMemberAlias]]) -> set[str]:
    split = _split_nested_member(value)
    if split is None:
        return set()
    owner_expr, member = split
    parsed = _parse_template_instance(owner_expr)
    if parsed is None:
        return set()
    owner, arguments = parsed
    results: set[str] = set()
    for record in member_aliases.get((owner.split("::")[-1], member), []):
        substitutions = _bind_template_arguments(record, arguments)
        if substitutions is None:
            continue
        expression = record.expression
        for parameter, argument in sorted(substitutions.items(), key=lambda item: -len(item[0])):
            expression = re.sub(rf"\b{re.escape(parameter)}\b", argument, expression)
        normalized = normalize_declared_type(expression)
        if normalized:
            results.add(normalized)
    return results


def _bind_template_arguments(record: TemplateMemberAlias, arguments: tuple[str, ...]) -> dict[str, str] | None:
    if not record.specialization:
        return dict(zip(record.parameters, arguments)) if len(record.parameters) == len(arguments) else None
    if len(record.specialization) != len(arguments):
        return None
    parameter_set = set(record.parameters)
    substitutions: dict[str, str] = {}
    for expected, actual in zip(record.specialization, arguments):
        if expected in parameter_set:
            prior = substitutions.get(expected)
            if prior is not None and prior != actual:
                return None
            substitutions[expected] = actual
        elif normalize_declared_type(expected) != normalize_declared_type(actual):
            return None
    return substitutions


def _split_nested_member(value: str) -> tuple[str, str] | None:
    depth = 0
    split_at = -1
    i = 0
    while i < len(value) - 1:
        if value[i] == "<": depth += 1
        elif value[i] == ">": depth = max(0, depth - 1)
        elif value[i:i+2] == "::" and depth == 0:
            split_at = i; i += 1
        i += 1
    if split_at < 0:
        return None
    owner, member = value[:split_at], value[split_at+2:]
    return (owner, member) if re.fullmatch(r"[A-Za-z_]\w*", member) else None


def _parse_template_instance(value: str) -> tuple[str, tuple[str, ...]] | None:
    open_pos = value.find("<")
    if open_pos < 0:
        return None
    close_pos = _matching_delimiter(value, open_pos, "<", ">")
    if close_pos != len(value) - 1:
        return None
    return value[:open_pos], tuple(normalize_declared_type(x) for x in _split_top_level(value[open_pos+1:close_pos], ","))


def _conditional_branches(value: str) -> set[str]:
    for marker, suffix_required in (("std::conditional_t<", False), ("conditional_t<", False), ("std::conditional<", True), ("conditional<", True)):
        start = value.find(marker)
        if start < 0:
            continue
        open_pos = start + len(marker) - 1
        close_pos = _matching_delimiter(value, open_pos, "<", ">")
        if close_pos is None:
            return set()
        suffix = value[close_pos+1:]
        if suffix_required and suffix not in {"::type", "::type_t", ""}:
            return set()
        if not suffix_required and suffix:
            return set()
        args = _split_top_level(value[open_pos+1:close_pos], ",")
        return {normalize_declared_type(args[1]), normalize_declared_type(args[2])} - {""} if len(args) == 3 else set()
    return set()


def _template_parameter_name(clause: str) -> str:
    match = re.search(r"([A-Za-z_]\w*)$", normalize_declared_type(clause.split("=", 1)[0]))
    return match.group(1) if match else ""


def _matching_delimiter(text: str, open_pos: int, opening: str, closing: str) -> int | None:
    depth = 0
    for index in range(open_pos, len(text)):
        if text[index] == opening: depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0: return index
    return None


def _split_top_level(text: str, delimiter: str) -> list[str]:
    out, start = [], 0
    depths = {"(":0,"[":0,"{":0,"<":0}; pairs = {")":"(","]":"[","}":"{",">":"<"}
    for index, ch in enumerate(text):
        if ch in depths: depths[ch] += 1
        elif ch in pairs: depths[pairs[ch]] = max(0, depths[pairs[ch]] - 1)
        elif ch == delimiter and not any(depths.values()): out.append(text[start:index]); start = index + 1
    out.append(text[start:])
    return out


def _strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*", " ", re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL))
