"""Deterministic C++ receiver-type facts and one-hop return propagation.

The implementation intentionally remains conservative: it binds only declarations,
class members, and direct ``auto x = receiver.Method(...)`` assignments whose source
or official return type is unique. Anything else remains unresolved for downstream
review rather than being guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from uo.scripts.function_body import CallSite, FunctionDefinition


_DECL_QUALIFIERS = frozenset(
    {
        "const", "volatile", "static", "mutable", "typename", "struct", "class",
        "register", "extern", "inline", "constexpr", "consteval", "friend", "virtual",
        "explicit", "__aicore__", "__host__", "__device__", "__global__", "__forceinline__",
    }
)
_CONTROL_PREFIXES = (
    "return ", "if ", "if(", "for ", "for(", "while ", "while(", "switch ",
    "switch(", "using ", "typedef ", "static_assert", "template ", "enum ",
    "case ", "break", "continue", "goto ", "do ",
)
_CLASS_OPEN_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)\b[^;{]{0,500}\{")
_AUTO_ASSIGN_RE = re.compile(
    r"^\s*auto\s*(?:&&|&|\*)?\s*([A-Za-z_]\w*)\s*=\s*(.*?)\s*$",
    re.DOTALL,
)
_CALL_EXPR_RE = re.compile(
    r"^(?:(?P<receiver>(?:this\s*->\s*)?[A-Za-z_]\w*(?:\s*\[[^\]]*\])?)\s*(?:\.|->)\s*)?"
    r"(?:template\s+)?(?P<method>[A-Za-z_]\w*)\s*(?:<(?P<template>.*)>)?\s*\((?P<args>.*)\)$",
    re.DOTALL,
)


@dataclass(frozen=True)
class TypeBinding:
    name: str
    type_name: str
    line: int
    source: str


@dataclass
class ReceiverTypeFacts:
    bindings_by_function: dict[str, list[TypeBinding]] = field(default_factory=dict)
    member_types_by_class: dict[str, dict[str, str]] = field(default_factory=dict)
    return_types_by_method: dict[tuple[str, str, int], set[str]] = field(default_factory=dict)
    return_types_by_name: dict[tuple[str, int], set[str]] = field(default_factory=dict)

    def add_binding(self, function_id: str, binding: TypeBinding) -> None:
        bucket = self.bindings_by_function.setdefault(function_id, [])
        if binding not in bucket:
            bucket.append(binding)
            bucket.sort(key=lambda item: (item.line, item.name, item.source))


@dataclass(frozen=True)
class _AutoAssignment:
    function_id: str
    caller_class: str
    name: str
    receiver: str
    method: str
    argument_count: int
    line: int


def build_receiver_type_facts(
    functions: list[FunctionDefinition],
    source_texts: Mapping[Any, str] | None = None,
    *,
    official_contracts: Mapping[str, list[dict[str, Any]]] | None = None,
) -> ReceiverTypeFacts:
    facts = ReceiverTypeFacts()
    source_by_rel = {str(path).replace("\\", "/"): str(text or "") for path, text in (source_texts or {}).items()}

    for raw_path, text in source_by_rel.items():
        _collect_class_members(text, facts)

    assignments: list[_AutoAssignment] = []
    for fn in functions:
        return_type = _extract_return_type(fn)
        arity = _signature_arity(fn.normalized_signature)
        if return_type and arity >= 0:
            owner = _normalize_type_name(fn.class_or_namespace)
            if owner:
                facts.return_types_by_method.setdefault((owner, fn.name, arity), set()).add(return_type)
            facts.return_types_by_name.setdefault((fn.name, arity), set()).add(return_type)

        for name, type_name in _parameter_bindings(fn.header_text, fn.name):
            facts.add_binding(fn.stable_id, TypeBinding(name, type_name, fn.start_line, "parameter"))

        body_text = fn.body_text or ""
        opening_brace = body_text.find("{")
        scan_offset = opening_brace + 1 if opening_brace >= 0 else 0
        scan_text = body_text[scan_offset:]
        for statement, offset in _iter_semicolon_statements(scan_text):
            line = fn.start_line + body_text[: scan_offset + offset].count("\n")
            auto_assignment = _parse_auto_assignment(statement, fn, line)
            if auto_assignment is not None:
                assignments.append(auto_assignment)
                continue
            declared = _parse_declaration(statement)
            if declared is not None:
                name, type_name = declared
                facts.add_binding(fn.stable_id, TypeBinding(name, type_name, line, "local"))

    for assignment in assignments:
        receiver_type = _lookup_receiver_expression(
            assignment.receiver,
            assignment.function_id,
            assignment.caller_class,
            assignment.line,
            facts,
        )
        return_type = _unique_return_type(
            receiver_type,
            assignment.method,
            assignment.argument_count,
            facts,
            official_contracts or {},
        )
        if return_type:
            facts.add_binding(
                assignment.function_id,
                TypeBinding(assignment.name, return_type, assignment.line, "one_hop_return"),
            )
    return facts


def infer_receiver_type(
    site: CallSite,
    caller: FunctionDefinition,
    facts: ReceiverTypeFacts | None,
    *,
    official_contracts: Mapping[str, list[dict[str, Any]]] | None = None,
) -> str:
    if facts is None:
        return ""
    receiver = _strip_receiver_suffix(site.receiver_type_or_object)
    if not receiver:
        return ""
    if receiver == "this":
        return caller.class_or_namespace

    chained = _parse_call_expression(receiver)
    if chained is not None:
        base, method, argument_count = chained
        base_type = _lookup_receiver_expression(
            base,
            caller.stable_id,
            caller.class_or_namespace,
            site.line,
            facts,
        )
        return _unique_return_type(
            base_type,
            method,
            argument_count,
            facts,
            official_contracts or {},
        )

    return _lookup_receiver_expression(
        receiver,
        caller.stable_id,
        caller.class_or_namespace,
        site.line,
        facts,
    )


def _lookup_receiver_expression(
    expression: str,
    function_id: str,
    caller_class: str,
    line: int,
    facts: ReceiverTypeFacts,
) -> str:
    text = _strip_receiver_suffix(expression)
    text = re.sub(r"\s*\[[^\]]*\]\s*$", "", text)
    text = text.strip()
    if text == "this":
        return caller_class
    if text.startswith("this->"):
        text = text.split("->", 1)[1].strip()

    matches = [
        item for item in facts.bindings_by_function.get(function_id, [])
        if item.name == text and item.line <= line
    ]
    if matches:
        return matches[-1].type_name

    owner = _normalize_type_name(caller_class)
    member = facts.member_types_by_class.get(owner, {}).get(text)
    if member:
        return member
    return ""


def _unique_return_type(
    receiver_type: str,
    method: str,
    argument_count: int,
    facts: ReceiverTypeFacts,
    official_contracts: Mapping[str, list[dict[str, Any]]],
) -> str:
    candidates: set[str] = set()
    owner = _normalize_type_name(receiver_type)
    if owner:
        candidates.update(facts.return_types_by_method.get((owner, method, argument_count), set()))
    elif method:
        candidates.update(facts.return_types_by_name.get((method, argument_count), set()))

    for contract in official_contracts.get(method, []):
        counts = {int(value) for value in contract.get("argument_counts") or []}
        if counts and argument_count not in counts:
            continue
        allowed = [str(value or "") for value in contract.get("receiver_types") or []]
        if allowed and (not receiver_type or not any(_type_matches(receiver_type, item) for item in allowed)):
            continue
        return_type = _normalize_declared_type(str(contract.get("return_type") or ""))
        if return_type:
            candidates.add(return_type)

    normalized = {_normalize_declared_type(item) for item in candidates if _normalize_declared_type(item)}
    if not normalized:
        return ""
    base_names = {_normalize_type_name(item) for item in normalized}
    if len(base_names) != 1:
        return ""
    return sorted(normalized, key=lambda value: (len(value), value))[0]


def _collect_class_members(text: str, facts: ReceiverTypeFacts) -> None:
    for match in _CLASS_OPEN_RE.finditer(text):
        end = _matching_brace(text, match.end() - 1)
        if end is None:
            continue
        owner = _normalize_type_name(match.group(1))
        body = text[match.end():end]
        for statement, _offset in _iter_class_member_statements(body):
            declared = _parse_declaration(statement)
            if declared is None:
                continue
            name, type_name = declared
            facts.member_types_by_class.setdefault(owner, {}).setdefault(name, type_name)


def _parameter_bindings(header: str, function_name: str) -> list[tuple[str, str]]:
    open_paren = _function_parameter_open(header, function_name)
    if open_paren < 0:
        return []
    close_paren = _matching_delimiter(header, open_paren, "(", ")")
    if close_paren is None:
        return []
    out: list[tuple[str, str]] = []
    for clause in _split_top_level(header[open_paren + 1:close_paren], ","):
        declared = _parse_declaration(clause)
        if declared is not None:
            out.append(declared)
    return out


def _parse_declaration(statement: str) -> tuple[str, str] | None:
    text = _strip_comments(statement).strip()
    text = re.sub(r"^(?:public|private|protected)\s*:\s*", "", text).strip()
    if not text or text.startswith(_CONTROL_PREFIXES):
        return None
    text = _strip_top_level_initializer(text)
    text = text.rstrip(";").strip()
    if not text or "(" in _strip_template_text(text):
        return None
    if _top_level_contains(text, ","):
        return None

    match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", text)
    if not match:
        return None
    name = match.group(1)
    prefix = text[:match.start()].strip()
    if not prefix or any(ch in prefix for ch in "{};"):
        return None
    type_name = _normalize_declared_type(prefix)
    if (
        not type_name
        or any(ch in type_name for ch in "{};")
        or _normalize_type_name(type_name) in {"auto", "void"}
    ):
        return None
    return name, type_name


def _parse_auto_assignment(statement: str, fn: FunctionDefinition, line: int) -> _AutoAssignment | None:
    match = _AUTO_ASSIGN_RE.match(_strip_comments(statement).rstrip(";").strip())
    if not match:
        return None
    parsed = _parse_call_expression(match.group(2))
    if parsed is None:
        return None
    receiver, method, argument_count = parsed
    return _AutoAssignment(
        function_id=fn.stable_id,
        caller_class=fn.class_or_namespace,
        name=match.group(1),
        receiver=receiver,
        method=method,
        argument_count=argument_count,
        line=line,
    )


def _parse_call_expression(expression: str) -> tuple[str, str, int] | None:
    text = expression.strip()
    while text.startswith("(") and text.endswith(")"):
        close = _matching_delimiter(text, 0, "(", ")")
        if close != len(text) - 1:
            break
        text = text[1:-1].strip()
    match = _CALL_EXPR_RE.match(text)
    if not match:
        return None
    receiver = (match.group("receiver") or "").replace(" ", "")
    args = match.group("args") or ""
    return receiver, match.group("method"), _argument_count(args)


def _extract_return_type(fn: FunctionDefinition) -> str:
    header = str(fn.header_text or "")
    open_paren = _function_parameter_open(header, fn.name)
    if open_paren < 0:
        return ""
    name_start = header.rfind(fn.name, 0, open_paren)
    if name_start < 0:
        return ""
    if _normalize_type_name(fn.class_or_namespace) == fn.name or header[max(0, name_start - 1):name_start] == "~":
        return ""
    prefix = header[:name_start]
    prefix = re.split(r"[;}]", prefix)[-1]
    prefix = re.sub(r"template\s*<.*?>\s*", " ", prefix, flags=re.DOTALL)
    prefix = re.sub(r"(?:[A-Za-z_]\w*(?:\s*<[^;{}]*>)?\s*::\s*)+$", "", prefix).strip()
    tokens = []
    for token in re.split(r"\s+", prefix):
        if not token or token in _DECL_QUALIFIERS or token.startswith("__attribute__"):
            continue
        tokens.append(token)
    if not tokens:
        return ""
    return_type = _normalize_declared_type(" ".join(tokens))
    if _normalize_type_name(return_type) in {"auto", "void"}:
        trailing = re.search(r"->\s*([^\{]+)$", header[: header.find("{") if "{" in header else len(header)])
        return _normalize_declared_type(trailing.group(1)) if trailing else ""
    return return_type


def _function_parameter_open(header: str, name: str) -> int:
    for match in re.finditer(rf"\b{re.escape(name)}\s*\(", header):
        return header.find("(", match.start())
    return -1


def _iter_class_member_statements(text: str):
    """Yield only class-scope semicolon statements, skipping inline method bodies."""
    start = 0
    index = 0
    paren = bracket = 0
    quote = ""
    escape = False
    while index < len(text):
        ch = text[index]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            index += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            index += 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket = max(0, bracket - 1)
        elif ch == "{" and paren == 0 and bracket == 0:
            end = _matching_brace(text, index)
            if end is None:
                return
            start = end + 1
            index = end + 1
            continue
        elif ch == ";" and paren == 0 and bracket == 0:
            yield text[start:index], start
            start = index + 1
        index += 1


def _iter_semicolon_statements(text: str, *, top_level_braces: bool = False):
    start = 0
    paren = bracket = brace = 0
    quote = ""
    escape = False
    for index, ch in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket = max(0, bracket - 1)
        elif ch == "{":
            brace += 1
        elif ch == "}":
            brace = max(0, brace - 1)
        elif ch == ";" and paren == 0 and bracket == 0 and (not top_level_braces or brace == 0):
            yield text[start:index], start
            start = index + 1


def _matching_brace(text: str, open_pos: int) -> int | None:
    return _matching_delimiter(text, open_pos, "{", "}")


def _matching_delimiter(text: str, open_pos: int, opening: str, closing: str) -> int | None:
    depth = 0
    quote = ""
    escape = False
    for index in range(open_pos, len(text)):
        ch = text[index]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
            continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_top_level(text: str, delimiter: str) -> list[str]:
    out: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    pairs = {")": "(", "]": "[", "}": "{", ">": "<"}
    quote = ""
    escape = False
    for index, ch in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
            continue
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


def _strip_top_level_initializer(text: str) -> str:
    parts = _split_top_level(text, "=")
    return parts[0].strip() if len(parts) > 1 else text


def _top_level_contains(text: str, delimiter: str) -> bool:
    return len(_split_top_level(text, delimiter)) > 1


def _strip_template_text(text: str) -> str:
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
            continue
        if ch == ">" and depth:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", text)


def _strip_receiver_suffix(receiver: str) -> str:
    text = str(receiver or "").strip()
    if text.endswith("->"):
        text = text[:-2]
    elif text.endswith("."):
        text = text[:-1]
    return text.strip()


def _normalize_declared_type(type_name: str) -> str:
    text = str(type_name or "").strip()
    text = re.sub(r"\b(?:const|volatile|static|mutable|typename|struct|class|register|extern)\b", " ", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("*& ")


def _normalize_type_name(type_name: str) -> str:
    text = _normalize_declared_type(type_name)
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
            continue
        if ch == ">":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip().split("::")[-1]


def _type_matches(left: str, right: str) -> bool:
    return bool(_normalize_type_name(left) and _normalize_type_name(left) == _normalize_type_name(right))


def _signature_arity(signature: str) -> int:
    text = str(signature or "").strip()
    if not text.startswith("(") or not text.endswith(")"):
        return -1
    return _argument_count(text[1:-1])


def _argument_count(arguments: str) -> int:
    text = str(arguments or "").strip()
    if not text or text == "void":
        return 0
    return len(_split_top_level(text, ","))
