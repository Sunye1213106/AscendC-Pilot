"""Deterministic call-signature facts for overload disambiguation.

Parses function template/parameter signatures, infers call-argument types from
local facts, and filters candidates conservatively. Unknown argument types never
force a unique winner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from uo.scripts.function_body import CallSite, FunctionDefinition
from uo.scripts.receiver_type_facts import (
    ReceiverTypeFacts,
    _lookup_receiver_expression,
    _matching_delimiter,
    _split_top_level,
)
from uo.scripts.type_normalizer import canonical_base, normalize_declared_type


_TYPE_TEMPLATE_PREFIXES = ("typename", "class")
_KNOWN_NONTYPE_TYPES = frozenset(
    {
        "bool",
        "int",
        "uint32_t",
        "int32_t",
        "uint64_t",
        "int64_t",
        "uint8_t",
        "int8_t",
        "size_t",
        "unsigned",
        "long",
        "short",
        "char",
    }
)
_INT_FAMILY = frozenset(
    {
        "bool",
        "char",
        "short",
        "int",
        "long",
        "unsigned",
        "signed",
        "size_t",
        "ssize_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "int64",
        "uint64",
    }
)
_TENSOR_FAMILY = frozenset({"LocalTensor", "GlobalTensor"})
_CAST_RE = re.compile(
    r"^(?:static_cast|reinterpret_cast|const_cast)\s*<\s*(?P<type>.+?)\s*>\s*\((?P<inner>.*)\)\s*$",
    re.DOTALL,
)
_SIMPLE_NAME_RE = re.compile(r"^(?:this\s*->\s*)?(?P<name>[A-Za-z_]\w*)\s*$")
_SUBSCRIPT_RE = re.compile(r"^(?:this\s*->\s*)?(?P<name>[A-Za-z_]\w*)\s*\[(?P<index>.*)\]\s*$", re.DOTALL)
_ARROW_FIELD_RE = re.compile(
    r"^(?P<base>[A-Za-z_]\w*)\s*->\s*(?P<field>[A-Za-z_]\w*)\s*$"
)
_COMPLEX_EXPR_RE = re.compile(r"[?:+\-/]|&&|\|\||\b(?:sizeof|alignof)\b")


@dataclass(frozen=True)
class TemplateParameter:
    name: str
    kind: str
    default: str | None = None


@dataclass(frozen=True)
class FunctionSignatureFacts:
    function_id: str
    template_parameters: tuple[TemplateParameter, ...]
    parameter_types: tuple[str, ...]
    parameter_kinds: tuple[str, ...]
    return_type: str
    variadic: bool
    min_arity: int
    max_arity: int
    raw_parameter_clauses: tuple[str, ...] = ()


@dataclass(frozen=True)
class CallArgumentFacts:
    expression: str
    type_candidates: tuple[str, ...]


@dataclass(frozen=True)
class SignatureMatch:
    function_id: str
    compatible: bool
    deterministic: bool
    template_bindings: dict[str, str]
    reasons: tuple[str, ...]
    argument_matches: tuple[str, ...] = ()
    confidence: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "compatible": self.compatible,
            "deterministic": self.deterministic,
            "template_bindings": dict(self.template_bindings),
            "reasons": list(self.reasons),
            "argument_matches": list(self.argument_matches),
            "confidence": self.confidence,
            "signature_match": {
                "arity": "exact" if "arity_exact" in self.reasons else (
                    "compatible" if "arity_compatible" in self.reasons else "unknown"
                ),
                "receiver": "exact" if "receiver_scope" in self.reasons else "unknown",
                "explicit_template_args": (
                    "exact" if "template_args_exact" in self.reasons else (
                        "incompatible" if not self.compatible and "template_mismatch" in self.reasons
                        else "unknown"
                    )
                ),
                "argument_types": list(self.argument_matches),
                "confidence": "deterministic" if self.deterministic else self.confidence,
            },
        }


def function_declarator_text(fn: FunctionDefinition) -> str:
    """Return the declarator span (up to ``{``) preferring multiline body text."""
    body = str(fn.body_text or "")
    brace = body.find("{")
    if brace >= 0:
        return body[: brace + 1]
    header = str(fn.header_text or "")
    if header and not header.rstrip().endswith("{"):
        return header + " {"
    return header


def build_signature_index(
    functions: list[FunctionDefinition],
    source_texts: Mapping[Any, str] | None = None,
) -> dict[str, FunctionSignatureFacts]:
    source_by_rel = {
        str(path).replace("\\", "/"): str(text or "")
        for path, text in (source_texts or {}).items()
    }
    decl_defaults = _collect_declaration_defaults(source_by_rel)
    out: dict[str, FunctionSignatureFacts] = {}
    for fn in functions:
        out[fn.stable_id] = _signature_for_function(fn, source_by_rel, decl_defaults)
    return out


def enrich_call_site_arguments(
    site: CallSite,
    *,
    source_text: str = "",
) -> CallSite:
    """Fill structured template/argument expression fields when missing."""
    explicit = site.explicit_template_arguments
    if not explicit and site.template_args:
        explicit = tuple(
            part.strip()
            for part in _split_top_level(site.template_args, ",")
            if part.strip()
        )
    expressions = site.argument_expressions
    if not expressions and site.argument_count > 0 and source_text:
        expressions = _argument_expressions_from_source(site, source_text)
    if (
        explicit == site.explicit_template_arguments
        and expressions == site.argument_expressions
    ):
        return site
    return CallSite(
        caller_function_id=site.caller_function_id,
        callee_name=site.callee_name,
        callee_qualified_hint=site.callee_qualified_hint,
        call_expression=site.call_expression,
        file_path=site.file_path,
        line=site.line,
        receiver_type_or_object=site.receiver_type_or_object,
        template_args=site.template_args,
        argument_count=site.argument_count,
        ordinal_in_function=site.ordinal_in_function,
        snippet_hash=site.snippet_hash,
        explicit_template_arguments=explicit,
        argument_expressions=expressions,
        argument_type_candidates=site.argument_type_candidates,
    )


def infer_call_argument_facts(
    site: CallSite,
    caller: FunctionDefinition,
    receiver_facts: ReceiverTypeFacts | None,
    *,
    source_text: str = "",
) -> tuple[CallArgumentFacts, ...]:
    site = enrich_call_site_arguments(site, source_text=source_text)
    expressions = site.argument_expressions
    if not expressions and site.argument_count > 0:
        expressions = tuple("" for _ in range(site.argument_count))
    out: list[CallArgumentFacts] = []
    for expression in expressions:
        types = _infer_expression_types(
            expression,
            caller,
            site.line,
            receiver_facts,
        )
        out.append(CallArgumentFacts(expression=expression, type_candidates=types))
    return tuple(out)


def filter_candidates_by_signature(
    site: CallSite,
    caller: FunctionDefinition,
    candidates: list[FunctionDefinition],
    *,
    signature_index: Mapping[str, FunctionSignatureFacts],
    receiver_facts: ReceiverTypeFacts | None,
    receiver_type: str = "",
    source_text: str = "",
) -> tuple[list[FunctionDefinition], list[SignatureMatch], bool]:
    """Filter candidates by signature. Returns (kept, matches, unique_deterministic)."""
    if len(candidates) <= 1:
        return candidates, [], len(candidates) == 1

    site = enrich_call_site_arguments(site, source_text=source_text)
    arg_facts = infer_call_argument_facts(
        site, caller, receiver_facts, source_text=source_text
    )
    # Persist inferred type candidates onto a shallow copy for callers/site nodes.
    site.argument_type_candidates = tuple(item.type_candidates for item in arg_facts)
    site.explicit_template_arguments = site.explicit_template_arguments or tuple(
        part.strip()
        for part in _split_top_level(site.template_args, ",")
        if part.strip()
    )
    site.argument_expressions = tuple(item.expression for item in arg_facts)

    matches: list[SignatureMatch] = []
    kept: list[FunctionDefinition] = []
    unknown_blocked = False
    for candidate in candidates:
        signature = signature_index.get(candidate.stable_id)
        if signature is None:
            signature = _signature_for_function(candidate, {}, {})
        match = match_call_to_signature(
            site,
            signature,
            arg_facts,
            receiver_type=receiver_type,
            candidate_owner=candidate.class_or_namespace,
        )
        matches.append(match)
        if match.compatible:
            kept.append(candidate)
            if not match.deterministic:
                unknown_blocked = True

    if not kept:
        # Fail open: keep original candidates when every structured filter rejects.
        return candidates, matches, False

    unique = len(kept) == 1 and not unknown_blocked and matches_unique(kept, matches)
    return kept, matches, unique


def matches_unique(
    kept: list[FunctionDefinition], matches: list[SignatureMatch]
) -> bool:
    if len(kept) != 1:
        return False
    winner_id = kept[0].stable_id
    winner_matches = [item for item in matches if item.function_id == winner_id]
    if not winner_matches:
        return False
    winner = winner_matches[0]
    if not winner.compatible or not winner.deterministic:
        return False
    # Another compatible deterministic candidate with equal signature evidence?
    peers = [
        item
        for item in matches
        if item.function_id != winner_id and item.compatible and item.deterministic
    ]
    return not peers


def match_call_to_signature(
    site: CallSite,
    signature: FunctionSignatureFacts,
    arg_facts: tuple[CallArgumentFacts, ...],
    *,
    receiver_type: str = "",
    candidate_owner: str = "",
) -> SignatureMatch:
    reasons: list[str] = []
    bindings: dict[str, str] = {}
    explicit = list(site.explicit_template_arguments)
    if not explicit and site.template_args:
        explicit = [
            part.strip()
            for part in _split_top_level(site.template_args, ",")
            if part.strip()
        ]

    # Arity
    argc = int(site.argument_count or 0)
    if signature.variadic:
        if argc < signature.min_arity:
            return SignatureMatch(
                signature.function_id, False, True, {}, ("arity_mismatch",), confidence="deterministic"
            )
        reasons.append("arity_compatible")
    elif not (signature.min_arity <= argc <= signature.max_arity):
        return SignatureMatch(
            signature.function_id, False, True, {}, ("arity_mismatch",), confidence="deterministic"
        )
    else:
        reasons.append("arity_exact" if argc == signature.max_arity else "arity_compatible")

    # Explicit template arguments
    template_ok, template_bindings, template_reasons, template_deterministic = _bind_template_args(
        signature.template_parameters, explicit, signature.parameter_types
    )
    if not template_ok:
        return SignatureMatch(
            signature.function_id,
            False,
            True,
            {},
            ("template_mismatch",) + template_reasons,
            confidence="deterministic",
        )
    bindings.update(template_bindings)
    reasons.extend(template_reasons)

    # Receiver scope is handled upstream; record evidence when present.
    if receiver_type and candidate_owner:
        if _type_base(receiver_type) == _type_base(candidate_owner):
            reasons.append("receiver_scope")

    unbound_type_params = {
        param.name
        for param in signature.template_parameters
        if param.kind in {"type", "type_pack"} and param.name not in bindings
    }
    instantiated_params = [
        _substitute_type(param, bindings) for param in signature.parameter_types
    ]
    argument_matches: list[str] = []
    deterministic = template_deterministic
    confidence = "deterministic"

    for index, param_type in enumerate(instantiated_params):
        if index >= len(arg_facts):
            # Defaulted parameter not supplied.
            argument_matches.append("exact")
            continue
        fact = arg_facts[index]
        status = _argument_compatibility(
            fact.type_candidates,
            param_type,
            bindings,
            unbound_type_params=unbound_type_params,
        )
        argument_matches.append(status)
        if status == "incompatible":
            return SignatureMatch(
                signature.function_id,
                False,
                True,
                bindings,
                tuple(reasons + ["argument_incompatible"]),
                tuple(argument_matches),
                confidence="deterministic",
            )
        if status == "unknown":
            deterministic = False
            confidence = "unknown"
            reasons.append("argument_unknown")
        elif status == "compatible":
            if confidence == "deterministic":
                confidence = "compatible"
            reasons.append("argument_compatible")
        else:
            reasons.append("argument_exact")

    # Extra args only allowed for variadic (already checked).
    return SignatureMatch(
        function_id=signature.function_id,
        compatible=True,
        deterministic=deterministic,
        template_bindings=bindings,
        reasons=tuple(dict.fromkeys(reasons)),
        argument_matches=tuple(argument_matches),
        confidence=confidence,
    )


def _signature_for_function(
    fn: FunctionDefinition,
    source_by_rel: Mapping[str, str],
    decl_defaults: Mapping[tuple[str, str, int], tuple[str, ...]],
) -> FunctionSignatureFacts:
    declarator = function_declarator_text(fn)
    params = _extract_parameter_clauses(declarator, fn.name)
    source = source_by_rel.get(fn.file_path, "")
    templates = _extract_template_parameters(fn, source)
    key = (fn.class_or_namespace or "", fn.name, len(params))
    decl = decl_defaults.get(key)
    if decl and len(decl) == len(params):
        params = _merge_default_clauses(params, decl)

    parameter_types: list[str] = []
    parameter_kinds: list[str] = []
    variadic = False
    for clause in params:
        if clause.strip() == "...":
            variadic = True
            continue
        if clause.strip().endswith("..."):
            variadic = True
        parameter_types.append(_parameter_type(clause))
        parameter_kinds.append(_parameter_kind(clause))

    min_arity = 0
    for clause in params:
        if clause.strip() in {"", "..."}:
            continue
        if len(_split_top_level(clause, "=")) == 1:
            min_arity += 1
        else:
            break
    max_arity = len(parameter_types)
    return_type = _return_type_from_declarator(declarator, fn.name, fn.class_or_namespace)
    return FunctionSignatureFacts(
        function_id=fn.stable_id,
        template_parameters=tuple(templates),
        parameter_types=tuple(parameter_types),
        parameter_kinds=tuple(parameter_kinds),
        return_type=return_type,
        variadic=variadic,
        min_arity=min_arity,
        max_arity=max_arity,
        raw_parameter_clauses=tuple(params),
    )


def _collect_declaration_defaults(
    source_by_rel: Mapping[str, str],
) -> dict[tuple[str, str, int], tuple[str, ...]]:
    """Index in-class/out-of-class declarations that carry default arguments."""
    best: dict[tuple[str, str, int], tuple[int, tuple[str, ...]]] = {}
    class_re = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)\b")
    for source in source_by_rel.values():
        class_stack: list[tuple[str, int]] = []
        brace_depth = 0
        index = 0
        while index < len(source):
            ch = source[index]
            if ch == "{":
                brace_depth += 1
                index += 1
                continue
            if ch == "}":
                brace_depth = max(0, brace_depth - 1)
                while class_stack and class_stack[-1][1] >= brace_depth:
                    class_stack.pop()
                index += 1
                continue
            class_match = class_re.match(source, index)
            if class_match:
                # Class body opens at the next top-level '{' after the name.
                probe = class_match.end()
                while probe < len(source) and source[probe] not in "{;":
                    probe += 1
                if probe < len(source) and source[probe] == "{":
                    class_stack.append((class_match.group(1), brace_depth))
                index = class_match.end()
                continue
            name_match = re.match(r"\b([A-Za-z_]\w*)\s*\(", source[index:])
            if not name_match:
                index += 1
                continue
            name = name_match.group(1)
            abs_name_start = index + name_match.start(1)
            open_paren = index + name_match.end() - 1
            if name in {
                "if", "for", "while", "switch", "catch", "return", "sizeof",
                "alignof", "decltype", "static_assert",
            }:
                index = open_paren + 1
                continue
            close = _matching_delimiter(source, open_paren, "(", ")")
            if close is None:
                index = open_paren + 1
                continue
            post = source[close + 1 : close + 48].lstrip()
            if not (
                post.startswith("{")
                or post.startswith(";")
                or post.startswith("const")
                or post.startswith("override")
                or post.startswith("final")
                or post.startswith("noexcept")
            ):
                index = close + 1
                continue
            params = [
                part.strip()
                for part in _split_top_level(source[open_paren + 1 : close], ",")
                if part.strip() and part.strip() != "void"
            ]
            defaults = sum(1 for part in params if len(_split_top_level(part, "=")) > 1)
            if defaults <= 0:
                index = close + 1
                continue
            pre = source[max(0, abs_name_start - 160) : abs_name_start]
            owner_match = re.search(
                r"([A-Za-z_]\w*)\s*(?:<[^;{}]*>)?\s*::\s*$",
                pre,
            )
            owner = owner_match.group(1) if owner_match else (
                class_stack[-1][0] if class_stack else ""
            )
            key = (owner, name, len(params))
            prev = best.get(key)
            if prev is None or defaults > prev[0]:
                best[key] = (defaults, tuple(params))
            index = close + 1
    return {key: value[1] for key, value in best.items()}


def _merge_default_clauses(definition: list[str], declaration: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for index, clause in enumerate(definition):
        decl = declaration[index] if index < len(declaration) else clause
        if len(_split_top_level(clause, "=")) == 1 and len(_split_top_level(decl, "=")) > 1:
            default = _split_top_level(decl, "=")[1].strip()
            out.append(f"{clause} = {default}")
        else:
            out.append(clause)
    return out


def _extract_parameter_clauses(declarator: str, name: str) -> list[str]:
    open_paren = _function_parameter_open(declarator, name)
    if open_paren < 0:
        return []
    close = _matching_delimiter(declarator, open_paren, "(", ")")
    if close is None:
        return []
    inner = declarator[open_paren + 1 : close].strip()
    if not inner or inner == "void":
        return []
    return [part.strip() for part in _split_top_level(inner, ",") if part.strip()]


def _extract_template_parameters(
    fn: FunctionDefinition, source: str
) -> list[TemplateParameter]:
    lines = source.splitlines() if source else (fn.body_text or "").splitlines()
    if not lines:
        # Fall back to stored template arity string.
        return _parse_template_parameter_list(fn.template_arity_or_signature)

    start = max(0, int(fn.start_line or 1) - 1)
    for index in range(start, max(-1, start - 8), -1):
        chunk = "\n".join(lines[index : start + 1])
        matches = list(re.finditer(r"\btemplate\s*<", chunk))
        if not matches:
            continue
        marker = matches[-1]
        open_angle = chunk.find("<", marker.start())
        close_angle = _matching_delimiter(chunk, open_angle, "<", ">")
        if close_angle is None:
            continue
        after = chunk[close_angle + 1 :]
        name_match = re.search(rf"\b{re.escape(fn.name)}\b", after)
        if not name_match:
            continue
        between = after[: name_match.start()]
        if re.search(r"[;{}]", between):
            continue
        return _parse_template_parameter_list(chunk[open_angle + 1 : close_angle])

    return _parse_template_parameter_list(fn.template_arity_or_signature)


def _parse_template_parameter_list(text: str) -> list[TemplateParameter]:
    inner = str(text or "").strip()
    if inner.startswith("<") and inner.endswith(">"):
        inner = inner[1:-1]
    if not inner:
        return []
    out: list[TemplateParameter] = []
    for part in _split_top_level(inner, ","):
        clause = part.strip()
        if not clause:
            continue
        default = None
        pieces = _split_top_level(clause, "=")
        head = pieces[0].strip()
        if len(pieces) > 1:
            default = pieces[1].strip()
        kind = "nontype"
        name = ""
        type_match = re.match(r"(?:typename|class)\s*\.\.\.\s*([A-Za-z_]\w*)", head)
        if type_match:
            out.append(TemplateParameter(type_match.group(1), "type_pack", default))
            continue
        type_match = re.match(r"(?:typename|class)\s+([A-Za-z_]\w*)\s*$", head)
        if type_match:
            out.append(TemplateParameter(type_match.group(1), "type", default))
            continue
        tokens = head.split()
        if tokens:
            name = tokens[-1]
            prefix = " ".join(tokens[:-1]).strip()
            base = canonical_base(prefix) or prefix
            if base in _KNOWN_NONTYPE_TYPES:
                kind = base
            elif base:
                kind = "nontype"
        if name:
            out.append(TemplateParameter(name, kind, default))
    return out


def _bind_template_args(
    template_parameters: tuple[TemplateParameter, ...] | list[TemplateParameter],
    explicit: list[str],
    parameter_types: tuple[str, ...] | list[str],
) -> tuple[bool, dict[str, str], tuple[str, ...], bool]:
    params = list(template_parameters)
    if explicit:
        # Count required template params (no default).
        required = 0
        for param in params:
            if param.default is None:
                required += 1
            else:
                break
        if not params:
            return False, {}, ("template_args_on_non_template",), True
        if len(explicit) < required or len(explicit) > len(params):
            return False, {}, ("template_arity_mismatch",), True
        bindings: dict[str, str] = {}
        for index, value in enumerate(explicit):
            param = params[index]
            if param.kind == "type" or param.kind == "type_pack":
                # Reject obvious nontype literals in type slots when clearly numeric/bool.
                if re.fullmatch(r"(?:true|false|\d+[uUlL]*)", value.strip()):
                    return False, {}, ("template_kind_mismatch",), True
            elif param.kind in _KNOWN_NONTYPE_TYPES or param.kind == "nontype":
                # Type-looking tokens in nontype slots are still allowed (enums/consts).
                pass
            bindings[param.name] = normalize_declared_type(value) or value.strip()
        for param in params[len(explicit) :]:
            if param.default is not None:
                bindings[param.name] = normalize_declared_type(param.default) or param.default
        return True, bindings, ("template_args_exact",), True

    # No explicit template args: reject templates that require nontype params
    # which cannot be deduced from function parameters.
    param_text = ",".join(parameter_types)
    for param in params:
        if param.default is not None:
            continue
        if param.kind in {"type", "type_pack"}:
            continue
        if param.name and re.search(rf"\b{re.escape(param.name)}\b", param_text):
            continue
        return False, {}, ("template_requires_explicit_nontype",), True
    return True, {}, ("template_deduced_or_absent",), True


def _argument_compatibility(
    arg_types: tuple[str, ...],
    param_type: str,
    bindings: Mapping[str, str],
    *,
    unbound_type_params: set[str] | frozenset[str] | None = None,
) -> str:
    param = normalize_declared_type(_substitute_type(param_type, bindings))
    if not param:
        return "unknown"
    if not arg_types:
        return "unknown"

    param_base = canonical_base(param)
    unbound = unbound_type_params or set()
    # Bare / dependent template type parameters remain deducible.
    if param in unbound or param_base in unbound:
        return "compatible"
    if re.fullmatch(r"[A-Za-z_]\w*", param) and param not in _INT_FAMILY and param_base not in _TENSOR_FAMILY:
        if param in unbound or len(param) <= 2:
            return "compatible"

    best = "incompatible"
    for raw in arg_types:
        arg = normalize_declared_type(raw)
        if not arg:
            continue
        arg_base = canonical_base(arg)
        if arg == param:
            return "exact"
        if arg_base and arg_base == param_base:
            # Same template family with possibly different args after binding.
            if _strip_indirection(arg) == _strip_indirection(param):
                return "exact"
            best = "compatible" if best == "incompatible" else best
            continue
        if _is_pointer(raw) != _is_pointer_type(param_type) and (
            _is_pointer(raw) or _is_pointer_type(param_type)
        ):
            # Keep incompatible for pointer/non-pointer mismatch.
            continue
        if arg_base in _TENSOR_FAMILY and param_base in _TENSOR_FAMILY and arg_base != param_base:
            continue
        if _buffer_manager_conflict(arg_base, param_base):
            continue
        if arg_base in _INT_FAMILY and param_base in _INT_FAMILY:
            best = "compatible"
            continue
        # Dependent template type: LocalTensor<T> vs LocalTensor<float> after binding only.
        if arg_base and param_base and arg_base == param_base:
            best = "exact"
            continue
        if param_base in unbound or any(
            token in unbound for token in re.findall(r"[A-Za-z_]\w*", param)
        ):
            best = "compatible"
    return best


def _infer_expression_types(
    expression: str,
    caller: FunctionDefinition,
    line: int,
    receiver_facts: ReceiverTypeFacts | None,
) -> tuple[str, ...]:
    text = str(expression or "").strip()
    if not text:
        return ()
    while text.startswith("(") and text.endswith(")"):
        close = _matching_delimiter(text, 0, "(", ")")
        if close != len(text) - 1:
            break
        text = text[1:-1].strip()

    cast = _CAST_RE.match(text)
    if cast:
        cast_type = normalize_declared_type(cast.group("type"))
        return (cast_type,) if cast_type else ()

    if text in {"true", "false"}:
        return ("bool",)
    if re.fullmatch(r"\d+[uUlL]*", text):
        if text.lower().endswith("ull") or text.lower().endswith("ll"):
            return ("int64_t",)
        if text.lower().endswith("u"):
            return ("uint32_t",)
        return ("int",)
    if re.fullmatch(r"\d+\.\d*(?:[eE][+-]?\d+)?[fF]?", text):
        return ("float",) if text.endswith(("f", "F")) else ("double",)

    # Pointer dereference.
    if text.startswith("*"):
        inner = text[1:].strip()
        inner_types = _infer_expression_types(inner, caller, line, receiver_facts)
        out = []
        for item in inner_types:
            out.append(normalize_declared_type(item.rstrip("*& ")))
        return tuple(dict.fromkeys(out))

    # Address-of.
    if text.startswith("&") and not text.startswith("&&"):
        inner = text[1:].strip()
        inner_types = _infer_expression_types(inner, caller, line, receiver_facts)
        return tuple(f"{item}*" for item in inner_types if item)

    if _COMPLEX_EXPR_RE.search(text):
        # Keep unknown for arithmetic/ternary/macro-like forms.
        if not _SIMPLE_NAME_RE.match(text) and not _SUBSCRIPT_RE.match(text):
            return ()

    sub = _SUBSCRIPT_RE.match(text)
    if sub:
        base = _lookup_type_name(sub.group("name"), caller, line, receiver_facts)
        return (base,) if base else ()

    arrow = _ARROW_FIELD_RE.match(text)
    if arrow:
        base_type = _lookup_type_name(arrow.group("base"), caller, line, receiver_facts)
        if receiver_facts is None or not base_type:
            return ()
        owner = canonical_base(base_type)
        field = receiver_facts.member_types_by_class.get(owner, {}).get(arrow.group("field"))
        return (field,) if field else ()

    simple = _SIMPLE_NAME_RE.match(text)
    if simple:
        found = _lookup_type_name(simple.group("name"), caller, line, receiver_facts)
        return (found,) if found else ()

    # this->field already covered by simple with this-> prefix
    return ()


def _lookup_type_name(
    name: str,
    caller: FunctionDefinition,
    line: int,
    receiver_facts: ReceiverTypeFacts | None,
) -> str:
    if receiver_facts is None:
        return ""
    return _lookup_receiver_expression(
        name,
        caller.stable_id,
        caller.class_or_namespace,
        line,
        receiver_facts,
    )


def _argument_expressions_from_source(site: CallSite, source_text: str) -> tuple[str, ...]:
    lines = source_text.splitlines()
    if not lines or site.line <= 0 or site.line > len(lines):
        return ()
    # Search a small window around the call line for callee(.
    window = "\n".join(lines[max(0, site.line - 1) : min(len(lines), site.line + 8)])
    pattern = re.compile(rf"\b{re.escape(site.callee_name)}\s*(?:<[^;{{}}]*>)?\s*\(")
    for match in pattern.finditer(window):
        open_paren = window.find("(", match.start())
        close = _matching_delimiter(window, open_paren, "(", ")")
        if close is None:
            continue
        inner = window[open_paren + 1 : close]
        parts = [part.strip() for part in _split_top_level(inner, ",")]
        if len(parts) == site.argument_count or (
            site.argument_count == 0 and (not parts or parts == [""])
        ):
            if site.argument_count == 0:
                return ()
            return tuple(parts)
    return ()


def _parameter_type(clause: str) -> str:
    text = _split_top_level(clause, "=")[0].strip()
    text = re.sub(r"^\s*typename\s+", "", text)
    # Drop trailing name / array declarator while keeping pointer/ref in kind.
    text = re.sub(r"(\[\s*[^\]]*\s*\])+\s*$", "", text).strip()
    text = re.sub(r"(\.\.\.)?\s*([A-Za-z_]\w*)\s*$", lambda match: match.group(1) or "", text)
    return normalize_declared_type(text)


def _parameter_kind(clause: str) -> str:
    head = _split_top_level(clause, "=")[0]
    if "&&" in head:
        return "rvalue_reference"
    if re.search(r"\bconst\b", head) and "&" in head:
        return "const_reference"
    if "&" in head:
        return "reference"
    if "*" in head:
        return "pointer"
    return "value"


def _return_type_from_declarator(declarator: str, name: str, owner: str) -> str:
    open_paren = _function_parameter_open(declarator, name)
    if open_paren < 0:
        return ""
    name_start = declarator.rfind(name, 0, open_paren)
    if name_start < 0:
        return ""
    if canonical_base(owner) == name:
        return ""
    prefix = declarator[:name_start]
    prefix = re.split(r"[;}]", prefix)[-1]
    prefix = re.sub(r"template\s*<.*?>\s*", " ", prefix, flags=re.DOTALL)
    prefix = re.sub(r"(?:[A-Za-z_]\w*(?:\s*<[^;{}]*>)?\s*::\s*)+$", "", prefix).strip()
    tokens = [
        token
        for token in re.split(r"\s+", prefix)
        if token
        and token
        not in {
            "const", "volatile", "static", "inline", "constexpr", "consteval",
            "__aicore__", "__host__", "__device__", "__global__", "__forceinline__",
            "virtual", "explicit", "friend", "typename", "struct", "class",
        }
        and not token.startswith("__attribute__")
    ]
    if not tokens:
        return ""
    return normalize_declared_type(" ".join(tokens))


def _function_parameter_open(text: str, name: str) -> int:
    for match in re.finditer(rf"\b{re.escape(name)}\s*\(", text):
        return text.find("(", match.start())
    return -1


def _substitute_type(type_name: str, bindings: Mapping[str, str]) -> str:
    text = str(type_name or "")
    if not text or not bindings:
        return text
    for name, value in bindings.items():
        text = re.sub(rf"\b{re.escape(name)}\b", value, text)
    return normalize_declared_type(text) or text


def _type_base(type_name: str) -> str:
    return canonical_base(type_name)


def _strip_indirection(type_name: str) -> str:
    return normalize_declared_type(type_name)


def _is_pointer(expression_or_type: str) -> bool:
    text = str(expression_or_type or "").strip()
    return text.endswith("*") or "*" in text[-3:]


def _is_pointer_type(type_clause: str) -> bool:
    return "*" in str(type_clause or "")


def _buffer_manager_conflict(arg_base: str, param_base: str) -> bool:
    if not arg_base or not param_base:
        return False
    if "BufferManager" not in arg_base and "BufferManager" not in param_base:
        return False
    return ("Mutex" in arg_base) != ("Mutex" in param_base)
