# -*- coding: utf-8 -*-
"""Capture a reproducible Git change payload (in memory; yaml write is optional)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

_HUNK = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_DIFF_FILE = re.compile(r"^\+\+\+\s+b/(.+)$|^\+\+\+\s+(.+)$")
_OLD_FILE = re.compile(r"^---\s+a/(.+)$|^---\s+(.+)$")


def parse_diff_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Map path → list of (start_line, end_line) for new-file hunks."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        fm = _DIFF_FILE.match(line)
        if fm:
            current = (fm.group(1) or fm.group(2) or "").strip()
            if current == "/dev/null":
                current = None
            continue
        hm = _HUNK.match(line)
        if hm and current:
            start = int(hm.group(3))
            count = int(hm.group(4) or "1")
            end = start + max(count, 1) - 1
            ranges.setdefault(current, []).append((start, end))
    return ranges


def parse_two_sided_spans(diff_text: str) -> list[dict[str, Any]]:
    """Preserve both old/new hunk spans and add/delete/modify/rename status."""
    rows: list[dict[str, Any]] = []
    old_path = ""
    new_path = ""
    for line in diff_text.splitlines():
        old = _OLD_FILE.match(line)
        if old:
            old_path = (old.group(1) or old.group(2) or "").strip()
            continue
        new = _DIFF_FILE.match(line)
        if new:
            new_path = (new.group(1) or new.group(2) or "").strip()
            continue
        hunk = _HUNK.match(line)
        if not hunk:
            continue
        old_start, old_count = int(hunk.group(1)), int(hunk.group(2) or "1")
        new_start, new_count = int(hunk.group(3)), int(hunk.group(4) or "1")
        if old_path == "/dev/null":
            status = "add"
        elif new_path == "/dev/null":
            status = "delete"
        elif old_path and new_path and old_path != new_path:
            status = "rename"
        else:
            status = "modify"
        rows.append({
            "status": status,
            "old": {"file": old_path or None, "start": old_start, "end": old_start + max(old_count, 1) - 1},
            "new": {"file": new_path or None, "start": new_start, "end": new_start + max(new_count, 1) - 1},
        })
    return rows


_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
_IDENT_SKIP = frozenset(
    {
        "int", "void", "bool", "char", "long", "short", "float", "double", "auto",
        "const", "static", "inline", "return", "class", "struct", "enum", "namespace",
        "template", "typename", "using", "public", "private", "protected", "virtual",
        "override", "nullptr", "true", "false", "this", "if", "else", "for", "while",
        "switch", "case", "break", "continue", "sizeof", "include", "define",
        "ACLNN", "TILING", "KERNEL", "TODO", "FIXME",
        "std", "vector", "string", "size_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t",
        "int8_t", "int16_t", "int32_t", "int64_t", "batch", "size", "type", "value",
        "data", "info", "flag", "mode", "ptr",
    }
)


def extract_added_identifiers(diff_text: str, *, limit: int = 24) -> list[str]:
    """Unique identifiers from added diff lines (intent seeds, not a spec)."""
    seen: list[str] = []
    for line in str(diff_text or "").splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for match in _IDENT.finditer(line[1:]):
            name = match.group(1)
            if name in _IDENT_SKIP or name.startswith("_"):
                continue
            if name.isupper() and len(name) <= 16:
                continue
            if name not in seen:
                seen.append(name)
            if len(seen) >= limit:
                return seen
    return seen


def operator_relative_path(path: str) -> str:
    """Strip repo prefixes. Keep ``tests/`` even when the file sits under ``tests/ut/op_host``."""
    norm = str(path or "").replace("\\", "/").lstrip("./")
    for marker in ("tests/", "examples/"):
        idx = norm.find(marker)
        if idx >= 0:
            return norm[idx:]
    for marker in ("op_host/", "op_kernel/", "common/"):
        idx = norm.find(marker)
        if idx >= 0:
            return norm[idx:]
    return norm


def suggested_file_line_queries(
    ranges: dict[str, list[tuple[int, int]]], *, limit: int = 8
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, spans in ranges.items():
        raw = str(path or "").replace("\\", "/")
        rel = operator_relative_path(path)
        if (
            "/tests/" in raw
            or raw.startswith("tests/")
            or rel.startswith("tests/")
            or rel.endswith(".md")
        ):
            continue
        for start, _end in spans:
            out.append({"file": rel, "line": int(start)})
            if len(out) >= limit:
                return out
    return out


def _ident_suggest_rank(name: str) -> int:
    if name.isupper():
        return 2
    camel = name[:1].isupper() or any(c.isupper() for c in name[1:])
    if camel and len(name) >= 6:
        return 0
    return 1


def suggested_ident_queries(identifiers: list[str], *, limit: int = 8) -> list[dict[str, Any]]:
    items = [str(n).strip() for n in identifiers if str(n or "").strip()]
    ranked = [name for _, name in sorted(enumerate(items), key=lambda p: (_ident_suggest_rank(p[1]), p[0]))]
    out: list[dict[str, Any]] = []
    for ident in ranked:
        out.append({"ident": ident})
        if len(out) >= limit:
            return out
    return out


def iter_hunk_windows(
    diff_text: str, *, max_hunks: int = 12, max_lines: int = 80
) -> list[tuple[str, int, str]]:
    """Small per-hunk windows so reviewers need not read the full patch."""
    windows: list[tuple[str, int, str]] = []
    current_path = ""
    buf: list[str] = []
    hunk_start = 0
    for line in str(diff_text or "").splitlines():
        fm = _DIFF_FILE.match(line)
        if fm:
            if buf and current_path and hunk_start:
                windows.append((current_path, hunk_start, "\n".join(buf[:max_lines])))
                if len(windows) >= max_hunks:
                    return windows
            current_path = (fm.group(1) or fm.group(2) or "").strip()
            buf = []
            hunk_start = 0
            continue
        hm = _HUNK.match(line)
        if hm:
            if buf and current_path and hunk_start:
                windows.append((current_path, hunk_start, "\n".join(buf[:max_lines])))
                if len(windows) >= max_hunks:
                    return windows
            hunk_start = int(hm.group(3))
            buf = [line]
            continue
        if buf:
            buf.append(line)
    if buf and current_path and hunk_start and len(windows) < max_hunks:
        windows.append((current_path, hunk_start, "\n".join(buf[:max_lines])))
    return windows


def render_change_index(
    *,
    subject: str = "",
    log_oneline: str = "",
    base_sha: str = "",
    head_sha: str = "",
    ranges: dict[str, list[tuple[int, int]]] | None = None,
    identifiers: list[str] | None = None,
    queries: list[dict[str, Any]] | None = None,
) -> str:
    """Markdown index: the Spec/Standards primary input instead of full diff.md."""
    ranges = ranges or {}
    identifiers = identifiers or []
    queries = queries or []
    lines = [
        "# Change capture index",
        "",
        "Do not linearly read `diff.md`. Use this index, then `uo-query --file --line`.",
        "",
        "## Subject",
        subject.strip() or "(no subject)",
        "",
        f"- base: `{base_sha or '-'}`",
        f"- head: `{head_sha or '-'}`",
        "",
    ]
    if log_oneline.strip():
        lines.extend(["## git log --oneline", "```", log_oneline.strip(), "```", ""])
    lines.append("## Changed files / hunks")
    if not ranges:
        lines.append("(none)")
    for path, spans in ranges.items():
        span_s = ", ".join(f"{a}-{b}" for a, b in spans)
        lines.append(f"- `{operator_relative_path(path)}`: {span_s}")
    lines.extend(["", "## Added identifiers", ""])
    if identifiers:
        lines.append(", ".join(f"`{n}`" for n in identifiers))
    else:
        lines.append("(none extracted)")
    lines.extend(["", "## Suggested uo-query (form 1 identifiers, then form 3 with ident)", ""])
    if not queries:
        lines.append("(none)")
    for q in queries:
        ident = str(q.get("ident") or "").strip()
        if ident:
            lines.append(f"- `uo-query {ident}`")
            continue
        path = operator_relative_path(str(q.get("file") or ""))
        line = int(q.get("line") or 0)
        if path and line:
            lines.append(f"- `uo-query --file {path} --line {line}`")
    lines.append("")
    return "\n".join(lines)

_SOURCE_SUFFIXES = {".cpp", ".cc", ".c", ".h", ".hpp", ".cuh", ".cu", ".py"}
_WIN_GIT_CANDIDATES = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)


def git_executable() -> str:
    """Resolve git even when OpenCode/acp inherit a thin PATH (Windows)."""
    explicit = (os.environ.get("GIT_EXECUTABLE") or os.environ.get("GIT") or "").strip()
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        found_explicit = shutil.which(explicit)
        if found_explicit:
            return found_explicit
    found = shutil.which("git")
    if found:
        return found
    if os.name == "nt":
        for candidate in _WIN_GIT_CANDIDATES:
            if Path(candidate).is_file():
                return candidate
    return "git"


def _run_git(root: Path, *args: str, allow_diff: bool = False) -> str:
    proc = subprocess.run(
        [git_executable(), *args],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if allow_diff and proc.returncode in {0, 1}:
        return proc.stdout or ""
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout or ""


def _operator_scope(op_root: Path) -> tuple[Path, list[str], str]:
    """Run git at the repo root, pathspec-limited to the operator tree."""
    op = Path(op_root).expanduser().resolve()
    try:
        top_text = _run_git(op, "rev-parse", "--show-toplevel").strip()
    except RuntimeError:
        return op, [], ""
    if not top_text:
        return op, [], ""
    top = Path(top_text).resolve()
    try:
        prefix = op.relative_to(top).as_posix().replace("\\", "/").strip("/")
    except ValueError:
        return op, [], ""
    if prefix in {"", "."}:
        return top, [], ""
    return top, ["--", prefix], prefix + "/"


def _rewrite_diff_prefix(diff_text: str, prefix: str) -> str:
    if not prefix or not diff_text:
        return diff_text
    needle_a = f"a/{prefix}"
    needle_b = f"b/{prefix}"
    out: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        out.append(line.replace(needle_a, "a/").replace(needle_b, "b/"))
    return "".join(out)


def _untracked_diffs(git_cwd: Path, pathspec: list[str], prefix: str) -> str:
    listed = _run_git(git_cwd, "ls-files", "--others", "--exclude-standard", *pathspec)
    chunks: list[str] = []
    for raw in listed.splitlines():
        rel = raw.replace("\\", "/").strip()
        if not rel:
            continue
        op_rel = rel[len(prefix) :] if prefix and rel.startswith(prefix) else rel
        if Path(op_rel).suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        abs_path = git_cwd / rel
        if not abs_path.is_file():
            continue
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "\0" in text[:4096]:
            continue
        lines = text.splitlines()
        body = "".join(f"+{line}\n" for line in lines)
        n = max(len(lines), 1)
        chunks.append(
            f"diff --git a/{op_rel} b/{op_rel}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{op_rel}\n"
            f"@@ -0,0 +1,{n} @@\n"
            f"{body}"
        )
    return "".join(chunks)


def capture(
    project_root: Path | str,
    *,
    base: str = "HEAD",
    head: str = "",
    architecture: str = "",
    output: Path | str | None = None,
) -> dict[str, Any]:
    """Capture SHAs, unified diff, and parsed spans; optionally write YAML."""
    root = Path(project_root).expanduser().resolve()
    git_cwd, pathspec, prefix = _operator_scope(root)
    base_sha = _run_git(git_cwd, "rev-parse", base).strip()
    head_ref = head or "HEAD"
    head_sha = _run_git(git_cwd, "rev-parse", head_ref).strip()
    diff_args = ["diff", "--no-ext-diff", "--unified=3", base_sha]
    if head:
        diff_args.append(head_sha)
    diff_args.extend(pathspec)
    diff_text = _run_git(git_cwd, *diff_args, allow_diff=True)
    if not head:
        extra = _untracked_diffs(git_cwd, pathspec, prefix)
        if extra:
            diff_text = (diff_text.rstrip() + "\n" + extra) if diff_text.strip() else extra
    diff_text = _rewrite_diff_prefix(diff_text, prefix)
    payload: dict[str, Any] = {
        "schema": "ce-change-capture/v1",
        "base_sha": base_sha,
        "head_sha": head_sha,
        "diff": diff_text,
        "diff_spans": {
            path: [[start, end] for start, end in spans]
            for path, spans in parse_diff_ranges(diff_text).items()
        },
        "two_sided_spans": parse_two_sided_spans(diff_text),
    }
    if output is not None:
        path = Path(output)
        if not path.is_absolute():
            pilot = root / ".ascendc-pilot"
            path = pilot / architecture / path if architecture else pilot / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        payload["path"] = str(path)
    return payload


capture_change = capture
