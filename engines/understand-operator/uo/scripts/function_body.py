"""Brace-bounded C/C++ function body resolution (generic, no op names)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo.scripts.source_path import resolve_repo_source_path, to_repo_relative

# Match a definition opening that ends with `{` on the same logical header span.
_DEF_OPEN_RE_TMPL = (
    r"^([^\n]*\b{name}\s*\([^;{{]*\)\s*(?:const\s*|override\s*|final\s*)*\{{)"
)


def find_function_body(
    repo_root: Path,
    file_path: str,
    name: str,
    *,
    hint_line: int = 0,
) -> tuple[int, int, str, str] | None:
    """Locate ``name`` definition; return (start_line, end_line, body, resolved_rel_path)."""
    if not name:
        return None
    path = resolve_repo_source_path(repo_root, file_path)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    pattern = re.compile(_DEF_OPEN_RE_TMPL.format(name=re.escape(name)), re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return None

    chosen = matches[0]
    if hint_line > 0 and len(matches) > 1:
        best = None
        best_dist = 10**9
        for m in matches:
            line = text.count("\n", 0, m.start()) + 1
            dist = abs(line - hint_line)
            if dist < best_dist:
                best_dist = dist
                best = m
        if best is not None:
            chosen = best

    brace_pos = text.find("{", chosen.start())
    if brace_pos < 0:
        return None
    end_pos = _matching_brace_end(text, brace_pos)
    if end_pos is None:
        return None

    def_start = text.count("\n", 0, chosen.start()) + 1
    def_end = text.count("\n", 0, end_pos) + 1
    lines = text.splitlines()
    body = "\n".join(lines[def_start - 1 : def_end])
    rel = to_repo_relative(repo_root, path)
    return def_start, def_end, body, rel


def resolve_helper_body(
    repo_root: Path,
    item: dict[str, Any],
    *,
    prefer_definition: bool = True,
    max_fallback_lines: int = 120,
) -> tuple[str, int, int]:
    """Return brace-bounded definition body when possible; else a small safe window.

    Never uses a large fixed expand (400/500) that can swallow the next function.
    When a definition is found, updates ``item['file_path']`` to the resolved
    repo-relative path so downstream IR keeps a readable path.
    """
    file_path = str(item.get("file_path") or "")
    start = int(item.get("start_line") or 0)
    end = int(item.get("end_line") or start)
    name = str(item.get("name") or "")

    if prefer_definition and name:
        resolved = find_function_body(repo_root, file_path, name, hint_line=start)
        if resolved is not None:
            def_start, def_end, body, rel = resolved
            item["file_path"] = rel
            return body, def_start, def_end

    path = resolve_repo_source_path(repo_root, file_path)
    if path is None:
        return "", start, start
    item["file_path"] = to_repo_relative(repo_root, path)
    safe_end = max(end, start)
    if safe_end <= start:
        safe_end = start + max_fallback_lines
    else:
        safe_end = min(safe_end, start + max_fallback_lines)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return "", start, start
    lo = max(0, start - 1)
    hi = min(len(lines), max(safe_end, start))
    body = "\n".join(lines[lo:hi])
    return body, start, safe_end


def extract_callee_names(body: str, *, noise: set[str] | frozenset[str]) -> list[str]:
    """PascalCase / CamelCase call sites inside a body (structural, not a name whitelist)."""
    found: list[str] = []
    seen: set[str] = set()
    for name in re.findall(r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", body):
        if name in noise or name in seen:
            continue
        seen.add(name)
        found.append(name)
    return found


_CONTROL_NAMES = frozenset({"if", "for", "while", "switch", "catch", "else", "try"})
_DEF_ANY_RE = re.compile(
    r"^([^\n]*\b([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{]*\)\s*(?:const\s*|override\s*|final\s*)*\{)",
    re.MULTILINE,
)


def iter_function_defs(
    repo_root: Path,
    file_path: str,
) -> list[tuple[str, int, int, str, str]]:
    """Yield (name, start_line, end_line, body, resolved_rel) for defs in a file.

    Skips control-flow ``if/for/while`` matches. Used for sink-closure discovery.
    """
    path = resolve_repo_source_path(repo_root, file_path)
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    rel = to_repo_relative(repo_root, path)
    lines = text.splitlines()
    out: list[tuple[str, int, int, str, str]] = []
    for match in _DEF_ANY_RE.finditer(text):
        name = match.group(2)
        if name.casefold() in _CONTROL_NAMES:
            continue
        brace_pos = text.find("{", match.start())
        if brace_pos < 0:
            continue
        end_pos = _matching_brace_end(text, brace_pos)
        if end_pos is None:
            continue
        def_start = text.count("\n", 0, match.start()) + 1
        def_end = text.count("\n", 0, end_pos) + 1
        body = "\n".join(lines[def_start - 1 : def_end])
        out.append((name, def_start, def_end, body, rel))
    return out


def _matching_brace_end(text: str, open_pos: int) -> int | None:
    """Return index of matching `}` for `{` at open_pos, skipping strings/comments roughly."""
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
        return None
    depth = 0
    i = open_pos
    n = len(text)
    in_line_comment = False
    in_block_comment = False
    in_string: str | None = None
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ('"', "'"):
            in_string = ch
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None
