"""Context Compiler — compile a ContextProfile into a minimal action slice.

Uses UoQuery (via open_query) to gather a bounded graph neighborhood plus
domain references and optional prior-failure receipts. Never loads the full KB.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.context.profiles import ContextProfile, QuerySlice, get_profile
from ascendc_pilot.paths import context_root, ensure_agent_layout, tg_root, uo_root
from ascendc_pilot.state import load_state


def _load_yaml(path: Path) -> Any:
    if yaml is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _estimate_tokens(obj: Any) -> int:
    """Rough token estimate (~ chars/4) for budgeting."""
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except TypeError:
        text = str(obj)
    return max(1, len(text) // 4)


def _truncate_to_budget(items: list[Any], budget: int) -> list[Any]:
    out: list[Any] = []
    used = 0
    for item in items:
        cost = _estimate_tokens(item)
        if out and used + cost > budget:
            break
        out.append(item)
        used += cost
    return out


def _repo_root_from_project(project_root: Path) -> Path:
    # project_root is the operator dir; AscendC-Pilot repo is a sibling or cwd.
    # Prefer env/cwd discovery: walk up for skills/domain.
    cur = Path(project_root).expanduser().resolve()
    for base in [cur, *cur.parents]:
        if (base / "skills" / "domain").is_dir() and (base / "pilot").is_dir():
            return base
    # Fall back: assume installed next to operators, or cwd.
    cwd = Path.cwd().resolve()
    if (cwd / "skills" / "domain").is_dir():
        return cwd
    return cur


def _seed_ids(
    project_root: Path,
    seed_from: str,
    *,
    limit: int,
) -> list[str]:
    uo = uo_root(project_root)
    tg = tg_root(project_root)
    seeds: list[str] = []

    if seed_from == "unresolved_blockers":
        data = _load_yaml(uo / "ir" / "unresolved.yaml") or {}
        blockers = []
        if isinstance(data, dict):
            blockers = list(data.get("blockers") or data.get("items") or [])
            if not blockers and isinstance(data.get("unresolved"), list):
                blockers = list(data["unresolved"])
        for row in blockers:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("id") or row.get("blocker_id") or "").strip()
            if bid:
                seeds.append(bid)
            # Also pull related entity / node ids when present.
            for key in ("entity_id", "node_id", "owner_id", "var", "name"):
                v = str(row.get(key) or "").strip()
                if v and v not in seeds:
                    seeds.append(v)

    elif seed_from == "lemma_leads":
        data = _load_yaml(tg / "closure" / "lemmas" / "leads.yaml") or {}
        leads = []
        if isinstance(data, dict):
            leads = list(data.get("leads") or data.get("items") or [])
        for row in leads:
            if isinstance(row, dict):
                for key in ("key", "key_id", "dim", "id", "target"):
                    v = str(row.get(key) or "").strip()
                    if v and v not in seeds:
                        seeds.append(v)
            elif row:
                seeds.append(str(row))

    elif seed_from == "open_keys":
        open_path = tg / "closure" / "open.txt"
        if open_path.is_file():
            for line in open_path.read_text(encoding="utf-8").splitlines():
                key = line.strip().split(",")[0].strip()
                if key and not key.startswith("#"):
                    seeds.append(key)

    elif seed_from == "impact_files":
        impact = _load_yaml(project_root / ".ascendc-pilot" / "ce" / "impact.json")
        if impact is None:
            # also under arch-scoped ce root if present
            from ascendc_pilot.paths import agent_root

            impact = _load_yaml(agent_root(project_root) / "ce" / "impact.json")
        if isinstance(impact, dict):
            files = list(impact.get("files") or impact.get("changed_files") or [])
            for f in files:
                if isinstance(f, dict):
                    p = str(f.get("path") or f.get("file") or "").strip()
                else:
                    p = str(f).strip()
                if p:
                    seeds.append(p)
            for key in impact.get("affected_keys") or []:
                seeds.append(str(key))

    return seeds[: max(1, limit)]


def _run_query(
    q: Any,
    slice_spec: QuerySlice,
    seeds: list[str],
) -> list[dict[str, Any]]:
    method = slice_spec.method
    limit = slice_spec.limit
    rows: list[dict[str, Any]] = []

    if not hasattr(q, method):
        return [{"error": f"query_method_missing:{method}"}]

    fn = getattr(q, method)

    if method == "entities_in_files":
        try:
            rows = list(fn(seeds[:limit]) or [])
        except Exception as exc:  # noqa: BLE001 — slice must never break prepare
            return [{"error": f"{method}:{exc}"}]
        return rows[:limit]

    if method == "impact_of":
        for seed in seeds[:limit]:
            # seed may be "file:start-end" or plain path
            file_path = seed
            line_range = (1, 1)
            if ":" in seed and seed.rsplit(":", 1)[-1].replace("-", "").isdigit():
                file_path, rng = seed.rsplit(":", 1)
                if "-" in rng:
                    a, b = rng.split("-", 1)
                    try:
                        line_range = (int(a), int(b))
                    except ValueError:
                        line_range = (1, 1)
            try:
                part = list(fn(file_path, line_range) or [])
                rows.extend(part)
            except TypeError:
                try:
                    part = list(fn(file_path) or [])
                    rows.extend(part)
                except Exception as exc:  # noqa: BLE001
                    rows.append({"error": f"{method}:{exc}", "seed": seed})
            except Exception as exc:  # noqa: BLE001
                rows.append({"error": f"{method}:{exc}", "seed": seed})
        return rows[:limit]

    if method == "search":
        for seed in seeds[:limit]:
            try:
                part = list(fn(seed, limit=min(8, limit)) or [])
            except TypeError:
                try:
                    part = list(fn(seed) or [])
                except Exception as exc:  # noqa: BLE001
                    rows.append({"error": f"{method}:{exc}", "seed": seed})
                    continue
            except Exception as exc:  # noqa: BLE001
                rows.append({"error": f"{method}:{exc}", "seed": seed})
                continue
            for item in part:
                if isinstance(item, dict):
                    item = {**item, "_seed": seed}
                rows.append(item)
        return rows[:limit]

    # Generic per-seed methods: neighbors, constraints_for, branches_for_key, ...
    for seed in seeds[:limit]:
        try:
            part = fn(seed, **(slice_spec.kwargs or {}))
            if part is None:
                continue
            if isinstance(part, dict):
                rows.append({**part, "_seed": seed})
            else:
                for item in list(part)[: max(1, limit // max(1, len(seeds)))]:
                    if isinstance(item, dict):
                        rows.append({**item, "_seed": seed})
                    else:
                        rows.append({"value": item, "_seed": seed})
        except TypeError:
            try:
                part = fn(seed)
                if isinstance(part, dict):
                    rows.append({**part, "_seed": seed})
                else:
                    for item in list(part or [])[:8]:
                        if isinstance(item, dict):
                            rows.append({**item, "_seed": seed})
                        else:
                            rows.append({"value": item, "_seed": seed})
            except Exception as exc:  # noqa: BLE001
                rows.append({"error": f"{method}:{exc}", "seed": seed})
        except Exception as exc:  # noqa: BLE001
            rows.append({"error": f"{method}:{exc}", "seed": seed})
    return rows[:limit]


def _load_references(repo: Path, refs: tuple[str, ...]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for rel in refs:
        path = repo / rel
        if not path.is_file():
            out.append({"path": rel, "status": "missing"})
            continue
        text = path.read_text(encoding="utf-8")
        # Cap each reference to ~800 tokens of content.
        max_chars = 3200
        out.append(
            {
                "path": rel,
                "status": "ok",
                "text": text[:max_chars] + ("\n…(truncated)…" if len(text) > max_chars else ""),
            }
        )
    return out


def _prior_failure(project_root: Path, action_id: str) -> dict[str, Any] | None:
    state = load_state(project_root)
    if not isinstance(state, dict):
        return None
    last = state.get("last_failure")
    if isinstance(last, dict) and last:
        # Prefer failures related to this action when tagged.
        if last.get("action_id") and str(last.get("action_id")) != action_id:
            # Still useful as prior context; keep compact.
            return {
                "action_id": last.get("action_id"),
                "error": last.get("error") or last.get("message") or last.get("reason"),
                "gate": last.get("gate"),
                "note": "prior_failure_other_action",
            }
        return {
            "action_id": last.get("action_id") or action_id,
            "error": last.get("error") or last.get("message") or last.get("reason"),
            "gate": last.get("gate"),
            "failed_gates": list(state.get("failed_gates") or [])[:8],
        }
    return None


def compile_context_slice(
    project_root: Path,
    *,
    profile_id: str | None,
    action_id: str = "",
    workflow_id: str = "",
    intent: str = "",
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Compile a context slice for ``profile_id``.

    Returns ``None`` when no profile is registered (caller must keep legacy pack).
    Always writes the slice file when a profile exists, even if the .uo KB is missing
    (graph_slice then carries an error stub).
    """
    profile = get_profile(profile_id)
    if profile is None:
        return None

    ensure_agent_layout(project_root)
    repo = Path(repo_root).resolve() if repo_root else _repo_root_from_project(project_root)
    state = load_state(project_root) if isinstance(load_state(project_root), dict) else {}
    task = {
        "action_id": action_id,
        "workflow_id": workflow_id or state.get("workflow_id"),
        "profile_id": profile.id,
        "intent": intent or f"run-action:{action_id}",
        "description": profile.description,
    }

    graph_slice: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    query_errors: list[str] = []

    try:
        from uo_init.uo_query import open_query  # type: ignore

        q = open_query(uo_root(project_root))
    except Exception as exc:  # noqa: BLE001
        q = None
        query_errors.append(f"open_query:{exc}")

    if q is not None:
        for qs in profile.query_slices:
            seeds = _seed_ids(project_root, qs.seed_from, limit=qs.limit)
            evidence.append(
                {
                    "seed_from": qs.seed_from,
                    "seed_count": len(seeds),
                    "seeds": seeds[: qs.limit],
                    "method": qs.method,
                }
            )
            rows = _run_query(q, qs, seeds)
            # Drop bulky fields that blow the budget.
            compact: list[Any] = []
            for row in rows:
                if not isinstance(row, dict):
                    compact.append(row)
                    continue
                cleaned = {
                    k: v
                    for k, v in row.items()
                    if k not in {"smt", "data", "values_json"} or _estimate_tokens(v) < 200
                }
                compact.append(cleaned)
            graph_slice.append(
                {
                    "method": qs.method,
                    "seed_from": qs.seed_from,
                    "rows": _truncate_to_budget(compact, profile.token_budget // max(1, len(profile.query_slices))),
                }
            )

    references = _load_references(repo, profile.references)
    prior = _prior_failure(project_root, action_id) if profile.include_prior_failure else None

    slice_doc: dict[str, Any] = {
        "version": 1,
        "built_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task": task,
        "graph_slice": graph_slice,
        "evidence": evidence,
        "references": references,
        "prior_failure": prior,
        "excluded": list(profile.excluded),
        "query_errors": query_errors,
        "token_budget": profile.token_budget,
    }
    slice_doc["token_estimate"] = _estimate_tokens(
        {
            "task": task,
            "graph_slice": graph_slice,
            "references": [{"path": r.get("path"), "n": len(r.get("text") or "")} for r in references],
            "prior_failure": prior,
        }
    )

    out_dir = context_root(project_root) / "slices"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = (action_id or profile.id).replace("/", "-")
    out_path = out_dir / f"{out_name}.yaml"
    if yaml is not None:
        out_path.write_text(
            yaml.safe_dump(slice_doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    slice_doc["path"] = out_path.as_posix()
    slice_doc["profile_id"] = profile.id
    return slice_doc


def maybe_compile_slice(
    project_root: Path,
    *,
    context_profile_id: str | None,
    action_id: str = "",
    workflow_id: str = "",
    intent: str = "",
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Public entry: compile when profile exists, else return None (legacy pack only)."""
    return compile_context_slice(
        project_root,
        profile_id=context_profile_id,
        action_id=action_id,
        workflow_id=workflow_id,
        intent=intent,
        repo_root=repo_root,
    )


__all__ = ["compile_context_slice", "maybe_compile_slice", "get_profile", "ContextProfile"]
