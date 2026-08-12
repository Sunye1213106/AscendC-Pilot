"""Context Compiler — compile a ContextProfile into a minimal action slice.

Uses UoQuery (via open_query) to gather a bounded graph neighborhood plus
domain references and optional prior-failure receipts. Never loads the full KB.
The profile token budget is enforced across the final model-facing bundle, not
only across graph rows.
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


def _model_payload(slice_doc: dict[str, Any]) -> dict[str, Any]:
    """Fields that are actually useful to the actor and count against budget."""
    return {
        "task": slice_doc.get("task"),
        "graph_slice": slice_doc.get("graph_slice"),
        "evidence": slice_doc.get("evidence"),
        "references": slice_doc.get("references"),
        "prior_failure": slice_doc.get("prior_failure"),
        "excluded": slice_doc.get("excluded"),
        "query_errors": slice_doc.get("query_errors"),
    }


def _fit_slice_doc_to_budget(slice_doc: dict[str, Any], budget: int) -> list[str]:
    """Mutate optional payload until the final model-facing bundle fits.

    Priority is deliberate:
    1. Keep task/evidence routing metadata.
    2. Trim long reference bodies before dropping graph evidence.
    3. Trim graph rows from the largest slice.
    4. Drop prior-failure context last.

    Returns human-readable trim receipts. Core routing metadata is never silently
    removed; if it alone exceeds the budget, ``budget_core_overflow`` is emitted.
    """
    receipts: list[str] = []
    budget = max(256, int(budget))

    def current() -> int:
        return _estimate_tokens(_model_payload(slice_doc))

    references = slice_doc.get("references")
    if not isinstance(references, list):
        references = []
        slice_doc["references"] = references

    # First progressively shrink reference text while retaining paths/status.
    while current() > budget:
        candidates = [
            (idx, ref)
            for idx, ref in enumerate(references)
            if isinstance(ref, dict) and len(str(ref.get("text") or "")) > 400
        ]
        if not candidates:
            break
        idx, ref = max(candidates, key=lambda item: len(str(item[1].get("text") or "")))
        text = str(ref.get("text") or "")
        new_len = max(400, len(text) // 2)
        ref["text"] = text[:new_len] + "\n…(budget-truncated)…"
        receipts.append(f"reference_truncated:{idx}:{len(text)}->{new_len}")

    # Then remove optional reference bodies entirely, preserving metadata.
    while current() > budget:
        candidates = [
            (idx, ref)
            for idx, ref in enumerate(references)
            if isinstance(ref, dict) and ref.get("text")
        ]
        if not candidates:
            break
        idx, ref = candidates[-1]
        ref.pop("text", None)
        ref["status"] = "budget_omitted"
        receipts.append(f"reference_body_omitted:{idx}")

    # Graph is evidence-rich, so only trim rows after references are exhausted.
    graph = slice_doc.get("graph_slice")
    if not isinstance(graph, list):
        graph = []
        slice_doc["graph_slice"] = graph
    while current() > budget:
        row_lists: list[tuple[int, list[Any]]] = []
        for idx, part in enumerate(graph):
            if isinstance(part, dict) and isinstance(part.get("rows"), list) and part["rows"]:
                row_lists.append((idx, part["rows"]))
        if not row_lists:
            break
        idx, rows = max(row_lists, key=lambda item: _estimate_tokens(item[1]))
        removed = rows.pop()
        receipts.append(f"graph_row_omitted:{idx}:{_estimate_tokens(removed)}")

    # Evidence seed lists are routing hints, not authoritative facts; compact them
    # before discarding prior-failure information.
    evidence = slice_doc.get("evidence")
    if isinstance(evidence, list):
        while current() > budget:
            changed = False
            for item in reversed(evidence):
                if isinstance(item, dict) and isinstance(item.get("seeds"), list) and len(item["seeds"]) > 1:
                    item["seeds"].pop()
                    changed = True
                    receipts.append("evidence_seed_omitted")
                    break
            if not changed:
                break

    if current() > budget and slice_doc.get("prior_failure") is not None:
        slice_doc["prior_failure"] = None
        receipts.append("prior_failure_omitted")

    # Query errors can include long exception strings; preserve the fact that an
    # error occurred while bounding its diagnostic payload.
    errors = slice_doc.get("query_errors")
    if isinstance(errors, list) and current() > budget:
        slice_doc["query_errors"] = [str(e)[:160] for e in errors[:4]]
        receipts.append("query_errors_compacted")

    if current() > budget:
        receipts.append(f"budget_core_overflow:{current()}>{budget}")
    return receipts


def _repo_root_from_project(project_root: Path) -> Path:
    # project_root is the operator dir; AscendC-Pilot repo is a sibling or cwd.
    # Prefer env/cwd discovery: walk up for skills/ + pilot/ (or cognitive-skills/).
    def _looks_like_repo(base: Path) -> bool:
        skills = base / "skills"
        cog = base / "cognitive-skills"
        if not (base / "pilot").is_dir():
            # Installed plugin bundle: cognitive-skills without pilot/
            if cog.is_dir() and any(
                (cog / name).is_dir()
                for name in (
                    "operator-analysis",
                    "testcase-generation",
                    "source-proof",
                    "code-review",
                )
            ):
                return True
            return False
        if skills.is_dir() and any(
            (skills / name).is_dir()
            for name in (
                "operator-analysis",
                "testcase-generation",
                "source-proof",
                "code-review",
                "domain",
            )
        ):
            return True
        if cog.is_dir():
            return True
        return False

    cur = Path(project_root).expanduser().resolve()
    for base in [cur, *cur.parents]:
        if _looks_like_repo(base):
            return base
    # Installed OpenCode plugin tree
    home_plug = Path.home() / ".config" / "opencode" / "ascendc-pilot-plugin"
    if _looks_like_repo(home_plug):
        return home_plug
    cwd = Path.cwd().resolve()
    if _looks_like_repo(cwd):
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
    """Load profile references. Missing paths are marked ``status: missing``;

    callers must fail-closed (``BUNDLE_NOT_READABLE`` / prepare abort) — do not
    silently degrade for the model.
    """
    out: list[dict[str, str]] = []
    for rel in refs:
        path = repo / rel
        if not path.is_file():
            # OpenCode installs cognitive skills under cognitive-skills/.
            alt = rel
            if rel.startswith("skills/"):
                alt = "cognitive-" + rel
            alt_path = repo / alt
            home_alt = (
                Path.home()
                / ".config"
                / "opencode"
                / "ascendc-pilot-plugin"
                / alt
            )
            if alt_path.is_file():
                path = alt_path
                rel = alt
            elif home_alt.is_file():
                path = home_alt
                rel = alt
            else:
                out.append({"path": rel, "status": "missing"})
                continue
        text = path.read_text(encoding="utf-8")
        # Per-reference cap prevents one document from dominating before the
        # final bundle-level budget pass.
        max_chars = 3200
        out.append(
            {
                "path": rel,
                "status": "ok",
                "text": text[:max_chars] + ("\n…(truncated)…" if len(text) > max_chars else ""),
            }
        )
    return out


def missing_reference_paths(references: list[dict[str, str]] | None) -> list[str]:
    """Paths recorded as missing by ``_load_references``."""
    out: list[str] = []
    for row in references or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") == "missing":
            p = str(row.get("path") or "").strip()
            if p:
                out.append(p)
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
    loaded_state = load_state(project_root)
    state = loaded_state if isinstance(loaded_state, dict) else {}
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
                    if k not in {"expr", "data", "values_json"} or _estimate_tokens(v) < 200
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
    missing_refs = missing_reference_paths(references)
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
        # Fail-closed: missing references must not silently degrade the agent.
        "ok": not missing_refs,
        "missing_references": missing_refs,
    }
    if missing_refs:
        slice_doc["error"] = "BUNDLE_NOT_READABLE"
        slice_doc["reason_code"] = "CONTEXT_REFERENCES_MISSING"
        slice_doc["message_zh"] = (
            "Context profile 引用的 references 缺失："
            + ", ".join(missing_refs[:8])
            + "；禁止派发（禁止静默 missing 降级）。"
        )
    trim_receipts = _fit_slice_doc_to_budget(slice_doc, profile.token_budget)
    slice_doc["budget_receipts"] = trim_receipts
    slice_doc["token_estimate"] = _estimate_tokens(_model_payload(slice_doc))
    slice_doc["budget_ok"] = slice_doc["token_estimate"] <= profile.token_budget

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


__all__ = [
    "compile_context_slice",
    "maybe_compile_slice",
    "get_profile",
    "ContextProfile",
    "missing_reference_paths",
]
