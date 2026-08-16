"""Materialize cognitive skill method + refs into an action session directory.

Subagents then read only ``session_dir/method.md`` and ``session_dir/refs/**``,
eliminating host-specific skill discovery paths.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any


def _repo_candidates(project_root: Path | None) -> list[Path]:
    roots: list[Path] = []
    here = Path(__file__).resolve()
    # actions/ → ascendc_pilot → pilot → repo
    roots.append(here.parents[3])
    home = Path.home()
    roots.extend(
        [
            home / ".config" / "opencode" / "ascendc-pilot-plugin",
            home / ".cursor" / "ascendc-pilot-plugin",
            home / ".agents" / "ascendc-pilot-plugin",
        ]
    )
    if project_root is not None:
        roots.append(Path(project_root).resolve())
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        k = str(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


_NAMED_REF_RE = re.compile(
    r"`(?:(?:skills|cognitive-skills)/[a-z0-9-]+/)?references/([^`\s]+?\.md)`",
    re.I,
)
_SKILL_SCOPED_REF_RE = re.compile(
    r"`(?:skills|cognitive-skills)/([a-z0-9-]+)/references/([^`\s]+?\.md)`",
    re.I,
)


def _named_reference_files(*texts: str) -> set[str]:
    """Return ``references/*.md`` basenames/relpaths named in backticks."""
    found: set[str] = set()
    for text in texts:
        for match in _NAMED_REF_RE.finditer(text or ""):
            rel = match.group(1).replace("\\", "/").lstrip("/")
            if rel:
                found.add(rel)
    return found


def _skill_scoped_refs(*texts: str) -> list[tuple[str, str]]:
    """Return ``(skill_id, references/rel.md)`` named as ``skills/<id>/references/...``."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for text in texts:
        for match in _SKILL_SCOPED_REF_RE.finditer(text or ""):
            owner = match.group(1).strip()
            rel = match.group(2).replace("\\", "/").lstrip("/")
            key = (owner, rel)
            if owner and rel and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _ref_is_named(rel: str, wanted: set[str]) -> bool:
    posix = rel.replace("\\", "/")
    name = Path(posix).name
    return posix in wanted or name in wanted or any(
        posix.endswith("/" + w) or w.endswith("/" + posix) for w in wanted
    )


def find_cognitive_skill_dir(skill_id: str, project_root: Path | None = None) -> Path | None:
    sid = (skill_id or "").strip()
    if not sid:
        return None
    for root in _repo_candidates(project_root):
        for rel in (
            Path("cognitive-skills") / sid,
            Path("skills") / sid,
            Path("generated") / "opencode" / "cognitive-skills" / sid,
        ):
            cand = root / rel
            if (cand / "SKILL.md").is_file():
                return cand
    return None


def materialize_method_bundle(
    session_dir: Path,
    *,
    skill_ids: list[str],
    existing_method: str = "",
    project_root: Path | None = None,
    max_refs: int = 24,
    prompt: str = "",
    extra_ref_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Write session method.md from the Action METHOD only.

    Never concatenate Agent ``SKILL.md`` files. ``skill_ids`` is a permission
    ceiling: named ``references/*.md`` may be copied only from those trees.
    Copy a reference when METHOD, the task prompt, or ``extra_ref_paths``
    names it.

    Returns ``{ok, method_path, refs_dir, copied, indexed, missing}``.
    """
    sdir = Path(session_dir)
    sdir.mkdir(parents=True, exist_ok=True)
    refs_dir = sdir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    indexed: list[str] = []
    missing: list[str] = []
    unauthorized: list[str] = []
    method_chunks: list[str] = []
    method_body = existing_method.strip()
    if not method_body:
        return {
            "ok": False,
            "error": "METHOD_BUNDLE_MISSING",
            "reason_code": "METHOD_BUNDLE_MISSING",
            "method_path": "",
            "refs_dir": refs_dir.as_posix(),
            "copied": copied,
            "indexed": indexed,
            "missing": missing,
            "unauthorized": unauthorized,
            "message_zh": "Action METHOD 缺失；禁止拼接 Agent SKILL.md 作为 fallback。",
        }

    method_chunks.append(method_body.rstrip() + "\n")
    allowed = {str(s).strip() for s in skill_ids if str(s).strip()}
    for sid in sorted(allowed):
        method_chunks.append(f"\nDomain map (do not inline): `skills/{sid}/SKILL.md`\n")

    prompt_text = prompt
    prompt_file = sdir / "prompt.md"
    if not prompt_text and prompt_file.is_file():
        prompt_text = prompt_file.read_text(encoding="utf-8")

    extra_blob = "\n".join(f"`{p}`" for p in (extra_ref_paths or []) if p)
    wanted = _named_reference_files(existing_method, prompt_text, extra_blob)
    for owner, rel in _skill_scoped_refs(existing_method, prompt_text, extra_blob):
        if allowed and owner not in allowed:
            posix = f"skills/{owner}/references/{rel}"
            if posix not in unauthorized:
                unauthorized.append(posix)

    for sid in skill_ids:
        sid = str(sid).strip()
        if not sid:
            continue
        skill_dir = find_cognitive_skill_dir(sid, project_root)
        if skill_dir is None:
            missing.append(sid)
            continue
        ref_src = skill_dir / "references"
        if not ref_src.is_dir():
            continue
        dest = refs_dir / sid
        count = 0
        for src in sorted(ref_src.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(ref_src).as_posix()
            if not _ref_is_named(rel, wanted):
                continue
            if count >= max_refs:
                break
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied.append(f"refs/{sid}/{rel}")
            indexed.append(f"references/{sid}/{rel}")
            count += 1

    for raw in extra_ref_paths or []:
        posix = str(raw).replace("\\", "/").lstrip("/")
        parts = posix.split("/")
        if len(parts) >= 4 and parts[0] == "skills" and parts[2] == "references":
            owner = parts[1]
            if allowed and owner not in allowed:
                unauthorized.append(posix)

    method_path = sdir / "method.md"
    if copied:
        method_chunks.append("\n## Materialized refs (session-local)\n\n")
        for c in copied:
            method_chunks.append(f"- `{c}`\n")
    method_path.write_text("".join(method_chunks), encoding="utf-8")

    ok = len(missing) == 0 and len(unauthorized) == 0
    if not ok:
        try:
            method_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": ok,
        "error": "" if ok else "METHOD_BUNDLE_MISSING",
        "reason_code": "" if ok else "METHOD_BUNDLE_MISSING",
        "method_path": method_path.as_posix() if ok and method_path.is_file() else "",
        "refs_dir": refs_dir.as_posix(),
        "copied": copied,
        "indexed": indexed,
        "missing": missing,
        "unauthorized": unauthorized,
        "message_zh": (
            ""
            if ok
            else (
                "Required cognitive skill missing or unauthorized reference: "
                + ", ".join((missing + unauthorized)[:8])
                + "；禁止派发（禁止 placeholder method.md）。"
            )
        ),
    }


# Pointer keys Host writes into the stub. Values are leased paths.
_POINTER_LINE_RE = re.compile(
    r"^\s*(prompt|method|bundle|session_dir|read|write|forbid_read|environment)\s*:\s*(.+)$",
    re.I,
)
_USER_QUESTION_RE = re.compile(r"^USER QUESTION\b", re.I)
_QUESTION_END_PREFIXES = (
    "MUST ",
    "Do NOT",
    "Hard stop:",
    "Return a short",
    "After a directed",
)
# Product / session paths. Do NOT match `/foo` after `a/foo` (user identifiers)
# or `CodeMap / minimal` (prose). Unix abs needs 2+ segments.
_PRODUCT_PATH_RE = re.compile(
    r"(?P<p>"
    r"(?:[A-Za-z]:[/\\][^\s`'\"<>|]+)|"
    r"(?:/(?:[^\s`'\"<>|/]+/)[^\s`'\"<>|]+)|"
    r"runs/[^\s`'\"<>|]+|"
    r"uo/[^\s`'\"<>|]+|"
    r"tg/[^\s`'\"<>|]+|"
    r"ce/[^\s`'\"<>|]+|"
    r"skills/[^\s`'\"<>|]+|"
    r"cognitive-skills/[^\s`'\"<>|]+)"
)


def _tokens_from_pointer_value(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text or text.startswith("(none"):
        return []
    out: list[str] = []
    for raw in text.split(","):
        tok = raw.strip().rstrip("),.;")
        if not tok or tok.startswith("(none"):
            continue
        out.append(tok)
    return out


def extract_stub_paths(stub: str) -> list[str]:
    """Collect leased paths from stub pointer lines — not from USER QUESTION.

    User questions may contain identifiers like ``queryRope/keyRope`` or prose
    like ``CodeMap / minimal``; those must not become BUNDLE_NOT_READABLE misses.
    """
    found: list[str] = []
    in_question = False
    for line in str(stub or "").splitlines():
        stripped = line.strip()
        if _USER_QUESTION_RE.match(stripped):
            in_question = True
            continue
        if in_question:
            if stripped.startswith(_QUESTION_END_PREFIXES):
                in_question = False
            else:
                continue
        ptr = _POINTER_LINE_RE.match(line)
        if ptr:
            for tok in _tokens_from_pointer_value(ptr.group(2)):
                if tok not in found:
                    found.append(tok)
            continue
        for m in _PRODUCT_PATH_RE.finditer(line):
            p = m.group("p").rstrip("),.;")
            if p and p not in found:
                found.append(p)
    return found


def check_bundle_readable(
    *,
    stub: str,
    session_dir: Path,
    project_root: Path,
    allowed_read_paths: list[str],
    allowed_source_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Fail-closed: every concrete path referenced by stub must exist and be leased."""
    from ascendc_pilot.ownership import path_matches_patterns

    missing: list[str] = []
    unleased: list[str] = []
    sdir = Path(session_dir).resolve()
    # Always require session pack essentials.
    for name in ("prompt.md", "method.md", "bundle.yaml"):
        p = sdir / name
        if not p.is_file():
            missing.append(p.as_posix())

    for raw in extract_stub_paths(stub):
        p = Path(raw)
        if not p.is_absolute():
            # Try session-relative then project-relative then agent-relative.
            candidates = [
                sdir / raw,
                Path(project_root) / raw,
            ]
            try:
                from ascendc_pilot.paths import agent_root

                candidates.append(agent_root(project_root) / raw)
            except Exception:  # noqa: BLE001
                pass
            hit = next((c for c in candidates if c.exists()), None)
            if hit is None:
                # Globs / templates — skip non-existing soft refs
                if "*" in raw or "{" in raw:
                    continue
                missing.append(raw)
                continue
            p = hit
        elif not p.exists():
            if "*" in raw:
                continue
            missing.append(raw)
            continue

        # Lease check for pilot-relative paths
        try:
            from ascendc_pilot.paths import agent_root

            rel = p.resolve().relative_to(agent_root(project_root).resolve()).as_posix()
            if allowed_read_paths and not path_matches_patterns(rel, list(allowed_read_paths)):
                # Session dir always ok
                try:
                    p.resolve().relative_to(sdir)
                except ValueError:
                    unleased.append(rel)
        except ValueError:
            # Outside agent root: source roots
            try:
                src_rel = p.resolve().relative_to(Path(project_root).resolve()).as_posix()
            except ValueError:
                # Host method path outside project — allow if under session refs or skills
                continue
            roots = [str(x).replace("\\", "/").lstrip("/") for x in (allowed_source_roots or [])]
            if roots:
                ok = any(
                    src_rel == r or src_rel.startswith(r.rstrip("/") + "/")
                    for r in roots
                )
                if not ok:
                    unleased.append(src_rel)

    if missing or unleased:
        return {
            "ok": False,
            "error": "BUNDLE_NOT_READABLE",
            "reason_code": "BUNDLE_NOT_READABLE",
            "missing": missing,
            "unleased": unleased,
            "message_zh": (
                "Action Bundle 读闭合失败：stub/session 引用的路径缺失或不在 lease 可读集合内；"
                "禁止派发子代理。"
            ),
        }
    return {"ok": True}


__all__ = [
    "find_cognitive_skill_dir",
    "materialize_method_bundle",
    "extract_stub_paths",
    "check_bundle_readable",
]
