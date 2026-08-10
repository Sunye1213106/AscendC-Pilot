# -*- coding: utf-8 -*-
"""Cut the block of source a line sits in, to show rather than quote.

A gap is a question about a piece of code, and three lines around the guard is
not that piece. Where the answer is "what does this loop compute", the loop is
the evidence and anything less asks the reader to guess it. So the window is
taken by matching braces: the innermost block containing the line, widened to
the whole function while that still fits.

Braces are counted, not parsed. A parser would need the include graph and the
macro definitions to get an answer this does not depend on — what is wanted is
a readable extent, and mis-cutting one by a few lines costs nothing. What does
have to be right is not counting braces inside comments and string literals,
which is what `_code_only` is for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["blocks_at", "evidence_window", "read_lines"]

#: Past this a "window" stops being evidence and becomes a file dump.
DEFAULT_MAX_LINES = 400

#: How far to look above an opening brace for the signature that goes with it.
_SIGNATURE_LOOKBACK = 6


def read_lines(path: Path | str) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()


def _code_only(line: str, in_comment: bool) -> tuple[str, bool]:
    """The line with comments and literals blanked, and the comment state after.

    Blanked rather than removed so that column positions survive, which keeps
    this usable for anything that wants to point inside the line later.
    """
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_comment:
            if ch == "*" and i + 1 < n and line[i + 1] == "/":
                in_comment = False
                out.append("  ")
                i += 2
                continue
            out.append(" ")
            i += 1
            continue
        if ch == "/" and i + 1 < n and line[i + 1] == "/":
            out.append(" " * (n - i))
            break
        if ch == "/" and i + 1 < n and line[i + 1] == "*":
            in_comment = True
            out.append("  ")
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(" ")
            i += 1
            while i < n:
                if line[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                if line[i] == quote:
                    break
                out.append(" ")
                i += 1
            if i < n:
                out.append(" ")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_comment


def blocks_at(lines: list[str], line: int) -> list[tuple[int, int]]:
    """Brace blocks containing `line`, outermost first. Lines are 1-based.

    A block whose closing brace is missing — the file was cut short, or the
    braces do not balance because of a macro — is left out rather than run to
    the end of the file.
    """
    if line <= 0 or line > len(lines):
        return []
    stack: list[int] = []
    spans: list[tuple[int, int]] = []
    in_comment = False
    for no, raw in enumerate(lines, start=1):
        code, in_comment = _code_only(raw, in_comment)
        for ch in code:
            if ch == "{":
                stack.append(no)
            elif ch == "}" and stack:
                start = stack.pop()
                if start <= line <= no:
                    spans.append((start, no))
    # Popping produces innermost first; the caller reads outermost first.
    return sorted(spans, key=lambda s: (s[0], -s[1]))


def _with_signature(lines: list[str], start: int) -> int:
    """Walk up from an opening brace to the declaration it belongs to."""
    first = start
    for no in range(start - 1, max(0, start - _SIGNATURE_LOOKBACK) - 1, -1):
        text = lines[no - 1].strip()
        if not text or text.endswith((";", "}", "{")) or text.startswith(("//", "/*")):
            break
        first = no
    return first


def evidence_window(
    path: Path | str,
    line: int,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    context: int = 12,
) -> dict[str, Any] | None:
    """The most informative extent around `line` that is still worth reading.

    Prefers the whole function, because a loop reads differently once you can
    see what was set before it. Falls back inward when the function is too
    large to be evidence, and to a plain window when the braces say nothing.
    """
    lines = read_lines(path)
    if not lines or line <= 0 or line > len(lines):
        return None
    spans = blocks_at(lines, line)
    chosen: tuple[int, int] | None = None
    kind = "window"
    if spans:
        outer = spans[0]
        first = _with_signature(lines, outer[0])
        if outer[1] - first + 1 <= max_lines:
            chosen = (first, outer[1])
            kind = "function"
        else:
            # The largest block that fits, not the smallest. Asked what a loop
            # computes, the innermost block is the `if` inside it -- four lines
            # that show a test and none of the accumulation, which reads as
            # "the loop body was not provided".
            for span in spans:
                if span[1] - span[0] + 1 <= max_lines:
                    chosen = span
                    kind = "block"
                    break
    if chosen is None:
        chosen = (max(1, line - context), min(len(lines), line + context))
        kind = "window"
    start, end = chosen
    return {
        "file": str(path).replace("\\", "/"),
        "line": int(line),
        "line_start": start,
        "line_end": end,
        "kind": kind,
        "text": "\n".join(lines[start - 1 : end]),
    }
