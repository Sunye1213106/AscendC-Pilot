"""Materialize cognitive skill method + refs into an action session directory.

Subagents then read only ``session_dir/method.md`` and ``session_dir/refs/**``,
eliminating host-specific skill discovery paths.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _repo_candidates(project_root: Path | None) -> list[Path]:
    roots: list[Path] = []
    here = Path(__file__).resolve()
    # actions/ → ascendc_pilot → pilot → repo
    roots.append(here.parents[3])
    from ascendc_pilot.paths import opencode_plugin_root

    roots.extend(
        [
            opencode_plugin_root(),
            Path.home() / ".cursor" / "ascendc-pilot-plugin",
            Path.home() / ".agents" / "ascendc-pilot-plugin",
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


_REL_REF_RE = re.compile(r"`references/([^`\s]+?\.md)`", re.I)
_SKILL_SCOPED_REF_RE = re.compile(
    r"`(?:skills|cognitive-skills)/([a-z0-9-]+)/references/([^`\s]+?\.md)`",
    re.I,
)
_QUALIFIED_REF_PATH_RE = re.compile(
    r"^(?:skills|cognitive-skills)/([a-z0-9-]+)/references/([^`\s]+?\.md)$",
    re.I,
)


def parse_declared_refs(
    *texts: str,
    current_skill_id: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Return ``(owner, rel)`` refs plus unauthorized foreign scoped paths.

    ``references/foo.md`` binds to ``current_skill_id``.
    ``skills/foo/references/bar.md`` binds to ``foo`` only when ``foo`` is the
    current skill; otherwise it is unauthorized. No basename fallback.
    """
    owner_now = (current_skill_id or "").strip()
    requested: list[tuple[str, str]] = []
    unauthorized: list[str] = []
    seen: set[tuple[str, str]] = set()

    def _add(owner: str, rel: str) -> None:
        key = (owner, rel)
        if owner and rel and key not in seen:
            seen.add(key)
            requested.append(key)

    for text in texts:
        for match in _SKILL_SCOPED_REF_RE.finditer(text or ""):
            owner = match.group(1).strip()
            rel = match.group(2).replace("\\", "/").lstrip("/")
            posix = f"skills/{owner}/references/{rel}"
            if owner != owner_now:
                if posix not in unauthorized:
                    unauthorized.append(posix)
                continue
            _add(owner, rel)
        for match in _REL_REF_RE.finditer(text or ""):
            rel = match.group(1).replace("\\", "/").lstrip("/")
            _add(owner_now, rel)
    return requested, unauthorized


def parse_qualified_ref_path(raw: str) -> tuple[str, str] | None:
    """Parse ``skills/<id>/references/<rel>.md``. Bare basenames are rejected."""
    posix = str(raw or "").replace("\\", "/").lstrip("/")
    hit = _QUALIFIED_REF_PATH_RE.match(posix)
    if not hit:
        return None
    return hit.group(1).strip(), hit.group(2).replace("\\", "/").lstrip("/")


def declared_reference_paths(skill_id: str, project_root: Path | None = None) -> tuple[str, ...]:
    """SKILL.md is the sole selector: qualified paths of locally declared refs."""
    sid = (skill_id or "").strip()
    if not sid:
        return ()
    skill_dir = find_cognitive_skill_dir(sid, project_root)
    if skill_dir is None:
        return ()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return ()
    requested, _unauth = parse_declared_refs(
        skill_md.read_text(encoding="utf-8"),
        current_skill_id=sid,
    )
    return tuple(f"skills/{owner}/references/{rel}" for owner, rel in requested)


def find_knowledge_file(ref: str, project_root: Path | None = None) -> Path | None:
    """Resolve ``ascendc/foo.md`` or ``knowledge/ascendc/foo.md`` from repo roots."""
    rel = str(ref or "").replace("\\", "/").lstrip("/")
    if rel.startswith("knowledge/"):
        rel = rel[len("knowledge/") :]
    if not rel or ".." in rel.split("/"):
        return None
    for root in _repo_candidates(project_root):
        cand = root / "knowledge" / rel
        if cand.is_file():
            return cand
    return None


def materialize_knowledge_refs(
    session_dir: Path,
    knowledge_refs: list[str] | None,
    *,
    project_root: Path | None = None,
    knowledge_ns: str = "",
) -> dict[str, Any]:
    """Copy declared knowledge files into ``session_dir/knowledge/**``.

    ``knowledge_ns`` optionally namespaces copies under ``knowledge/<ns>/``
    so parallel fanout slices do not share one folder.
    """
    dest = Path(session_dir) / "knowledge"
    ns = str(knowledge_ns or "").strip().replace("\\", "/").strip("/")
    if ns:
        dest = dest / ns
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    missing: list[str] = []
    for raw in knowledge_refs or []:
        rel = str(raw or "").replace("\\", "/").lstrip("/")
        if rel.startswith("knowledge/"):
            rel = rel[len("knowledge/") :]
        src = find_knowledge_file(rel, project_root)
        if src is None:
            missing.append(rel or str(raw))
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        copied.append(f"{ns}/{rel}" if ns else rel)
    ok = not missing
    return {
        "ok": ok,
        "copied": copied,
        "missing": missing,
        "error": "" if ok else "KNOWLEDGE_MISSING",
        "reason_code": "" if ok else "KNOWLEDGE_MISSING",
        "message_zh": "" if ok else f"knowledge_refs 缺失：{missing}",
    }


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


def _normalize_ref_rel(raw: str) -> str:
    rel = str(raw or "").replace("\\", "/").lstrip("/")
    if rel.startswith("references/"):
        rel = rel[len("references/") :]
    return rel


def materialize_method_bundle(
    session_dir: Path,
    *,
    skill_ids: list[str],
    existing_method: str = "",
    project_root: Path | None = None,
    max_refs: int = 24,
    prompt: str = "",
    extra_ref_paths: list[str] | None = None,
    current_skill_id: str = "",
    method_filename: str = "method.md",
    refs_dirname: str = "refs",
    refs_ns: str = "",
    copy_declared_refs: bool = True,
    explicit_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Write session method file from the current Action Skill.

    ``skill_ids`` is a permission ceiling. Reference identity is
    ``(owner_skill_id, relative_path)`` — never a basename.
    Copy selectors are only ActionSpec / axis ``explicit_refs`` plus optional
    qualified ``extra_ref_paths``. Skill-body backticks are pointers, not a
    second discovery mechanism.
    ``refs_ns`` optionally namespaces copied files under ``refs/<ns>/`` so
    parallel fanout slices in one session do not share a folder.
    ``copy_declared_refs=False`` keeps pointer text but does not copy those
    files (fanout parent routers: slices load their own ``method_ref``).
    """
    sdir = Path(session_dir)
    sdir.mkdir(parents=True, exist_ok=True)
    refs_dir = sdir / (refs_dirname or "refs")
    refs_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    indexed: list[str] = []
    missing: list[str] = []
    unauthorized: list[str] = []
    ambiguous: list[str] = []
    method_chunks: list[str] = []
    method_body = existing_method.strip()
    if not method_body:
        return {
            "ok": False,
            "error": "SKILL_BUNDLE_MISSING",
            "reason_code": "SKILL_BUNDLE_MISSING",
            "method_path": "",
            "refs_dir": refs_dir.as_posix(),
            "copied": copied,
            "indexed": indexed,
            "missing": missing,
            "unauthorized": unauthorized,
            "message_zh": "Action Skill 缺失。",
        }

    method_chunks.append(method_body.rstrip() + "\n")
    allowed = {str(s).strip() for s in skill_ids if str(s).strip()}
    owner_now = (current_skill_id or "").strip()
    if not owner_now:
        owner_now = next(iter(allowed), "")

    _ignored, scoped_unauth = parse_declared_refs(
        existing_method,
        current_skill_id=owner_now,
    )
    unauthorized.extend(scoped_unauth)
    requested: list[tuple[str, str]] = []
    if copy_declared_refs:
        for raw in explicit_refs or []:
            rel = _normalize_ref_rel(raw)
            if not rel or ".." in rel.split("/"):
                if str(raw) not in ambiguous:
                    ambiguous.append(str(raw))
                continue
            requested.append((owner_now, rel))

    skill_declared = set(requested)
    for raw in extra_ref_paths or []:
        parsed = parse_qualified_ref_path(str(raw))
        if parsed is None:
            ambiguous.append(str(raw))
            continue
        extra_owner, extra_rel = parsed
        if extra_owner not in allowed:
            posix = f"skills/{extra_owner}/references/{extra_rel}"
            if posix not in unauthorized:
                unauthorized.append(posix)
            continue
        if (extra_owner, extra_rel) in skill_declared:
            continue
        requested.append((extra_owner, extra_rel))

    for owner, rel in requested:
        if len(copied) >= max_refs:
            break
        posix = f"skills/{owner}/references/{rel}"
        if allowed and owner not in allowed:
            if posix not in unauthorized:
                unauthorized.append(posix)
            continue
        skill_dir = find_cognitive_skill_dir(owner, project_root)
        if skill_dir is None:
            if posix not in missing:
                missing.append(posix)
            continue
        src = skill_dir / "references" / rel
        if not src.is_file():
            if posix not in missing:
                missing.append(posix)
            continue
        dest_owner = str(refs_ns or owner).strip() or owner
        dest = refs_dir / dest_owner / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        prefix = (refs_dirname or "refs").replace("\\", "/").strip("/")
        copied.append(f"{prefix}/{dest_owner}/{rel}")
        indexed.append(f"references/{dest_owner}/{rel}")

    method_path = sdir / (method_filename or "method.md")
    if copied:
        method_chunks.append("\n## Materialized refs (session-local)\n\n")
        for c in copied:
            method_chunks.append(f"- `{c}`\n")
    method_path.write_text("".join(method_chunks), encoding="utf-8")

    fail_bits = missing + unauthorized + ambiguous
    ok = len(fail_bits) == 0
    reason = ""
    if ambiguous:
        reason = "REFERENCE_AMBIGUOUS"
    elif unauthorized or missing:
        reason = "SKILL_BUNDLE_MISSING"
    if not ok:
        try:
            method_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": ok,
        "error": "" if ok else reason or "SKILL_BUNDLE_MISSING",
        "reason_code": "" if ok else reason or "SKILL_BUNDLE_MISSING",
        "method_path": method_path.as_posix() if ok and method_path.is_file() else "",
        "refs_dir": refs_dir.as_posix(),
        "copied": copied,
        "indexed": indexed,
        "missing": missing,
        "unauthorized": unauthorized,
        "ambiguous": ambiguous,
        "requested": [f"skills/{o}/references/{r}" for o, r in requested],
        "message_zh": (
            ""
            if ok
            else (
                "Required cognitive skill missing or unauthorized reference: "
                + ", ".join(fail_bits[:8])
                + "；禁止派发（禁止 placeholder method.md）。"
            )
        ),
    }


# Typed pointer keys Host writes into the stub. Do not flatten these into one list.
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
_IDENTITY_LINE_RE = re.compile(
    r"^\s*(action_id|actor_id|run_id)\s*=\s*(.+)$",
    re.I,
)
_PROJECT_ROOT_RE = re.compile(r"(?:acp\s+--project|--project)\s+(\S+)", re.I)


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


def _soft_ref(raw: str) -> bool:
    return "*" in raw or "{" in raw


@dataclass
class TaskStubPointers:
    """Typed Host→subagent pointers. Inputs / outputs / metadata stay separate."""

    prompt: str = ""
    method: str = ""
    bundle: str = ""
    environment: str = ""
    session_dir: str = ""
    project_root: str = ""
    run_id: str = ""
    action_id: str = ""
    actor_id: str = ""
    read: list[str] = field(default_factory=list)
    write: list[str] = field(default_factory=list)
    forbid_read: list[str] = field(default_factory=list)

    def required_input_paths(self) -> list[str]:
        out: list[str] = []
        for p in (self.prompt, self.method, self.bundle, self.environment, *self.read):
            s = str(p or "").strip()
            if s and not s.startswith("(none"):
                out.append(s)
        return out

    def output_paths(self) -> list[str]:
        return [p for p in self.write if str(p or "").strip() and not str(p).startswith("(none")]

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "method": self.method,
            "bundle": self.bundle,
            "environment": self.environment,
            "session_dir": self.session_dir,
            "project_root": self.project_root,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "actor_id": self.actor_id,
            "read": list(self.read),
            "write": list(self.write),
            "forbid_read": list(self.forbid_read),
        }


def parse_stub_pointers(stub: str) -> TaskStubPointers:
    """Parse typed pointer lines only. Never scan prose project paths as inputs."""
    ptr = TaskStubPointers()
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
        ident = _IDENTITY_LINE_RE.match(stripped)
        if ident:
            key = ident.group(1).lower()
            val = ident.group(2).strip()
            if key == "action_id":
                ptr.action_id = val
            elif key == "actor_id":
                ptr.actor_id = val
            elif key == "run_id":
                ptr.run_id = val
            continue
        acp = _PROJECT_ROOT_RE.search(stripped)
        if acp and not ptr.project_root:
            ptr.project_root = acp.group(1)
            continue
        hit = _POINTER_LINE_RE.match(line)
        if not hit:
            continue
        key = hit.group(1).lower()
        value = hit.group(2).strip()
        if key == "prompt":
            ptr.prompt = value
        elif key == "method":
            ptr.method = value
        elif key == "bundle":
            ptr.bundle = value
        elif key == "environment":
            ptr.environment = value
        elif key == "session_dir":
            ptr.session_dir = value
        elif key == "read":
            ptr.read = _tokens_from_pointer_value(value)
        elif key == "write":
            ptr.write = _tokens_from_pointer_value(value)
        elif key == "forbid_read":
            ptr.forbid_read = _tokens_from_pointer_value(value)
    return ptr


def extract_stub_paths(stub: str) -> list[str]:
    """Required input paths from typed pointer lines — not writes, not project root."""
    return parse_stub_pointers(stub).required_input_paths()


def method_skill_ids_for_action(
    action: dict[str, Any] | None,
    *,
    agent_skill_ids: list[str] | None = None,
    extra_ref_paths: list[str] | None = None,
) -> list[str]:
    """Action Skill plus owners of extra qualified refs.

    Overlay skills stay out of ``max_skill_ids``. The agent's ceiling filters
    extra refs only; the Action's own ``skill_id`` is always kept.
    """
    ceiling = {str(s).strip() for s in (agent_skill_ids or []) if str(s).strip()}
    own = ""
    raw = str((action or {}).get("skill_id") or (action or {}).get("action_method_id") or "").strip()
    if raw:
        own = raw.rsplit("/", 1)[-1].strip()
    extras: set[str] = set()
    for raw_path in extra_ref_paths or []:
        parsed = parse_qualified_ref_path(str(raw_path))
        if parsed is None:
            continue
        extras.add(parsed[0])
    if ceiling:
        extras &= ceiling
    wanted = set(extras)
    if own:
        wanted.add(own)
    return sorted(sid for sid in wanted if sid)


def _resolve_existing_path(
    raw: str,
    *,
    session_dir: Path,
    project_root: Path,
) -> Path | None:
    p = Path(raw)
    if p.is_absolute():
        return p if p.exists() else None
    candidates = [session_dir / raw, Path(project_root) / raw]
    try:
        from ascendc_pilot.paths import agent_root

        candidates.append(agent_root(project_root) / raw)
    except Exception:  # noqa: BLE001
        pass
    return next((c for c in candidates if c.exists()), None)


def _pilot_rel(path: Path, project_root: Path) -> str | None:
    try:
        from ascendc_pilot.paths import agent_root

        return path.resolve().relative_to(agent_root(project_root).resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _source_rel(path: Path, project_root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(Path(project_root).resolve()).as_posix()
    except (ValueError, OSError):
        return None
    return rel


def _in_source_roots(src_rel: str, allowed_source_roots: list[str] | None) -> bool:
    roots = [str(x).replace("\\", "/").lstrip("/") for x in (allowed_source_roots or []) if str(x).strip()]
    if not roots:
        return True
    if src_rel in {".", ""}:
        return False
    return any(src_rel == r or src_rel.startswith(r.rstrip("/") + "/") for r in roots)


def check_input_readability(
    *,
    pointers: TaskStubPointers,
    session_dir: Path,
    project_root: Path,
    allowed_read_paths: list[str],
    allowed_source_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Required inputs must exist and be inside the read lease / source roots."""
    from ascendc_pilot.ownership import path_matches_patterns

    missing: list[str] = []
    unleased: list[str] = []
    sdir = Path(session_dir).resolve()
    for name in ("prompt.md", "method.md", "bundle.yaml"):
        p = sdir / name
        if not p.is_file():
            missing.append(p.as_posix())

    for raw in pointers.required_input_paths():
        if _soft_ref(raw):
            continue
        hit = _resolve_existing_path(raw, session_dir=sdir, project_root=project_root)
        if hit is None:
            missing.append(raw)
            continue
        try:
            hit.resolve().relative_to(sdir)
            continue
        except ValueError:
            pass
        rel = _pilot_rel(hit, project_root)
        if rel is not None:
            if allowed_read_paths and not path_matches_patterns(rel, list(allowed_read_paths)):
                unleased.append(rel)
            continue
        src_rel = _source_rel(hit, project_root)
        if src_rel is None:
            continue
        if not _in_source_roots(src_rel, allowed_source_roots):
            unleased.append(src_rel)

    if missing or unleased:
        return {
            "ok": False,
            "error": "BUNDLE_NOT_READABLE",
            "reason_code": "BUNDLE_NOT_READABLE",
            "missing": missing,
            "unleased": unleased,
            "message_zh": (
                "Action Bundle 读闭合失败：required inputs 缺失或不在 lease 可读集合内；"
                "禁止派发子代理。"
            ),
        }
    return {"ok": True}


def check_output_writability(
    *,
    pointers: TaskStubPointers,
    session_dir: Path,
    project_root: Path,
    allowed_write_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Outputs need not exist. Only verify they sit inside the write lease."""
    from ascendc_pilot.ownership import path_matches_patterns

    unwritable: list[str] = []
    writes = list(allowed_write_paths or [])
    sdir = Path(session_dir).resolve()
    for raw in pointers.output_paths():
        if _soft_ref(raw):
            rel = str(raw).replace("\\", "/").lstrip("/")
            if writes and not path_matches_patterns(rel, writes):
                # Absolute-under-agent glob: strip agent root prefix if present.
                pilot_rel = rel
                try:
                    from ascendc_pilot.paths import agent_root

                    prefix = agent_root(project_root).resolve().as_posix().rstrip("/") + "/"
                    posix = Path(raw).as_posix() if Path(raw).is_absolute() else rel
                    if posix.replace("\\", "/").startswith(prefix):
                        pilot_rel = posix.replace("\\", "/")[len(prefix) :]
                except Exception:  # noqa: BLE001
                    pass
                if not path_matches_patterns(pilot_rel, writes):
                    unwritable.append(raw)
            continue
        p = Path(raw)
        if not p.is_absolute():
            try:
                from ascendc_pilot.paths import agent_root

                p = agent_root(project_root) / raw
            except Exception:  # noqa: BLE001
                p = Path(project_root) / raw
        try:
            p.resolve().relative_to(sdir)
            continue
        except (ValueError, OSError):
            pass
        rel = _pilot_rel(p, project_root)
        if rel is None:
            continue
        if writes and not path_matches_patterns(rel, writes):
            unwritable.append(rel)

    if unwritable:
        return {
            "ok": False,
            "error": "BUNDLE_NOT_WRITABLE",
            "reason_code": "BUNDLE_NOT_WRITABLE",
            "unwritable": unwritable,
            "message_zh": "Action 声明的 write 路径不在 write lease 内；禁止派发。",
        }
    return {"ok": True}


def check_metadata_identity(
    *,
    pointers: TaskStubPointers,
    project_root: Path,
) -> dict[str, Any]:
    """``project_root`` is identity, not a source-read lease."""
    declared = str(pointers.project_root or "").strip()
    if not declared:
        return {"ok": True}
    try:
        got = Path(declared).expanduser().resolve()
        expected = Path(project_root).expanduser().resolve()
    except OSError as exc:
        return {
            "ok": False,
            "error": "BUNDLE_NOT_READABLE",
            "reason_code": "PROJECT_ROOT_MISMATCH",
            "message_zh": f"stub project_root 无法解析：{exc}",
        }
    if got != expected:
        return {
            "ok": False,
            "error": "BUNDLE_NOT_READABLE",
            "reason_code": "PROJECT_ROOT_MISMATCH",
            "declared": got.as_posix(),
            "expected": expected.as_posix(),
            "message_zh": "stub ``--project`` 与当前 resolved project 不一致；禁止派发。",
        }
    return {"ok": True}


def missing_reference_paths(references: list[dict[str, str]] | None) -> list[str]:
    """Paths recorded as missing by a reference status list."""
    out: list[str] = []
    for row in references or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") == "missing":
            p = str(row.get("path") or "").strip()
            if p:
                out.append(p)
    return out


def check_bundle_readable(
    *,
    stub: str = "",
    session_dir: Path,
    project_root: Path,
    allowed_read_paths: list[str],
    allowed_source_roots: list[str] | None = None,
    allowed_write_paths: list[str] | None = None,
    pointers: TaskStubPointers | None = None,
) -> dict[str, Any]:
    """Fail-closed prepare gate using typed pointers, not a flattened path list."""
    ptr = pointers if pointers is not None else parse_stub_pointers(stub)
    ident = check_metadata_identity(pointers=ptr, project_root=project_root)
    if not ident.get("ok"):
        return ident
    reads = check_input_readability(
        pointers=ptr,
        session_dir=session_dir,
        project_root=project_root,
        allowed_read_paths=allowed_read_paths,
        allowed_source_roots=allowed_source_roots,
    )
    if not reads.get("ok"):
        return reads
    writes = check_output_writability(
        pointers=ptr,
        session_dir=session_dir,
        project_root=project_root,
        allowed_write_paths=allowed_write_paths,
    )
    if not writes.get("ok"):
        return writes
    return {"ok": True}


__all__ = [
    "TaskStubPointers",
    "declared_reference_paths",
    "find_cognitive_skill_dir",
    "materialize_method_bundle",
    "method_skill_ids_for_action",
    "parse_declared_refs",
    "parse_qualified_ref_path",
    "parse_stub_pointers",
    "extract_stub_paths",
    "check_input_readability",
    "check_output_writability",
    "check_metadata_identity",
    "check_bundle_readable",
    "missing_reference_paths",
    "find_knowledge_file",
    "materialize_knowledge_refs",
]
