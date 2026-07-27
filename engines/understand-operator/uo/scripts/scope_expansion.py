"""Controlled scope expansion: LLM proposes, deterministic audit applies."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.source_path_resolve import resolve_scoped_source_path

MAX_SCOPE_EXPANSION_ROUNDS = 3
MAX_FILES_PER_ROUND = 8
MAX_TOTAL_EXPANDED_FILES = 32

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*(["<])([^">]+)[">]', re.MULTILINE)


def _fp(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def load_requests(uo_root: Path) -> dict[str, Any]:
    return read_yaml(uo_root / "ir" / "scope_expansion_requests.yaml") or {"version": 1, "requests": []}


def _latest_scope_confirmed(uo_root: Path) -> tuple[Path | None, dict[str, Any]]:
    runs = sorted((uo_root / "runs").glob("*/scope/scope_confirmed.yaml"), reverse=True)
    if not runs:
        return None, {}
    return runs[0], read_yaml(runs[0]) or {}


def _confirmed_rels(scope: dict[str, Any]) -> list[str]:
    files = list(scope.get("confirmed_source_files") or scope.get("confirmed_file_list") or [])
    out: list[str] = []
    for item in files:
        rel = str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/")
        if rel:
            out.append(rel)
    return out


def _is_reachable_from_scope(
    project_root: Path,
    candidate_rel: str,
    candidate_path: Path,
    *,
    confirmed_rels: list[str],
    request: dict[str, Any],
    architecture: str,
) -> tuple[bool, str]:
    """Require include edge from confirmed scope OR explicit symbol evidence window."""
    # Explicit evidence from LLM request (symbol window must name this file).
    for win in request.get("evidence_windows") or request.get("symbol_evidence") or []:
        if not isinstance(win, dict):
            continue
        wpath = str(win.get("file") or win.get("path") or "").replace("\\", "/")
        if wpath and (wpath == candidate_rel or wpath.endswith("/" + candidate_rel.split("/")[-1])):
            if win.get("symbol") or win.get("snippet") or win.get("lines"):
                return True, "symbol_evidence"

    # Include reachability: any confirmed file #includes this candidate.
    cand_name = Path(candidate_rel).name
    cand_posix = candidate_rel.replace("\\", "/")
    for crel in confirmed_rels:
        src = project_root / crel
        if not src.is_file():
            # try under parent/common via resolve
            resolved = resolve_scoped_source_path(
                project_root, crel, request.get("op_name") or "", architecture=architecture
            )
            if resolved.get("ok"):
                src = Path(resolved["path"])
            else:
                continue
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _INCLUDE_RE.finditer(text):
            inc = m.group(2).replace("\\", "/")
            if inc == cand_posix or inc.endswith("/" + cand_name) or Path(inc).name == cand_name:
                # Prefer path that resolves to candidate_path
                try:
                    if (src.parent / inc).resolve() == candidate_path.resolve():
                        return True, "include_edge"
                except OSError:
                    pass
                if Path(inc).name == cand_name:
                    return True, "include_edge_name"

    # Also: candidate includes a confirmed file? Not sufficient alone for "from scope".
    # Use include closure one-hop from confirmed seeds if available.
    try:
        from uo.scripts.source_include_closure import expand_local_include_closure

        seeds = []
        for crel in confirmed_rels[:64]:
            p = project_root / crel
            if p.is_file():
                seeds.append(p)
        if seeds:
            closure = expand_local_include_closure(
                project_root, seeds, architecture=architecture, max_depth=8, max_files=256
            )
            for f in closure.files:
                if f.resolve() == candidate_path.resolve():
                    return True, "include_closure"
    except Exception:  # noqa: BLE001
        pass

    return False, "not_reachable"


def audit_scope_expansion_request(
    project_root: Path,
    op_name: str,
    request: dict[str, Any],
    *,
    architecture: str = "arch35",
    already_expanded: set[str] | None = None,
    confirmed_rels: list[str] | None = None,
    uo_root: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Deterministic audit: existence, allowed roots, reachability, budget."""
    already = already_expanded or set()
    proposed = list(request.get("proposed_files") or [])
    req = dict(request)
    req["op_name"] = op_name
    if confirmed_rels is None and uo_root is not None:
        _, scope = _latest_scope_confirmed(uo_root)
        confirmed_rels = _confirmed_rels(scope)
    confirmed_rels = list(confirmed_rels or [])

    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    for item in proposed:
        rel = str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/")
        if not rel:
            continue
        if rel in already:
            rejected.append({"path": rel, "reason": "duplicate"})
            continue
        if ".." in Path(rel).parts:
            rejected.append({"path": rel, "reason": "path_traversal"})
            continue
        if "/arch" in rel and architecture and f"/{architecture}/" not in rel and "common/" not in rel:
            if any(f"/arch{i}/" in rel for i in ("22", "25", "30", "32") if f"arch{i}" != architecture):
                rejected.append({"path": rel, "reason": "other_architecture"})
                continue
        resolved = resolve_scoped_source_path(
            project_root,
            rel,
            op_name,
            architecture=architecture,
            repository_root=repository_root,
            uo_root=uo_root,
        )
        if not resolved.get("ok"):
            rejected.append({"path": rel, "reason": "not_found"})
            continue
        posix = str(resolved.get("rel") or rel)
        if not any(m in posix for m in ("op_host/", "op_kernel/", "op_api/", "common/", "op_graph/")):
            rejected.append({"path": rel, "reason": "outside_allowed_roots"})
            continue
        # Sibling operator guard: resolved path must not escape operator/common roots
        # (already enforced in resolve_scoped_source_path allowed_roots).
        ok_reach, reach_reason = _is_reachable_from_scope(
            project_root,
            posix,
            Path(resolved["path"]),
            confirmed_rels=confirmed_rels,
            request=req,
            architecture=architecture,
        )
        if not ok_reach:
            rejected.append({"path": rel, "reason": reach_reason or "not_reachable"})
            continue
        accepted.append(posix)
        if len(accepted) >= MAX_FILES_PER_ROUND:
            break
    return {
        "ok": bool(accepted),
        "accepted_files": accepted,
        "rejected_files": rejected,
        "request_fingerprint": _fp(
            {
                "missing_symbol": request.get("missing_symbol"),
                "proposed": [str(i.get("path") if isinstance(i, dict) else i) for i in proposed],
            }
        ),
    }


def apply_scope_expansion(
    project_root: Path,
    op_name: str,
    *,
    uo_root: Path,
    architecture: str = "arch35",
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Audit pending requests, update scope, refresh closure/snapshot/CBM stage."""
    req_doc = load_requests(uo_root)
    requests = [
        r
        for r in (req_doc.get("requests") or [])
        if isinstance(r, dict) and str(r.get("status") or "") not in {"consumed", "applied"}
    ]
    receipt_prev = read_yaml(uo_root / "ir" / "scope_expansion_receipt.yaml") or {}
    rounds = int(receipt_prev.get("rounds") or 0)
    expanded_total = list(receipt_prev.get("expanded_files") or [])
    prev_fps = set(receipt_prev.get("previous_request_fingerprints") or [])

    if not requests:
        return {
            "ok": True,
            "status": "no_pending_requests",
            "rounds": rounds,
            "new_files": [],
            "scope_updated": False,
            "next_actions": [],
        }

    if rounds >= MAX_SCOPE_EXPANSION_ROUNDS:
        return {
            "ok": False,
            "error": "SCOPE_EXPANSION_BUDGET_EXCEEDED",
            "rounds": rounds,
            "status": "human_required",
        }

    scope_path, scope = _latest_scope_confirmed(uo_root)
    confirmed_rels = _confirmed_rels(scope)
    snapshot_before = _fp({"files": confirmed_rels})

    decisions: list[dict[str, Any]] = []
    newly: list[str] = []
    for req in requests:
        audit = audit_scope_expansion_request(
            project_root,
            op_name,
            req,
            architecture=architecture,
            already_expanded=set(expanded_total) | set(newly),
            confirmed_rels=confirmed_rels + newly,
            uo_root=uo_root,
            repository_root=repository_root,
        )
        fp = str(audit.get("request_fingerprint") or "")
        if fp and fp in prev_fps and not audit.get("accepted_files"):
            decisions.append({**audit, "task_id": req.get("task_id"), "status": "no_progress"})
            continue
        decisions.append(
            {**audit, "task_id": req.get("task_id"), "status": "accepted" if audit.get("ok") else "rejected"}
        )
        newly.extend(list(audit.get("accepted_files") or []))
        if fp:
            prev_fps.add(fp)
        req["status"] = "consumed" if audit.get("ok") else "rejected"

    if len(expanded_total) + len(newly) > MAX_TOTAL_EXPANDED_FILES:
        newly = newly[: max(0, MAX_TOTAL_EXPANDED_FILES - len(expanded_total))]

    scope_updated = False
    snapshot_after = snapshot_before
    if newly and scope_path is not None:
        files = list(scope.get("confirmed_source_files") or scope.get("confirmed_file_list") or [])
        existing = {
            str(i.get("path") if isinstance(i, dict) else i).replace("\\", "/") for i in files
        }
        for rel in newly:
            if rel not in existing:
                files.append({"path": rel, "source": "scope_expansion"})
                existing.add(rel)
        scope["confirmed_source_files"] = files
        scope["scope_revision"] = int(scope.get("scope_revision") or 0) + 1
        write_yaml(scope_path, scope)
        scope_updated = True
        snapshot_after = _fp({"files": _confirmed_rels(scope), "revision": scope.get("scope_revision")})
        # Persist snapshot stamp so old source_snapshot_hash becomes stale.
        write_yaml(
            scope_path.parent / "scope_snapshot.yaml",
            {
                "version": 1,
                "source_snapshot_hash": snapshot_after,
                "previous_source_snapshot_hash": snapshot_before,
                "file_count": len(_confirmed_rels(scope)),
                "expanded_files": newly,
            },
        )

    # Include closure refresh (best-effort, repository-local).
    closure_info: dict[str, Any] = {}
    if newly and scope_path is not None:
        try:
            from uo.scripts.source_include_closure import expand_local_include_closure

            seeds = []
            for crel in _confirmed_rels(scope):
                p = Path(project_root) / crel
                if p.is_file():
                    seeds.append(p)
            closure = expand_local_include_closure(
                Path(project_root), seeds, architecture=architecture, max_depth=16, max_files=512
            )
            closure_info = closure.as_dict(Path(project_root))
            write_yaml(uo_root / "ir" / "scope_include_closure.yaml", {"version": 1, **closure_info})
        except Exception as exc:  # noqa: BLE001
            closure_info = {"error": str(exc)[:200]}

    # CBM stage / index_meta refresh
    cbm_info: dict[str, Any] = {}
    if newly:
        try:
            from uo.scripts.stage_cbm_scope import stage_cbm_scope

            cbm_info = stage_cbm_scope(Path(project_root), op_name)
            meta_path = uo_root / "cbm" / "index_meta.json"
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta = {
                "version": 1,
                "status": "staged",
                "source_snapshot_hash": snapshot_after,
                "expanded_files": newly,
                "stage": cbm_info if isinstance(cbm_info, dict) else {"ok": True},
            }
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            cbm_info = meta
        except Exception as exc:  # noqa: BLE001
            cbm_info = {"ok": False, "error": str(exc)[:300]}

    # Clear pending flags on llm_tasks for consumed scope requests
    try:
        tasks_doc = read_yaml(uo_root / "ir" / "llm_tasks.yaml") or {}
        changed = False
        consumed_ids = {str(d.get("task_id") or "") for d in decisions if d.get("status") == "accepted"}
        for task in tasks_doc.get("tasks") or []:
            if isinstance(task, dict) and str(task.get("task_id") or "") in consumed_ids:
                task["pending_scope_expansion"] = False
                changed = True
        if changed:
            write_yaml(uo_root / "ir" / "llm_tasks.yaml", tasks_doc)
    except Exception:  # noqa: BLE001
        pass

    # Persist consumed request statuses
    write_yaml(uo_root / "ir" / "scope_expansion_requests.yaml", req_doc)
    write_yaml(uo_root / "ir" / "scope_expansion_decisions.yaml", {"version": 1, "decisions": decisions})

    # Only increment rounds when we actually attempted pending requests.
    receipt = {
        "version": 1,
        "rounds": rounds + 1,
        "expanded_files": expanded_total + newly,
        "new_files": newly,
        "previous_request_fingerprints": sorted(prev_fps),
        "scope_updated": scope_updated,
        "source_snapshot_hash": snapshot_after,
        "previous_source_snapshot_hash": snapshot_before,
        "closure": {"file_count": len(closure_info.get("files") or [])} if closure_info else {},
        "cbm": cbm_info,
        "status": "ok" if newly else "no_progress",
    }
    write_yaml(uo_root / "ir" / "scope_expansion_receipt.yaml", receipt)
    out = {"ok": True, **receipt, "decisions": decisions}
    if newly:
        out["next_actions"] = ["detect_score_post"]
        out["recovery_actions"] = ["detect_score_post"]
    return out
