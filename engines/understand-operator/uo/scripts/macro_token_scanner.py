"""AscendC / C++ 轻量词法扫描器：宏 invocation 参数切分。

状态机覆盖字符串、字符、原始字符串、行/块注释；嵌套深度覆盖 ()[]{}<>。
第一版不做真实预处理 expansion，只产出 invocation 级事实。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScanState:
    mode: str = "normal"  # normal|string_literal|char_literal|raw_string|line_comment|block_comment
    paren: int = 0
    bracket: int = 0
    brace: int = 0
    angle: int = 0
    raw_delim: str = ""


@dataclass
class BalancedSpan:
    open_index: int
    close_index: int  # exclusive index after closing ')'
    inside: str
    args: list[str] = field(default_factory=list)


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_ident_cont(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def find_macro_call_sites(text: str, macro_name: str, *, require_paren: bool = True) -> list[int]:
    """Return start indices of ``MACRO`` / ``MACRO(`` occurrences outside comments/strings."""
    sites: list[int] = []
    i = 0
    n = len(text)
    state = ScanState()
    name_len = len(macro_name)
    while i < n:
        ch = text[i]
        if state.mode == "line_comment":
            if ch == "\n":
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "block_comment":
            if ch == "*" and i + 1 < n and text[i + 1] == "/":
                state.mode = "normal"
                i += 2
            else:
                i += 1
            continue
        if state.mode == "string_literal":
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "char_literal":
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "raw_string":
            end_pat = ")" + state.raw_delim + '"'
            if text.startswith(end_pat, i):
                state.mode = "normal"
                state.raw_delim = ""
                i += len(end_pat)
            else:
                i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                state.mode = "line_comment"
                i += 2
                continue
            if nxt == "*":
                state.mode = "block_comment"
                i += 2
                continue
        if ch == '"':
            if i >= 1 and text[i - 1] == "R":
                j = i + 1
                while j < n and text[j] != "(" and text[j] != '"':
                    j += 1
                if j < n and text[j] == "(":
                    state.raw_delim = text[i + 1 : j]
                    state.mode = "raw_string"
                    i = j + 1
                    continue
            state.mode = "string_literal"
            i += 1
            continue
        if ch == "'":
            state.mode = "char_literal"
            i += 1
            continue

        if text.startswith(macro_name, i) and (
            i == 0 or not _is_ident_cont(text[i - 1])
        ):
            if i + name_len < n and _is_ident_cont(text[i + name_len]):
                i += 1
                continue
            j = i + name_len
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] == "(":
                sites.append(i)
            elif not require_paren:
                sites.append(i)
        i += 1
    return sites


def extract_balanced_paren(text: str, open_paren_idx: int) -> BalancedSpan | None:
    """Extract balanced (...) starting at open_paren_idx, respecting strings/comments/<>."""
    if open_paren_idx < 0 or open_paren_idx >= len(text) or text[open_paren_idx] != "(":
        return None
    state = ScanState(paren=1)
    i = open_paren_idx + 1
    n = len(text)
    while i < n:
        ch = text[i]
        if state.mode == "line_comment":
            if ch == "\n":
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "block_comment":
            if ch == "*" and i + 1 < n and text[i + 1] == "/":
                state.mode = "normal"
                i += 2
            else:
                i += 1
            continue
        if state.mode == "string_literal":
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "char_literal":
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "raw_string":
            end_pat = ")" + state.raw_delim + '"'
            if text.startswith(end_pat, i):
                state.mode = "normal"
                state.raw_delim = ""
                i += len(end_pat)
            else:
                i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                state.mode = "line_comment"
                i += 2
                continue
            if nxt == "*":
                state.mode = "block_comment"
                i += 2
                continue
        if ch == '"':
            if i >= 1 and text[i - 1] == "R":
                j = i + 1
                while j < n and text[j] != "(" and text[j] != '"':
                    j += 1
                if j < n and text[j] == "(":
                    state.raw_delim = text[i + 1 : j]
                    state.mode = "raw_string"
                    i = j + 1
                    continue
            state.mode = "string_literal"
            i += 1
            continue
        if ch == "'":
            state.mode = "char_literal"
            i += 1
            continue

        if ch == "(":
            state.paren += 1
        elif ch == ")":
            state.paren -= 1
            if state.paren == 0:
                inside = text[open_paren_idx + 1 : i]
                return BalancedSpan(
                    open_index=open_paren_idx,
                    close_index=i + 1,
                    inside=inside,
                    args=split_top_level_args(inside),
                )
        elif ch == "[":
            state.bracket += 1
        elif ch == "]":
            state.bracket = max(0, state.bracket - 1)
        elif ch == "{":
            state.brace += 1
        elif ch == "}":
            state.brace = max(0, state.brace - 1)
        elif ch == "<":
            # Heuristic: treat as template depth only when likely angle, not comparison.
            # Always track when nested inside paren args of macros.
            state.angle += 1
        elif ch == ">":
            if state.angle > 0:
                state.angle -= 1
        i += 1
    return None


def split_top_level_args(inside: str) -> list[str]:
    """Split comma-separated args at depth 0 for ()[]{}<>."""
    args: list[str] = []
    buf: list[str] = []
    state = ScanState()
    i = 0
    n = len(inside)
    while i < n:
        ch = inside[i]
        if state.mode == "line_comment":
            buf.append(ch)
            if ch == "\n":
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "block_comment":
            buf.append(ch)
            if ch == "*" and i + 1 < n and inside[i + 1] == "/":
                buf.append("/")
                state.mode = "normal"
                i += 2
            else:
                i += 1
            continue
        if state.mode == "string_literal":
            buf.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    buf.append(inside[i + 1])
                i += 2
                continue
            if ch == '"':
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "char_literal":
            buf.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    buf.append(inside[i + 1])
                i += 2
                continue
            if ch == "'":
                state.mode = "normal"
            i += 1
            continue
        if state.mode == "raw_string":
            buf.append(ch)
            end_pat = ")" + state.raw_delim + '"'
            if inside.startswith(end_pat, i):
                for c in end_pat[1:]:
                    buf.append(c)
                state.mode = "normal"
                state.raw_delim = ""
                i += len(end_pat)
            else:
                i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = inside[i + 1]
            if nxt == "/":
                state.mode = "line_comment"
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            if nxt == "*":
                state.mode = "block_comment"
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
        if ch == '"':
            if i >= 1 and inside[i - 1] == "R":
                j = i + 1
                while j < n and inside[j] != "(" and inside[j] != '"':
                    j += 1
                if j < n and inside[j] == "(":
                    state.raw_delim = inside[i + 1 : j]
                    state.mode = "raw_string"
                    buf.append(ch)
                    for c in inside[i + 1 : j + 1]:
                        buf.append(c)
                    i = j + 1
                    continue
            state.mode = "string_literal"
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            state.mode = "char_literal"
            buf.append(ch)
            i += 1
            continue

        depth = state.paren + state.bracket + state.brace + state.angle
        if ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        if ch == "(":
            state.paren += 1
        elif ch == ")":
            state.paren = max(0, state.paren - 1)
        elif ch == "[":
            state.bracket += 1
        elif ch == "]":
            state.bracket = max(0, state.bracket - 1)
        elif ch == "{":
            state.brace += 1
        elif ch == "}":
            state.brace = max(0, state.brace - 1)
        elif ch == "<":
            state.angle += 1
        elif ch == ">":
            if state.angle > 0:
                state.angle -= 1
        buf.append(ch)
        i += 1
    if buf:
        args.append("".join(buf).strip())
    return [a for a in args if a]


def parse_chained_methods(text: str, start: int) -> list[dict[str, Any]]:
    """Parse ``.Method(...)`` chain after a macro call end index."""
    methods: list[dict[str, Any]] = []
    i = start
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n or text[i] != ".":
            break
        j = i + 1
        if j >= n or not _is_ident_start(text[j]):
            break
        k = j + 1
        while k < n and _is_ident_cont(text[k]):
            k += 1
        name = text[j:k]
        while k < n and text[k].isspace():
            k += 1
        if k >= n or text[k] != "(":
            break
        span = extract_balanced_paren(text, k)
        if not span:
            break
        methods.append(
            {
                "name": name,
                "args": list(span.args),
                "end": span.close_index,
                "start_index": i,
            }
        )
        i = span.close_index
    return methods


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, max(0, index)) + 1


def scan_invocations(
    text: str,
    macro_names: list[str],
) -> list[dict[str, Any]]:
    """Scan function-like macro invocations for the given names (longest first)."""
    names = sorted({n for n in macro_names if n}, key=len, reverse=True)
    found: list[dict[str, Any]] = []
    occupied: set[int] = set()
    # Macros that may appear without argument list
    bare_ok = {"END_TILING_DATA_DEF"}
    for name in names:
        require_paren = name not in bare_ok
        for start in find_macro_call_sites(text, name, require_paren=require_paren):
            if start in occupied:
                continue
            j = start + len(name)
            while j < len(text) and text[j].isspace():
                j += 1
            if j >= len(text) or text[j] != "(":
                if name in bare_ok:
                    inv = {
                        "macro": name,
                        "start_index": start,
                        "end_index": j,
                        "start_line": line_of(text, start),
                        "end_line": line_of(text, start),
                        "raw_args": [],
                        "expansion_status": "invocation_only",
                        "fact_kind": "macro_invocation",
                    }
                    found.append(inv)
                    for pos in range(start, min(j + 1, len(text))):
                        occupied.add(pos)
                continue
            span = extract_balanced_paren(text, j)
            if not span:
                continue
            inv = {
                "macro": name,
                "start_index": start,
                "end_index": span.close_index,
                "start_line": line_of(text, start),
                "end_line": line_of(text, span.close_index - 1),
                "raw_args": list(span.args),
                "expansion_status": "invocation_only",
                "fact_kind": "macro_invocation",
            }
            found.append(inv)
            for pos in range(start, span.close_index):
                occupied.add(pos)
    found.sort(key=lambda x: (x["start_line"], x["macro"]))
    return found
