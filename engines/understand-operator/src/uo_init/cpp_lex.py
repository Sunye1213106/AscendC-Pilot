# -*- coding: utf-8 -*-
"""Linear C++ lex helpers. Avoid DOTALL ``.*?`` scans on multi-MB kernel TUs."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

_FUNC_BODY_START_RE = re.compile(
    r"\)\s*(?:const\s*)?(?:noexcept(?:\s*\([^;{}()]*\))?\s*)?(?:override\s*)?\{"
)
_FUNC_NAME_TAIL_RE = re.compile(
    r"(?P<name>(?:[A-Za-z_]\w*(?:\s*<[^;{}()]{0,200}>)?\s*::\s*)*[A-Za-z_~]\w*)\s*$"
)
_CONTROL = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "catch",
        "return",
        "sizeof",
        "alignof",
        "decltype",
    }
)


@dataclass(frozen=True)
class FuncHit:
    start: int
    open_brace: int
    close_brace: int
    name: str
    params: str
    open_paren: int


def line_index(text: str) -> list[int]:
    return [i for i, ch in enumerate(text) if ch == "\n"]


def line_at(newlines: list[int], offset: int) -> int:
    return bisect.bisect_right(newlines, max(0, offset)) + 1


def mask_non_code(text: str) -> str:
    out = list(text)
    i = 0
    n = len(text)
    state = "code"
    quote = ""
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "line"
                continue
            if ch == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                i += 2
                state = "block"
                continue
            if ch in {'"', "'"}:
                quote = ch
                out[i] = " "
                i += 1
                state = "string"
                continue
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = "code"
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "code"
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out[i] = " "
            if text[i + 1] != "\n":
                out[i + 1] = " "
            i += 2
            continue
        if ch == quote:
            out[i] = " "
            i += 1
            state = "code"
        else:
            if ch != "\n":
                out[i] = " "
            i += 1
    return "".join(out)


def matching_brace(text: str, open_pos: int) -> int:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
        return -1
    depth = 0
    quote = ""
    escape = False
    for i in range(open_pos, len(text)):
        ch = text[i]
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
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _matching_paren(text: str, close_pos: int) -> int:
    if close_pos < 0:
        return -1
    depth = 0
    quote = ""
    escape = False
    i = close_pos
    while i >= 0:
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            i -= 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            i -= 1
            continue
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return -1


def iter_function_defs(masked: str) -> list[FuncHit]:
    """Linear ``name(params) ... {`` definitions. Skips if/for/while/switch."""
    out: list[FuncHit] = []
    accepted_end = -1
    for body in _FUNC_BODY_START_RE.finditer(masked):
        close_paren = body.start()
        open_paren = _matching_paren(masked, close_paren)
        if open_paren < 0:
            continue
        window_lo = max(0, open_paren - 400)
        prefix = masked[window_lo:open_paren]
        name_match = _FUNC_NAME_TAIL_RE.search(prefix)
        if name_match is None:
            continue
        name = name_match.group("name")
        short = name.split("::")[-1].split("<", 1)[0].strip()
        if short in _CONTROL or not short:
            continue
        start = window_lo + name_match.start("name")
        if start <= accepted_end:
            continue
        params = masked[open_paren + 1 : close_paren]
        if "{" in params or "}" in params:
            continue
        open_brace = body.end() - 1
        close_brace = matching_brace(masked, open_brace)
        if close_brace < 0:
            continue
        accepted_end = close_brace
        out.append(
            FuncHit(
                start=start,
                open_brace=open_brace,
                close_brace=close_brace,
                name=name,
                params=params,
                open_paren=open_paren,
            )
        )
    return out


def containing_function(hits: list[FuncHit], offset: int) -> str:
    """Innermost function name covering ``offset``, or empty."""
    best = ""
    best_span = 10**18
    for hit in hits:
        if hit.open_brace <= offset <= hit.close_brace:
            span = hit.close_brace - hit.open_brace
            if span < best_span:
                best_span = span
                best = hit.name
    return best
