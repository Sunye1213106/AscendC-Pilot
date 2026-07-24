"""Brace-bounded C/C++ function body resolution (generic, no op names).

Produces structured ``FunctionDefinition`` records with template-aware identity.
CBM/AST may be preferred when available; brace-bounded parsing is the always-on
fallback and must not invent unique resolution under ambiguity.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from uo.scripts.semantic_identity import (
    infer_specialization_kind,
    make_locator,
    mint_method_identity,
    mint_symbol_identity,
    normalize_cxx_signature,
    parse_template_arity,
    snippet_hash,
    source_file_hash,
)
from uo.scripts.source_path import resolve_repo_source_path, to_repo_relative

# Match a definition opening that ends with `{` on the same logical header span.
_DEF_OPEN_RE_TMPL = (
    r"^([^\n]*\b{name}\s*\([^;{{]*\)\s*(?:const\s*|override\s*|final\s*)*\{{)"
)

_CONTROL_NAMES = frozenset({"if", "for", "while", "switch", "catch", "else", "try"})
_DEF_ANY_RE = re.compile(
    r"^([^\n]*\b([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{]*\)\s*(?:const\s*|override\s*|final\s*)*\{)",
    re.MULTILINE,
)
_OUT_OF_CLASS_RE = re.compile(
    r"^([^\n]*\b([A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*)\s*::\s*"
    r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*|override\s*|final\s*)*\{)",
    re.MULTILINE,
)
_CLASS_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)\b")
# Candidate: optional Qual:: then Name(
_FN_CANDIDATE_RE = re.compile(
    r"(?:(?P<qual>[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*)\s*::\s*)?"
    r"(?P<name>[A-Za-z_]\w*)\s*\(",
)
_POST_PARAM_RE = re.compile(
    r"\s*(?:const\s*|override\s*|final\s*|noexcept\s*(?:\([^)]*\))?\s*)*\{"
)
_CALL_RE = re.compile(
    r"(?:"
    r"(?P<recv>(?:this\s*->|[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*\s*\.\s*|"
    r"[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*\s*->\s*))?"
    r"(?P<callee>(?:[A-Za-z_]\w*(?:\s*::\s*)?)+)"
    r"(?P<targs>\s*<[^>;{]{0,120}>)?"
    r"\s*\("
    r")",
)


@dataclass
class FunctionDefinition:
    name: str
    qualified_name: str
    class_or_namespace: str
    normalized_signature: str
    template_arity_or_signature: str
    specialization_kind: str
    file_path: str
    start_line: int
    end_line: int
    header_text: str
    body_text: str
    source_hash: str
    snippet_hash: str
    identity_key: str
    stable_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_legacy_tuple(self) -> tuple[int, int, str, str]:
        return self.start_line, self.end_line, self.body_text, self.file_path


@dataclass
class CallSite:
    caller_function_id: str
    callee_name: str
    callee_qualified_hint: str
    call_expression: str
    file_path: str
    line: int
    receiver_type_or_object: str
    template_args: str
    argument_count: int
    ordinal_in_function: int
    snippet_hash: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _def_matches_for_name(text: str, name: str) -> list[re.Match[str]]:
    if not name:
        return []
    pattern = re.compile(_DEF_OPEN_RE_TMPL.format(name=re.escape(name)), re.MULTILINE)
    return list(pattern.finditer(text))


def _match_line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _preceding_text(text: str, pos: int, *, max_chars: int = 2048) -> str:
    return text[max(0, pos - max_chars) : pos]


def _owns_class(preceding: str, owning_class: str) -> bool:
    if not owning_class:
        return False
    return bool(
        re.search(
            rf"\b(?:class|struct)\s+{re.escape(owning_class)}\b",
            preceding,
        )
    )


def _extract_signature(header: str, name: str) -> str:
    """Normalize the parenthesized parameter list from a header line."""
    idx = header.find(name)
    if idx < 0:
        return normalize_cxx_signature(header)
    paren = header.find("(", idx)
    if paren < 0:
        return ""
    depth = 0
    for i in range(paren, len(header)):
        ch = header[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return normalize_cxx_signature(header[paren : i + 1])
    return normalize_cxx_signature(header[paren:])


def _infer_class_from_context(text: str, match_start: int, header: str) -> str:
    # Out-of-class: Class::Method(
    m = re.search(
        r"\b([A-Za-z_]\w*(?:\s*<[^>]*>)?)\s*::\s*([A-Za-z_]\w*)\s*\(",
        header,
    )
    if m:
        return re.sub(r"\s*<.*?>", "", m.group(1)).strip()
    preceding = _preceding_text(text, match_start, max_chars=4000)
    matches = _CLASS_RE.findall(preceding)
    return matches[-1] if matches else ""


def _find_param_list_end(text: str, open_paren: int) -> int | None:
    if open_paren < 0 or open_paren >= len(text) or text[open_paren] != "(":
        return None
    depth = 0
    i = open_paren
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        elif ch in "'\"":
            quote = ch
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
        i += 1
    return None


def _definition_span_at(text: str, name_match: re.Match[str]) -> tuple[int, int, str] | None:
    """If candidate is a brace-bounded definition, return (start, end_brace, name)."""
    name = name_match.group("name")
    if not name or name.casefold() in _CONTROL_NAMES:
        return None
    open_paren = text.find("(", name_match.start(name_match.lastindex or 0))
    # Prefer the '(' immediately after the name match end-1
    open_paren = name_match.end() - 1
    if open_paren < 0 or open_paren >= len(text) or text[open_paren] != "(":
        open_paren = text.find("(", name_match.start())
    close_paren = _find_param_list_end(text, open_paren)
    if close_paren is None:
        return None
    post = _POST_PARAM_RE.match(text, close_paren + 1)
    if not post:
        return None
    brace_pos = post.end() - 1
    if text[brace_pos] != "{":
        return None
    end_pos = _matching_brace_end(text, brace_pos)
    if end_pos is None:
        return None
    return name_match.start(), end_pos, name


def _build_function_definition_from_span(
    *,
    name: str,
    text: str,
    start_pos: int,
    end_pos: int,
    rel: str,
    source_hash: str,
    architecture: str = "",
    qual_hint: str = "",
) -> FunctionDefinition | None:
    def_start = _match_line(text, start_pos)
    def_end = _match_line(text, end_pos)
    lines = text.splitlines()
    header = lines[def_start - 1] if 0 < def_start <= len(lines) else text[start_pos : text.find("{", start_pos)]
    body = "\n".join(lines[def_start - 1 : def_end])
    preceding = _preceding_text(text, start_pos)
    if qual_hint:
        cls = re.sub(r"\s+", "", qual_hint).split("::")[-1]
        cls = re.sub(r"<.*?>", "", cls)
    else:
        cls = _infer_class_from_context(text, start_pos, header)
    sig = _extract_signature(header, name)
    tpl = parse_template_arity(preceding[-400:] + " " + header)
    sk = infer_specialization_kind(preceding[-500:] + header)
    qn = f"{cls}::{name}" if cls else f"{rel}::{name}"
    if cls:
        ident = mint_method_identity(
            name=name,
            file_path=rel,
            class_or_namespace=cls,
            qualified_name=qn,
            signature=sig,
            template_arity_or_signature=tpl,
            specialization_kind=sk,
            architecture=architecture,
        )
    else:
        ident = mint_symbol_identity(
            kind="helper",
            name=name,
            file_path=rel,
            qualified_name=qn,
            signature=sig,
            template_arity_or_signature=tpl,
            specialization_kind=sk,
            architecture=architecture,
        )
    return FunctionDefinition(
        name=name,
        qualified_name=ident.qualified_name,
        class_or_namespace=ident.class_or_namespace,
        normalized_signature=ident.normalized_signature,
        template_arity_or_signature=ident.template_arity_or_signature,
        specialization_kind=ident.specialization_kind,
        file_path=rel,
        start_line=def_start,
        end_line=def_end,
        header_text=header.strip(),
        body_text=body,
        source_hash=source_hash,
        snippet_hash=snippet_hash(body),
        identity_key=ident.identity_key,
        stable_id=ident.stable_id,
    )


def iter_function_definitions(
    repo_root: Path,
    file_path: str,
    *,
    architecture: str = "",
) -> list[FunctionDefinition]:
    """Return all brace-bounded FunctionDefinitions in a file (overloads preserved)."""
    path = resolve_repo_source_path(repo_root, file_path)
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    rel = to_repo_relative(repo_root, path)
    src_hash = source_file_hash(path)
    out: list[FunctionDefinition] = []
    seen_spans: set[tuple[int, int, str]] = set()

    for match in _FN_CANDIDATE_RE.finditer(text):
        span = _definition_span_at(text, match)
        if span is None:
            continue
        start_pos, end_pos, name = span
        start_line = _match_line(text, start_pos)
        # Skip nested defs inside an already-captured outer function body.
        if any(fn.start_line < start_line < fn.end_line for fn in out):
            continue
        fn = _build_function_definition_from_span(
            name=name,
            text=text,
            start_pos=start_pos,
            end_pos=end_pos,
            rel=rel,
            source_hash=src_hash,
            architecture=architecture,
            qual_hint=(match.group("qual") or ""),
        )
        if fn is None:
            continue
        key = (fn.start_line, fn.end_line, fn.stable_id)
        if key in seen_spans:
            continue
        seen_spans.add(key)
        out.append(fn)
    out.sort(key=lambda f: (f.start_line, f.qualified_name))
    return out


def resolve_function_candidates(
    repo_root: Path,
    file_path: str,
    name: str,
    *,
    hint_line: int = 0,
    owning_class: str = "",
    signature: str = "",
    architecture: str = "",
) -> list[FunctionDefinition]:
    """All matching FunctionDefinitions; never silently picks one."""
    defs = iter_function_definitions(repo_root, file_path, architecture=architecture)
    filtered = [d for d in defs if d.name == name]
    if owning_class:
        scoped = [d for d in filtered if d.class_or_namespace == owning_class]
        if scoped:
            filtered = scoped
    if signature:
        sig = normalize_cxx_signature(signature)
        sig_hit = [d for d in filtered if d.normalized_signature == sig]
        if sig_hit:
            filtered = sig_hit
    if hint_line > 0 and filtered:
        # Sort by distance; caller must not treat [0] as unique unless len==1
        # and distance==0 for verified unique resolution.
        filtered = sorted(filtered, key=lambda d: abs(d.start_line - hint_line))
    return filtered


def resolve_function_definition(
    repo_root: Path,
    file_path: str,
    name: str,
    *,
    hint_line: int = 0,
    owning_class: str = "",
    signature: str = "",
    architecture: str = "",
) -> dict[str, Any]:
    """Resolve uniquely or return candidates/unresolved (fail-closed)."""
    candidates = resolve_function_candidates(
        repo_root,
        file_path,
        name,
        hint_line=hint_line,
        owning_class=owning_class,
        signature=signature,
        architecture=architecture,
    )
    if not candidates:
        return {
            "ok": False,
            "status": "missing",
            "error": "FUNCTION_DEFINITION_NOT_FOUND",
            "name": name,
            "file_path": file_path,
            "candidates": [],
        }
    if len(candidates) == 1:
        only = candidates[0]
        if hint_line > 0 and abs(only.start_line - hint_line) > 0 and not owning_class and not signature:
            # hint alone cannot unique-resolve when distance is nonzero with siblings
            # (already unique in list). Accept unique name+file (+optional class).
            pass
        return {"ok": True, "status": "resolved", "function": only, "candidates": [only]}
    # Multiple: only unique if exact hint_line match and no other at same line
    if hint_line > 0:
        exact = [c for c in candidates if c.start_line == hint_line]
        if len(exact) == 1:
            return {"ok": True, "status": "resolved", "function": exact[0], "candidates": exact}
    return {
        "ok": False,
        "status": "ambiguous",
        "error": "FUNCTION_DEFINITION_AMBIGUOUS",
        "name": name,
        "file_path": file_path,
        "candidates": candidates,
        "unresolved": {
            "kind": "function_definition_ambiguous",
            "name": name,
            "file_path": file_path,
            "candidate_ids": [c.stable_id for c in candidates],
            "candidate_qns": [c.qualified_name for c in candidates],
        },
    }


def find_function_bodies(
    repo_root: Path,
    file_path: str,
    name: str,
    *,
    hint_line: int = 0,
    owning_class: str = "",
) -> list[tuple[int, int, str, str]]:
    """Return all brace-bounded definitions for ``name`` (diagnostics / disambiguation)."""
    cands = resolve_function_candidates(
        repo_root,
        file_path,
        name,
        hint_line=hint_line,
        owning_class=owning_class,
    )
    return [c.as_legacy_tuple() for c in cands]


def find_function_body(
    repo_root: Path,
    file_path: str,
    name: str,
    *,
    hint_line: int = 0,
    owning_class: str = "",
) -> tuple[int, int, str, str] | None:
    """Locate ``name`` definition; return (start_line, end_line, body, resolved_rel_path).

    Fail-closed: returns None when ambiguous (hint_line may only unique-resolve
    on exact line match).
    """
    resolved = resolve_function_definition(
        repo_root,
        file_path,
        name,
        hint_line=hint_line,
        owning_class=owning_class,
    )
    if not resolved.get("ok"):
        return None
    fn: FunctionDefinition = resolved["function"]
    return fn.as_legacy_tuple()


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
    owning = str(
        item.get("class_or_namespace")
        or item.get("owning_class")
        or ""
    ).strip()

    if prefer_definition and name:
        resolved = find_function_body(
            repo_root,
            file_path,
            name,
            hint_line=start,
            owning_class=owning,
        )
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
    """PascalCase / CamelCase call sites inside a body (structural fallback)."""
    found: list[str] = []
    seen: set[str] = set()
    for name in re.findall(r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", body):
        if name in noise or name in seen:
            continue
        seen.add(name)
        found.append(name)
    return found


def extract_call_sites(
    fn: FunctionDefinition,
    *,
    noise: set[str] | frozenset[str] | None = None,
) -> list[CallSite]:
    """Extract call sites from a FunctionDefinition body (relative ordinal)."""
    noise = noise or _CONTROL_NAMES | {
        "static_cast",
        "reinterpret_cast",
        "const_cast",
        "dynamic_cast",
        "sizeof",
        "alignof",
        "decltype",
        "typeid",
        "return",
        "sizeof",
    }
    body = fn.body_text or ""
    # Only scan inside braces when possible
    brace = body.find("{")
    scan = body[brace + 1 :] if brace >= 0 else body
    out: list[CallSite] = []
    ordinal = 0
    for match in _CALL_RE.finditer(scan):
        callee_raw = (match.group("callee") or "").strip()
        callee = callee_raw.split("::")[-1].strip()
        if not callee or callee.casefold() in {n.casefold() for n in noise}:
            continue
        if callee == fn.name and not match.group("recv"):
            # Likely constructor-like / recursive — keep but mark hint
            pass
        recv = (match.group("recv") or "").strip()
        targs = (match.group("targs") or "").strip()
        # Rough argument count: commas at depth 0 until matching ')'
        arg_count = _count_args(scan, match.end() - 1)
        line_in_scan = scan.count("\n", 0, match.start()) + 1
        abs_line = fn.start_line + (body[: brace + 1 + match.start()].count("\n") if brace >= 0 else line_in_scan - 1)
        expr = match.group(0).rstrip("(").strip()
        hint = ""
        if "::" in callee_raw:
            hint = callee_raw
        elif recv:
            hint = f"{recv}{callee}"
        ordinal += 1
        out.append(
            CallSite(
                caller_function_id=fn.stable_id,
                callee_name=callee,
                callee_qualified_hint=hint,
                call_expression=expr[:240],
                file_path=fn.file_path,
                line=abs_line,
                receiver_type_or_object=recv,
                template_args=parse_template_arity(targs) if targs else "",
                argument_count=arg_count,
                ordinal_in_function=ordinal,
                snippet_hash=snippet_hash(expr),
            )
        )
    return out


def _count_args(text: str, open_paren_pos: int) -> int:
    if open_paren_pos < 0 or open_paren_pos >= len(text) or text[open_paren_pos] != "(":
        return 0
    depth = 0
    i = open_paren_pos
    n = len(text)
    commas = 0
    saw_token = False
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return commas + 1 if saw_token else 0
        elif ch == "," and depth == 1:
            commas += 1
            saw_token = True
        elif not ch.isspace() and depth == 1:
            saw_token = True
        i += 1
    return 0


def iter_function_defs(
    repo_root: Path,
    file_path: str,
) -> list[tuple[str, int, int, str, str]]:
    """Yield (name, start_line, end_line, body, resolved_rel) for defs in a file."""
    return [
        (d.name, d.start_line, d.end_line, d.body_text, d.file_path)
        for d in iter_function_definitions(repo_root, file_path)
    ]


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
