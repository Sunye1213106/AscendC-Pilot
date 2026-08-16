"""Load Agent declarations (scopes/role/mode/forbidden) from agents or installed bundles."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

#: Forbidden tags with deterministic harness meaning.
KNOWN_FORBIDDEN_TAGS = frozenset(
    {
        "modify_pilot_state",
        "declare_workflow_passed",
        "write_outside_declared_scope",
        "modify_uo_product",
        "no_free_repo_search",
        "free_repo_search",
        "write_canonical_ce_plan",
        "write_uo_formal_products",
        "write_excluded_set",
        "write_uo_checks",
        "write_canonical_uo_ir",
        "apply_semantic_gap_patch",
        "rewrite_deterministic_ledger",
    }
)

BEHAVIORAL_CONSTRAINT_TAGS = frozenset(
    {
        "invent_evidence",
        "invent_lemma_leads",
        "invent_unresolved_ids",
        "approve_own_producer_output",
        "do_not_invent_evidence",
        "do_not_approve_own_work",
    }
)


def _repo_root_candidates(project_root: Path | None) -> list[Path]:
    roots: list[Path] = []
    here = Path(__file__).resolve()
    # pilot/ascendc_pilot → repo root
    roots.append(here.parents[2])
    if project_root is not None:
        pr = Path(project_root).expanduser().resolve()
        roots.append(pr)
        for parent in pr.parents:
            roots.append(parent)
            if len(roots) > 12:
                break
    home = Path.home()
    roots.extend(
        [
            home / ".config" / "opencode" / "ascendc-pilot-plugin",
            home / ".cursor" / "ascendc-pilot-plugin",
            home / ".agents" / "ascendc-pilot-plugin",
        ]
    )
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@lru_cache(maxsize=64)
def load_agent_meta(agent_id: str, project_root: str | None = None) -> dict[str, Any]:
    """Return agent YAML meta for ``agent_id`` or {} if missing."""
    aid = (agent_id or "").strip()
    if not aid:
        return {}
    pr = Path(project_root).resolve() if project_root else None
    for root in _repo_root_candidates(pr):
        path = root / "agents" / f"{aid}.yaml"
        meta = _load_yaml(path)
        if meta.get("id"):
            return meta
        # Installed plugin may copy agents under bundle root
        path2 = root / "agents" / f"{aid}.yaml"
        meta2 = _load_yaml(path2)
        if meta2.get("id"):
            return meta2
    return {}


def agent_write_scopes(agent_id: str, project_root: Path | None = None) -> list[str]:
    """Return write scopes declared on the agent YAML."""
    meta = load_agent_meta(agent_id, str(project_root) if project_root else None)
    return [str(x) for x in (meta.get("write_scopes") or [])]


def agent_read_scopes(agent_id: str, project_root: Path | None = None) -> list[str]:
    meta = load_agent_meta(agent_id, str(project_root) if project_root else None)
    return [str(x) for x in (meta.get("read_scopes") or [])]


def agent_forbidden(agent_id: str, project_root: Path | None = None) -> list[str]:
    """Return forbidden tags declared on the agent YAML (may include unmapped tags)."""
    meta = load_agent_meta(agent_id, str(project_root) if project_root else None)
    return [str(x).strip() for x in (meta.get("forbidden") or []) if str(x).strip()]


def agent_machine_constraints(agent_id: str, project_root: Path | None = None) -> list[str]:
    """Tags that authorize / compose must enforce."""
    meta = load_agent_meta(agent_id, str(project_root) if project_root else None)
    tags = [str(x).strip() for x in (meta.get("machine_constraints") or []) if str(x).strip()]
    if not tags:
        tags = [t for t in agent_forbidden(agent_id, project_root) if t in KNOWN_FORBIDDEN_TAGS]
    return tags


def agent_behavioral_constraints(agent_id: str, project_root: Path | None = None) -> list[str]:
    meta = load_agent_meta(agent_id, str(project_root) if project_root else None)
    tags = [str(x).strip() for x in (meta.get("behavioral_constraints") or []) if str(x).strip()]
    if not tags:
        tags = [t for t in agent_forbidden(agent_id, project_root) if t in BEHAVIORAL_CONSTRAINT_TAGS]
    return tags


def unknown_forbidden_tags(agent_id: str, project_root: Path | None = None) -> list[str]:
    """Tags present in YAML but not in the harness mapping table."""
    known = KNOWN_FORBIDDEN_TAGS | BEHAVIORAL_CONSTRAINT_TAGS
    return [t for t in agent_forbidden(agent_id, project_root) if t not in known]


def forbidden_blocks_write(
    agent_id: str,
    rel_under_agent: str,
    *,
    project_root: Path | None = None,
) -> str | None:
    """Return a reason_code if a known forbidden tag blocks this write, else None."""
    tags = set(agent_forbidden(agent_id, project_root)) | set(
        agent_machine_constraints(agent_id, project_root)
    )
    if not tags:
        return None
    norm = rel_under_agent.replace("\\", "/").lstrip("/")
    if "modify_pilot_state" in tags:
        if norm == "state" or norm.startswith("state/"):
            return "FORBIDDEN_MODIFY_PILOT_STATE"
    if "modify_uo_product" in tags:
        if norm.endswith(".uo"):
            return "FORBIDDEN_MODIFY_UO_PRODUCT"
        if norm.startswith("uo/summary/") or norm.startswith("uo/checks/"):
            return "FORBIDDEN_MODIFY_UO_PRODUCT"
    return None


def forbidden_blocks_bash(
    agent_id: str,
    command: str,
    *,
    project_root: Path | None = None,
) -> str | None:
    """Return reason_code if bash is blocked by a known forbidden tag."""
    tags = set(agent_forbidden(agent_id, project_root)) | set(
        agent_machine_constraints(agent_id, project_root)
    )
    if "declare_workflow_passed" not in tags:
        return None
    cmd = (command or "").strip().lower()
    if not cmd:
        return None
    # acp complete / declare passed — soft control-plane pass declaration
    if "acp" in cmd and (
        " complete" in f" {cmd}"
        or "complete " in cmd
        or "declare" in cmd and "pass" in cmd
        or "--passed" in cmd
        or " status=passed" in cmd
        or "passed" in cmd and "workflow" in cmd
    ):
        return "FORBIDDEN_DECLARE_WORKFLOW_PASSED"
    return None


def split_scope_ns(scope: str) -> tuple[str, str]:
    """Split ``pilot:uo/**`` / ``method:…`` / ``source:…``; bare scopes → pilot."""
    s = str(scope or "").replace("\\", "/").strip()
    for ns in ("pilot:", "method:", "source:"):
        if s.lower().startswith(ns):
            return ns[:-1], s[len(ns) :].lstrip("/")
    # Legacy: skills/** and cognitive-skills/** are method roots.
    if s.startswith("skills/") or s.startswith("cognitive-skills/"):
        return "method", s
    # Legacy: op_host / op_kernel style roots are source.
    if s.split("/", 1)[0] in {
        "op_host",
        "op_kernel",
        "common",
        "op_graph",
        "framework",
        "include",
    }:
        return "source", s
    return "pilot", s.lstrip("/")


def path_matches_scope(rel_under_agent: str, scopes: list[str]) -> bool:
    """Match a path relative to ``.ascendc-pilot/`` against glob-like scopes.

    Supports ``**``, ``*``, and exact prefixes. Empty scopes → deny (caller decides).
    Namespace prefixes ``pilot:`` / ``method:`` / ``source:`` are stripped here;
    callers that need cross-root matching should use ``scope_allows_path``.
    """
    from fnmatch import fnmatch

    norm = rel_under_agent.replace("\\", "/").lstrip("/")
    if not scopes:
        return False
    for scope in scopes:
        ns, s = split_scope_ns(str(scope))
        if ns != "pilot":
            # Non-pilot scopes are handled by scope_allows_path.
            continue
        if not s:
            continue
        if s.endswith("/**"):
            prefix = s[:-3]
            if norm == prefix or norm.startswith(prefix + "/"):
                return True
            # also allow exact file under prefix via fnmatch
        if fnmatch(norm, s):
            return True
        # Directory scope without glob: treat as prefix
        if "*" not in s and "?" not in s and "[" not in s:
            if norm == s or norm.startswith(s.rstrip("/") + "/"):
                return True
        # Backward-compat: bare skills/** also matched as pilot-relative historically
        # (usually dead); keep fnmatch for unprefixed legacy identical to pilot.
    return False


def scope_allows_path(
    abs_path: str | Path,
    scopes: list[str],
    *,
    project_root: Path | None,
) -> bool:
    """True if abs_path is allowed by any namespaced scope."""
    from fnmatch import fnmatch

    try:
        resolved = Path(abs_path).expanduser().resolve()
    except OSError:
        return False
    if not scopes:
        return False

    method_roots = _method_roots(project_root)
    for scope in scopes:
        ns, pattern = split_scope_ns(str(scope))
        if not pattern:
            continue
        if ns == "pilot":
            rel = rel_under_agent_dir(resolved, project_root)
            if rel is None:
                continue
            if path_matches_scope(rel, [f"pilot:{pattern}", pattern]):
                return True
            continue
        if ns == "source":
            if project_root is None:
                continue
            try:
                rel = resolved.relative_to(Path(project_root).resolve()).as_posix()
            except ValueError:
                continue
            if pattern.endswith("/**"):
                prefix = pattern[:-3]
                if rel == prefix or rel.startswith(prefix + "/"):
                    return True
            if fnmatch(rel, pattern) or rel == pattern or rel.startswith(pattern.rstrip("/") + "/"):
                return True
            continue
        if ns == "method":
            for root in method_roots:
                try:
                    rel = resolved.relative_to(root.resolve()).as_posix()
                except ValueError:
                    continue
                # pattern may be skills/foo/** or cognitive-skills/foo/** or foo/**
                candidates = [pattern]
                if pattern.startswith("skills/"):
                    candidates.append("cognitive-" + pattern)
                    candidates.append(pattern[len("skills/") :])
                if pattern.startswith("cognitive-skills/"):
                    candidates.append(pattern[len("cognitive-skills/") :])
                    candidates.append("skills/" + pattern[len("cognitive-skills/") :])
                for cand in candidates:
                    if cand.endswith("/**"):
                        prefix = cand[:-3]
                        if rel == prefix or rel.startswith(prefix + "/"):
                            return True
                    if fnmatch(rel, cand) or rel == cand or rel.startswith(cand.rstrip("/") + "/"):
                        return True
    return False


def _method_roots(project_root: Path | None) -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    roots.extend(
        [
            home / ".config" / "opencode" / "ascendc-pilot-plugin",
            home / ".config" / "opencode",
            home / ".cursor" / "ascendc-pilot-plugin",
            home / ".agents" / "ascendc-pilot-plugin",
        ]
    )
    for root in _repo_root_candidates(project_root):
        roots.append(root)
        roots.append(root / "skills")
    # Dedup
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def rel_under_agent_dir(path: str | Path, project_root: Path | None) -> str | None:
    """Return path relative to the arch-scoped agent root (``uo/…``, ``tg/…``).

    After W0, durable products live under ``.ascendc-pilot/<arch>/``. Write
    scopes are still declared without the arch segment (``uo/**``), so this
    helper strips the architecture directory when present.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return None

    if project_root is not None:
        try:
            from ascendc_pilot.paths import agent_root

            return resolved.relative_to(agent_root(project_root)).as_posix()
        except ValueError:
            pass

    norm = str(resolved).replace("\\", "/")
    marker = "/.ascendc-pilot/"
    if marker not in norm:
        if norm.rstrip("/").endswith("/.ascendc-pilot"):
            return ""
        return None
    rel = norm.split(marker, 1)[1]
    parts = rel.split("/")
    roots = {"uo", "tg", "ce", "runs", "state", "context", "memory"}
    if len(parts) >= 2 and parts[0] not in roots and parts[1] in roots:
        return "/".join(parts[1:])
    return rel
