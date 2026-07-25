"""Generic C/C++ preprocessor region analysis (no operator-specific names).

Capabilities:
- Collect simple object-like ``#define`` macros
- Walk ``#if / #ifdef / #ifndef / #elif / #else / #endif``
- Evaluate constant / defined() conditions when possible
- Emit active line spans and directive sites for host/kernel extractors
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DIRECTIVE_RE = re.compile(
    r"^\s*#\s*(define|undef|if|ifdef|ifndef|elif|else|endif)\b(.*)$"
)
DEFINE_RE = re.compile(
    r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\b(?:\s+(.*?))?\s*$"
)
FUNCTION_DEFINE_RE = re.compile(
    r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*(.*?)\s*$"
)
UNDEF_RE = re.compile(r"^\s*#\s*undef\s+([A-Za-z_][A-Za-z0-9_]*)\b")
IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
DEFINED_RE = re.compile(r"defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)|defined\s+([A-Za-z_][A-Za-z0-9_]*)")


@dataclass
class MacroDirective:
    line: int
    kind: str  # if|ifdef|ifndef|elif|else|endif|define|undef
    condition: str = ""
    name: str = ""
    value: str | None = None
    eval_result: bool | None = None  # None = unknown
    parameters: tuple[str, ...] = ()
    function_like: bool = False
    variadic: bool = False


@dataclass
class MacroAnalysis:
    defines: dict[str, str | None] = field(default_factory=dict)
    function_macros: dict[str, dict[str, Any]] = field(default_factory=dict)
    directives: list[MacroDirective] = field(default_factory=list)
    # 1-based inclusive active line ranges after constant folding where known
    active_ranges: list[tuple[int, int]] = field(default_factory=list)
    # Lines known-dead because parent condition evaluated False
    inactive_lines: set[int] = field(default_factory=set)

    def is_active_line(self, line: int) -> bool:
        if line in self.inactive_lines:
            return False
        if not self.active_ranges:
            return True
        return any(lo <= line <= hi for lo, hi in self.active_ranges)


def _norm_macro_name(name: str) -> str:
    return "".join(ch for ch in str(name or "") if ch.isalnum()).casefold()


def analyze_macros(
    text: str,
    *,
    seed_defines: dict[str, str | None] | None = None,
    soft_undefined: set[str] | None = None,
) -> MacroAnalysis:
    """Analyze preprocessor structure in ``text``.

    Unknown ``#if`` conditions keep both branches extractable (active), but
    known-false regions (``#if 0``, failed ``#ifdef`` of undefined, etc.) are
    marked inactive so runtime scanners can skip dead code.

    ``soft_undefined``: normalized macro names (e.g. tiling-key symbols) that are
    injected at compile time. ``#ifdef`` of those names is treated as unknown
    (kept active) instead of false, so KEY-gated code is not dropped.
    """
    defines: dict[str, str | None] = dict(seed_defines or {})
    function_macros: dict[str, dict[str, Any]] = {}
    soft = {_norm_macro_name(x) for x in (soft_undefined or set()) if x}
    directives: list[MacroDirective] = []
    lines = text.splitlines()
    n = len(lines)

    # Stack frames: each open conditional group
    # frame = {kind, line, cond, parent_active, branch_taken, cur_active, known}
    stack: list[dict[str, Any]] = []
    inactive: set[int] = set()

    def parent_active() -> bool:
        return all(bool(frame.get("cur_active", True)) for frame in stack) if stack else True

    def mark_line(line_no: int, active: bool) -> None:
        if not active:
            inactive.add(line_no)

    for idx, raw in enumerate(lines):
        line_no = idx + 1
        # Strip line comments for directive match only
        stripped = raw.split("//", 1)[0]
        m = DIRECTIVE_RE.match(stripped)
        if not m:
            mark_line(line_no, parent_active())
            continue

        kind = m.group(1)
        rest = (m.group(2) or "").strip()

        if kind == "define":
            fm = FUNCTION_DEFINE_RE.match(stripped)
            if fm:
                name = fm.group(1)
                raw_params = fm.group(2).strip()
                body = fm.group(3).strip()
                params = tuple(p.strip() for p in raw_params.split(",") if p.strip())
                variadic = any(p == "..." or p.endswith("...") for p in params)
                function_macros[name] = {
                    "name": name,
                    "parameters": list(params),
                    "variadic": variadic,
                    "body": body,
                    "line": line_no,
                }
                directives.append(
                    MacroDirective(
                        line=line_no, kind="define", name=name, value=body,
                        parameters=params, function_like=True, variadic=variadic,
                    )
                )
                mark_line(line_no, parent_active())
                continue
            dm = DEFINE_RE.match(stripped)
            if dm:
                name = dm.group(1)
                value = dm.group(2)
                defines[name] = None if value is None or value == "" else value.strip()
                directives.append(
                    MacroDirective(line=line_no, kind="define", name=name, value=defines[name])
                )
            mark_line(line_no, parent_active())
            continue

        if kind == "undef":
            um = UNDEF_RE.match(stripped)
            name = um.group(1) if um else rest.split()[0] if rest.split() else ""
            if name:
                defines.pop(name, None)
                function_macros.pop(name, None)
            directives.append(MacroDirective(line=line_no, kind="undef", name=name))
            mark_line(line_no, parent_active())
            continue

        if kind in {"if", "ifdef", "ifndef"}:
            cond = rest
            if kind == "ifdef":
                name = rest.split()[0] if rest.split() else ""
                cond = f"defined({name})"
                if name in defines:
                    ev = True
                elif _norm_macro_name(name) in soft:
                    ev = None  # compile-injected (e.g. tiling key)
                else:
                    ev = False
            elif kind == "ifndef":
                name = rest.split()[0] if rest.split() else ""
                cond = f"!defined({name})"
                if name in defines:
                    ev = False
                elif _norm_macro_name(name) in soft:
                    ev = None
                else:
                    ev = True
            else:
                name = ""
                ev = eval_pp_condition(cond, defines)
            pa = parent_active()
            # If parent inactive, child inactive regardless
            if not pa:
                cur = False
                known = True
            elif ev is None:
                # Unknown: keep active for extraction, but don't mark sibling as dead
                cur = True
                known = False
            else:
                cur = bool(ev)
                known = True
            stack.append(
                {
                    "kind": kind,
                    "line": line_no,
                    "cond": cond,
                    "name": name,
                    "parent_active": pa,
                    "branch_taken": cur if known and cur else False,
                    "any_taken": bool(known and cur),
                    "cur_active": cur,
                    "known": known,
                }
            )
            directives.append(
                MacroDirective(
                    line=line_no,
                    kind=kind,
                    condition=cond,
                    name=name,
                    eval_result=ev,
                )
            )
            mark_line(line_no, pa)
            continue

        if kind == "elif":
            if not stack:
                mark_line(line_no, parent_active())
                continue
            frame = stack[-1]
            cond = rest
            ev = eval_pp_condition(cond, defines)
            pa = bool(frame.get("parent_active", True))
            if not pa:
                cur = False
                known = True
            elif frame.get("any_taken"):
                cur = False
                known = True
                ev = False
            elif ev is None:
                cur = True
                known = False
            else:
                cur = bool(ev)
                known = True
                if cur:
                    frame["any_taken"] = True
            frame["cur_active"] = cur
            frame["known"] = known
            frame["cond"] = cond
            directives.append(
                MacroDirective(line=line_no, kind="elif", condition=cond, eval_result=ev)
            )
            mark_line(line_no, pa)
            continue

        if kind == "else":
            if not stack:
                mark_line(line_no, parent_active())
                continue
            frame = stack[-1]
            pa = bool(frame.get("parent_active", True))
            if not pa:
                cur = False
            elif frame.get("any_taken"):
                cur = False
            elif frame.get("known") is False:
                # Opening if unknown → else also kept active (conservative)
                cur = True
            else:
                cur = not frame.get("any_taken", False)
                if cur:
                    frame["any_taken"] = True
            frame["cur_active"] = cur
            directives.append(MacroDirective(line=line_no, kind="else", eval_result=cur if pa else False))
            mark_line(line_no, pa)
            continue

        if kind == "endif":
            if stack:
                stack.pop()
            directives.append(MacroDirective(line=line_no, kind="endif"))
            mark_line(line_no, parent_active())
            continue

        mark_line(line_no, parent_active())

    # Build active ranges from complement of inactive (compact)
    active_ranges: list[tuple[int, int]] = []
    if n == 0:
        return MacroAnalysis(
            defines=defines, function_macros=function_macros, directives=directives,
            active_ranges=[], inactive_lines=inactive,
        )

    i = 1
    while i <= n:
        if i in inactive:
            i += 1
            continue
        lo = i
        while i <= n and i not in inactive:
            i += 1
        active_ranges.append((lo, i - 1))

    return MacroAnalysis(
        defines=defines,
        function_macros=function_macros,
        directives=directives,
        active_ranges=active_ranges,
        inactive_lines=inactive,
    )


def eval_pp_condition(cond: str, defines: dict[str, str | None]) -> bool | None:
    """Evaluate a restricted preprocessor expression. None = unknown."""
    expr = (cond or "").strip()
    if not expr:
        return None

    def _defined_sub(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2) or ""
        return "1" if name in defines else "0"

    expr = DEFINED_RE.sub(_defined_sub, expr)

    # Replace known object-like macros with numeric/bool literals
    for name in sorted(defines.keys(), key=len, reverse=True):
        val = defines[name]
        if val is None or str(val).strip() == "":
            repl = "1"
        else:
            v = str(val).strip()
            if re.fullmatch(r"0[xX][0-9A-Fa-f]+|[0-9]+", v):
                repl = str(int(v, 0))
            elif v in {"true", "TRUE"}:
                repl = "1"
            elif v in {"false", "FALSE"}:
                repl = "0"
            else:
                continue
        expr = re.sub(rf"\b{re.escape(name)}\b", repl, expr)

    if IDENT_RE.search(expr):
        return None

    py = expr.replace("&&", " and ").replace("||", " or ")
    # Unary ! → not (avoid touching !=)
    out_chars: list[str] = []
    i = 0
    while i < len(py):
        if py[i] == "!" and (i + 1 >= len(py) or py[i + 1] != "="):
            out_chars.append(" not ")
            i += 1
            continue
        out_chars.append(py[i])
        i += 1
    py = "".join(out_chars)
    try:
        result = eval(py, {"__builtins__": {}}, {})  # noqa: S307 — restricted pp expr
        return bool(result)
    except Exception:
        return None


def classify_macro_condition(
    cond: str,
    *,
    key_index: dict[str, Any] | None = None,
) -> tuple[str, str, list[Any] | None]:
    """Classify a ``#if`` condition against tiling-key provenance when possible."""
    from uo.scripts.provenance import classify_compile_determinant

    if key_index:
        source, ref, domain = classify_compile_determinant(cond, key_index)
        if source == "TilingKey":
            return source, ref, domain
    # defined(X) → prefer X as ref
    dm = DEFINED_RE.search(cond or "")
    if dm:
        name = dm.group(1) or dm.group(2) or cond
        if key_index:
            source, ref, domain = classify_compile_determinant(name, key_index)
            if source == "TilingKey":
                return source, ref, domain
        return "CompileMacro", name, [0, 1]
    toks = (cond or "").split()
    ref = toks[0] if toks else (cond or "")[:120]
    if key_index:
        source, key_ref, domain = classify_compile_determinant(ref, key_index)
        if source == "TilingKey":
            return source, key_ref, domain
    return "CompileMacro", ref[:120], None


def merge_defines(*maps: dict[str, str | None]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for m in maps:
        out.update(m)
    return out


_INCLUDE_GUARD_RE = re.compile(
    r".+(_H|_H_|_HPP|_HPP_|_HH|_HH_)$|^(?:[A-Z][A-Z0-9_]*_)+H_?$",
    re.IGNORECASE,
)


def is_include_guard_name(name: str) -> bool:
    """Heuristic: bare header-guard macros should not cross-seed other files."""
    n = str(name or "").strip()
    if not n:
        return False
    if _INCLUDE_GUARD_RE.match(n):
        return True
    # Common Ascend/C patterns ending with INTERFACE_H / UTILS_H already covered;
    # also treat ALL_CAPS names that end with _ and look like guards.
    if n.endswith("_") and n.replace("_", "").isalnum() and n.upper() == n:
        return True
    return False


def valued_seed_defines(defines: dict[str, str | None]) -> dict[str, str | None]:
    """Keep only object-like macros with concrete values for cross-file ``#if`` eval.

    Bare ``#define FOO_H`` include guards must not be seeded into other files:
    otherwise ``#ifndef FOO_H`` evaluates false and the whole header body is
    marked inactive (dropping constexpr / runtime branches).
    """
    out: dict[str, str | None] = {}
    for name, value in (defines or {}).items():
        if is_include_guard_name(name):
            continue
        if value is None or str(value).strip() == "":
            continue
        v = str(value).strip()
        if re.fullmatch(r"0[xX][0-9A-Fa-f]+|[0-9]+", v) or v in {
            "true",
            "TRUE",
            "false",
            "FALSE",
        }:
            out[name] = v
    return out
