# -*- coding: utf-8 -*-
"""What the API layer refuses, which is where the input contract is written.

Host tiling assumes it was handed a legal input and says almost nothing about
what that means. The `op_api` layer is where the operator actually states it,
one rejection at a time:

    if (queryRope != nullptr && qDtype != DT_BF16) {
        OP_LOGE(ACLNN_ERR_PARAM_INVALID, "...");
        return false;
    }

Every run that reaches tiling got past all of them, so their negations hold
together on any key worth asking about. Without them the analysis believes a
FLOAT16 query can arrive alongside a rope input and reports keys the kernel
never declared -- which is the shape of the contract disagreements found when
host-derived keys were compared against the kernel's own list.

The conditions are read in the API layer's own vocabulary and then grounded:
each identifier is chased back through the local assignments until it reaches
a parameter the operator declares. A condition that cannot be grounded whole
is kept but marked, never partially translated -- half a condition is not a
weaker premise, it is a different one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uo_init.decl_facts import DeclFacts
from uo_init.host_ir import build_host_ir
from uo_init.op_spec import camel_to_snake

IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")
# `strcmp(layout, "same_as_input")` — the words inside a literal are a value,
# not names, and reading them as identifiers leaves every such check ungrounded.
STRING_RE = re.compile(r'"[^"]*"')
# `static_cast<int64_t>(x)` — the cast and the type it names are syntax. They
# do not end in `(` so the call rule misses them.
CAST_RE = re.compile(r"\b(\w+_cast)\s*<([^>]*)>")
# `GetDimNum(` names the call, not a value. Every check goes through several,
# and reading them as inputs is what made whole conditions look ungrounded.
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
# `op::DataType::DT_BF16` — the qualifiers name a scope, not a value.
QUALIFIER_RE = re.compile(r"\b([A-Za-z_]\w*)\s*::")
# `fagShape.dDim` — what is read is the field. When the base is an input it
# resolves on its own (`query->GetDataType()`); when it is a scratch struct the
# checker filled in, it holds no value of its own and only the field matters.
MEMBER_BASE_RE = re.compile(r"\b([A-Za-z_]\w*)\s*(?:\.|->)")

NOT_A_PARAM = frozenset(
    """
    if else return true false nullptr null void const static inline sizeof
    and or not int long float double bool char unsigned signed auto size_t
    """.split()
)

# Suffixes the API layer adds to a declared name. `attenMaskOptional` is
# `atten_mask`; `dqOut` is the output `dq`. Only tried when the plain name
# misses, so a real parameter ending this way still wins.
NAME_SUFFIXES = ("_optional", "_out", "_tensor", "_input", "_in")


@dataclass
class ApiPremise:
    """One condition every legal input satisfies."""

    text: str
    function: str = ""
    file: str = ""
    line: int = 0
    #: Declared parameters this condition constrains.
    params: list[str] = field(default_factory=list)
    #: Identifiers that reached no declared parameter.
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_grounded(self) -> bool:
        return bool(self.params) and not self.unresolved


@dataclass
class ApiContract:
    """Input legality as the user-facing API states it."""

    premises: list[ApiPremise] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The API layer's own IR. A premise is written in that layer's vocabulary
    #: -- `qDtype`, assigned twenty lines up -- so turning it into something a
    #: solver can read means expanding it there, not against host tiling where
    #: those names do not exist.
    ir: Any = None

    def grounded(self) -> list[ApiPremise]:
        return [p for p in self.premises if p.is_grounded]

    def touching(self, param: str) -> list[ApiPremise]:
        return [p for p in self.premises if param in p.params]

    def to_dict(self) -> dict:
        return {
            "premises": [
                {
                    "text": p.text,
                    "function": p.function,
                    "file": Path(p.file).name if p.file else "",
                    "line": p.line,
                    "params": list(p.params),
                    "unresolved": list(p.unresolved),
                    "grounded": p.is_grounded,
                }
                for p in self.premises
            ],
            "grounded": len(self.grounded()),
            "total": len(self.premises),
            "notes": list(self.notes),
        }


def _looks_declarative(name: str) -> bool:
    """Constants, enum members and macros are spelt in caps here."""
    return name.isupper() or (name.upper() == name and "_" in name)


class _Grounding:
    """Chases an identifier back to the parameter it came from.

    A check rarely names an input directly: it reads `qDtype`, assigned from
    `query->GetDataType()` twenty lines up. The walk already recorded that
    assignment, so following it is a lookup rather than an analysis -- but it
    has to be bounded, because these functions reassign freely and a cycle
    would not terminate.
    """

    def __init__(
        self, facts: DeclFacts, summaries: dict, writes=(), depth: int = 8
    ) -> None:
        self.facts = facts
        self.summaries = summaries
        self.depth = depth
        self._declared = {p.name.lower(): p.name for p in facts.params}
        self._squashed = {k.replace("_", ""): v for k, v in self._declared.items()}
        # `fagShape.dDim` is a field of a struct the checker fills in from the
        # query shape. The name in the condition is the field, so the write is
        # indexed under both, and under the field alone because the struct is
        # filled in one function and tested in another.
        self._written: dict[tuple[str, str], list[str]] = {}
        self._written_anywhere: dict[str, list[str]] = {}
        for w in writes:
            rhs = getattr(w, "rhs", "") or ""
            path = getattr(w, "path", "") or ""
            if not rhs or not path:
                continue
            where = getattr(w, "function", "") or ""
            leaf = path.rsplit(".", 1)[-1]
            for key in {(where, path), (where, leaf)}:
                self._written.setdefault(key, []).append(rhs)
            self._written_anywhere.setdefault(leaf, []).append(rhs)

    def _as_param(self, ident: str) -> str | None:
        """The declared parameter an API-side name refers to, if any.

        Three spellings of the same thing have to meet: `queryRope` against
        `query_rope` is a case convention, `sinkInOptional` against `sink` is
        the suffixes the API adds, and `actualSeqQLen` against
        `actual_seq_qlen` is the two sides disagreeing on where the word breaks
        are. The last is why the final attempt drops the separators entirely.
        """
        snake = camel_to_snake(ident).lower()
        hit = self._declared.get(snake)
        if hit:
            return hit

        trimmed = snake
        while True:
            for suffix in NAME_SUFFIXES:
                if trimmed.endswith(suffix) and len(trimmed) > len(suffix):
                    trimmed = trimmed[: -len(suffix)]
                    break
            else:
                break
            hit = self._declared.get(trimmed)
            if hit:
                return hit

        for candidate in (snake, trimmed):
            hit = self._squashed.get(candidate.replace("_", ""))
            if hit:
                return hit
        return None

    def _actuals_for(self, function: str, formal: str) -> list[tuple[str, str]]:
        """What every caller passes for this formal, with the caller's name.

        A checker takes `inputLayoutStr` and knows nothing about where it came
        from; the callers do. All of them are followed, not one: each call
        happens, so each argument is equally constrained by the check.
        """
        summary = self.summaries.get(function)
        params = list(getattr(summary, "params", ()) or ())
        if formal not in params:
            return []
        pos = params.index(formal)
        out: list[tuple[str, str]] = []
        for caller, s in self.summaries.items():
            for callee, actuals in getattr(s, "calls", ()) or ():
                if callee == function and pos < len(actuals) and actuals[pos]:
                    out.append((caller, actuals[pos]))
        return out

    def resolve(self, text: str, function: str) -> tuple[list[str], list[str]]:
        found: list[str] = []
        missing: list[str] = []
        seen: set[tuple[str, str]] = set()
        # Collected over the whole walk rather than per expression: the same
        # struct is passed around bare before it is read a field at a time, and
        # whichever spelling is met first should not decide what it is.
        containers: set[str] = set()

        def walk(expr: str, where: str, budget: int) -> None:
            syntax = set(CALL_RE.findall(expr)) | set(QUALIFIER_RE.findall(expr))
            for cast, typed in CAST_RE.findall(expr):
                syntax.add(cast)
                syntax.update(IDENT_RE.findall(typed))
            containers.update(MEMBER_BASE_RE.findall(expr))
            locals_of = getattr(self.summaries.get(where), "locals", {}) or {}
            for ident in IDENT_RE.findall(STRING_RE.sub(" ", expr)):
                if ident in NOT_A_PARAM or ident in syntax:
                    continue
                if _looks_declarative(ident) or (where, ident) in seen:
                    continue
                seen.add((where, ident))
                param = self._as_param(ident)
                if param is not None:
                    if param not in found:
                        found.append(param)
                    continue
                if budget <= 0:
                    if ident not in missing:
                        missing.append(ident)
                    continue
                definition = locals_of.get(ident)
                if definition:
                    walk(definition, where, budget - 1)
                    continue
                assigned = self._written.get((where, ident)) or []
                if assigned:
                    for rhs in assigned:
                        walk(rhs, where, budget - 1)
                    continue
                actuals = self._actuals_for(where, ident)
                if actuals:
                    for caller, passed in actuals:
                        walk(passed, caller, budget - 1)
                    continue
                elsewhere = self._written_anywhere.get(ident) or []
                if elsewhere:
                    for rhs in elsewhere:
                        walk(rhs, where, budget - 1)
                    continue
                if ident not in missing:
                    missing.append(ident)

        walk(text, function, self.depth)
        return found, [m for m in missing if m not in containers]


def extract_api_contract(spec, ctx, facts: DeclFacts) -> ApiContract:
    """Read the API layer's refusals as premises about the operator's inputs."""
    contract = ApiContract()
    targets = [p for p in getattr(spec, "api_targets", ()) if Path(p).is_file()]
    if not targets:
        contract.notes.append("no_api_targets")
        return contract
    if not facts.params:
        contract.notes.append("no_declared_parameters: cannot ground any condition")

    ir = build_host_ir(
        list(targets),
        ctx=ctx,
        op_needle=getattr(spec, "op_needle", ""),
        scope=getattr(spec, "scope", None),
        logs_rejections=True,
    )
    contract.ir = ir
    ground = _Grounding(
        facts, ir.summaries, writes=(*ir.writes, *ir.local_writes)
    )
    for text, function, file, line in ir.legality_premises():
        params, unresolved = ground.resolve(text, function)
        contract.premises.append(
            ApiPremise(
                text=text,
                function=function,
                file=file,
                line=line,
                params=params,
                unresolved=unresolved,
            )
        )
    contract.notes.append(
        f"api_tus={len(targets)} premises={len(contract.premises)} "
        f"grounded={len(contract.grounded())}"
    )
    return contract
