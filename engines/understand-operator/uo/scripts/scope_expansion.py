"""Controlled scope expansion: LLM proposes, deterministic audit applies."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.source_evidence import verify_scope_symbol_evidence
from uo.scripts.source_include_closure import (
    classify_include_resolution,
    expand_local_include_closure,
    write_include_closure_ssot,
)
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
    """Prefer active run scope; fall back to newest glob for fixtures."""
    try:
        from uo._operator.run_context import active_run_id, is_active_run_id

        rid = None
        try:
            rid = active_run_id(uo_root)
        except Exception:  # noqa: BLE001
            manifest = read_yaml(uo_root / "manifest.yaml") or {}
            cand = str(manifest.get("current_run_id") or "").strip()
            if is_active_run_id(cand):
                rid = cand
        if rid:
            path = uo_root / "runs" / rid / "scope" / "scope_confirmed.yaml"
            if path.is_file():
                return path, read_yaml(path) or {}
    except Exception:  # noqa: BLE001
        pass
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


def _evidence_windows(request: dict[str, Any]) -> list[Any]:
    wins = (
        request.get("evidence_windows")
        or request.get("symbol_evidence")
        or request.get("evidence")
        or []
    )
    return list(wins) if isinstance(wins, list) else []


def _is_reachable_from_scope(
    project_root: Path,
    candidate_rel: str,
    candidate_path: Path,
    *,
    confirmed_rels: list[str],
    request: dict[str, Any],
    architecture: str,
) -> tuple[bool, str]:
    """Require verified include edge OR machine-verified symbol evidence."""
    wins = _evidence_windows(request)
    if wins:
        proof = verify_scope_symbol_evidence(
            project_root,
            candidate_rel,
            candidate_path,
            wins,
            missing_symbol=str(request.get("missing_symbol") or ""),
        )
        if proof.get("ok"):
            return True, "symbol_evidence"
        # Explicit evidence present but invalid → fail closed (do not fall through to basename).
        if any(
            isinstance(w, dict)
            and (
                str(w.get("file") or w.get("path") or "").replace("\\", "/").endswith(Path(candidate_rel).name)
                or str(w.get("file") or w.get("path") or "").replace("\\", "/") == candidate_rel
            )
            for w in wins
        ):
            return False, str(proof.get("reason_code") or "invalid_evidence")

    cand_posix = candidate_rel.replace("\\", "/")
    for crel in confirmed_rels:
        src = project_root / crel
        if not src.is_file():
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
            delim, inc = m.group(1), m.group(2).replace("\\", "/")
            classified = classify_include_resolution(
                project_root, src, inc, delimiter=delim, architecture=architecture
            )
            status = str(classified.get("status") or "")
            if status == "resolved_unique":
                target = str(classified.get("target") or "").replace("\\", "/")
                if target == cand_posix:
                    return True, "include_edge"
                try:
                    if (project_root / target).resolve() == candidate_path.resolve():
                        return True, "include_edge"
                except OSError:
                    pass
            elif status == "resolved_multiple":
                cands = [str(c).replace("\\", "/") for c in (classified.get("candidates") or [])]
                if cand_posix in cands or Path(cand_posix).name in {Path(c).name for c in cands}:
                    return False, "ambiguous_reachability"

    try:
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
    round_slots_remaining: int | None = None,
    total_slots_remaining: int | None = None,
) -> dict[str, Any]:
    """Deterministic audit: every proposed file gets a unique disposition."""
    already = already_expanded or set()
    proposed = list(request.get("proposed_files") or [])
    req = dict(request)
    req["op_name"] = op_name
    if confirmed_rels is None and uo_root is not None:
        _, scope = _latest_scope_confirmed(uo_root)
        confirmed_rels = _confirmed_rels(scope)
    confirmed_rels = list(confirmed_rels or [])
    round_left = MAX_FILES_PER_ROUND if round_slots_remaining is None else int(round_slots_remaining)
    total_left = MAX_TOTAL_EXPANDED_FILES if total_slots_remaining is None else int(total_slots_remaining)

    dispositions: list[dict[str, str]] = []
    applied: list[str] = []
    deferred: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []

    for item in proposed:
        rel = str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/")
        if not rel:
            continue
        if rel in already or rel in applied:
            row = {"path": rel, "disposition": "duplicate", "reason": "duplicate"}
            dispositions.append(row)
            rejected.append({"path": rel, "reason": "duplicate"})
            continue
        if ".." in Path(rel).parts:
            row = {"path": rel, "disposition": "rejected", "reason": "path_traversal"}
            dispositions.append(row)
            rejected.append({"path": rel, "reason": "path_traversal"})
            continue
        if "/arch" in rel and architecture and f"/{architecture}/" not in rel and "common/" not in rel:
            if any(f"/arch{i}/" in rel for i in ("22", "25", "30", "32") if f"arch{i}" != architecture):
                row = {"path": rel, "disposition": "rejected", "reason": "other_architecture"}
                dispositions.append(row)
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
            row = {"path": rel, "disposition": "rejected", "reason": "not_found"}
            dispositions.append(row)
            rejected.append({"path": rel, "reason": "not_found"})
            continue
        posix = str(resolved.get("rel") or rel)
        if not any(m in posix for m in ("op_host/", "op_kernel/", "op_api/", "common/", "op_graph/")):
            row = {"path": rel, "disposition": "out_of_allowed_root", "reason": "outside_allowed_roots"}
            dispositions.append(row)
            rejected.append({"path": rel, "reason": "outside_allowed_roots"})
            continue
        ok_reach, reach_reason = _is_reachable_from_scope(
            project_root,
            posix,
            Path(resolved["path"]),
            confirmed_rels=confirmed_rels,
            request=req,
            architecture=architecture,
        )
        if not ok_reach:
            disp = "ambiguous_reachability" if reach_reason == "ambiguous_reachability" else (
                "invalid_evidence" if str(reach_reason).startswith("EVIDENCE_") or reach_reason == "invalid_evidence"
                else "rejected"
            )
            row = {"path": rel, "disposition": disp, "reason": reach_reason or "not_reachable"}
            dispositions.append(row)
            rejected.append({"path": rel, "reason": reach_reason or "not_reachable"})
            continue

        # Budget decisions happen here — never accept then silently truncate.
        if total_left <= 0:
            row = {"path": posix, "disposition": "deferred_total_budget", "reason": "total_budget"}
            dispositions.append(row)
            deferred.append(row)
            continue
        if round_left <= 0:
            row = {"path": posix, "disposition": "deferred_round_budget", "reason": "round_budget"}
            dispositions.append(row)
            deferred.append(row)
            continue

        row = {"path": posix, "disposition": "applied", "reason": reach_reason or "ok"}
        dispositions.append(row)
        applied.append(posix)
        already.add(posix)
        round_left -= 1
        total_left -= 1

    return {
        "ok": bool(applied) and not deferred,
        "accepted_files": list(applied),  # backward-compat alias (= applied after write)
        "applied_files": list(applied),
        "deferred_files": deferred,
        "rejected_files": rejected,
        "file_dispositions": dispositions,
        "partial": bool(deferred),
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
        if isinstance(r, dict)
        and str(r.get("status") or "") not in {"consumed", "applied", "rejected"}
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
    if scope_path is None or not scope_path.is_file() or not scope:
        return {
            "ok": False,
            "status": "rework_required",
            "error": "SCOPE_CONFIRMED_MISSING",
            "rounds": rounds,
            "new_files": [],
            "scope_updated": False,
            "next_actions": [],
        }

    confirmed_rels = _confirmed_rels(scope)
    snapshot_before = _fp({"files": confirmed_rels})
    scope_fp_before = _fp({"files": confirmed_rels, "revision": scope.get("scope_revision")})

    decisions: list[dict[str, Any]] = []
    newly: list[str] = []
    round_slots = MAX_FILES_PER_ROUND
    total_slots = max(0, MAX_TOTAL_EXPANDED_FILES - len(expanded_total))
    any_deferred = False

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
            round_slots_remaining=round_slots,
            total_slots_remaining=total_slots - len(newly),
        )
        fp = str(audit.get("request_fingerprint") or "")
        applied_now = list(audit.get("applied_files") or [])
        deferred_now = list(audit.get("deferred_files") or [])
        if deferred_now:
            any_deferred = True
        if fp and fp in prev_fps and not applied_now and not deferred_now:
            decisions.append({**audit, "task_id": req.get("task_id"), "status": "no_progress"})
            continue

        if applied_now and deferred_now:
            req_status = "partially_applied"
        elif applied_now:
            req_status = "applied"
        elif deferred_now:
            req_status = "partially_applied"
        else:
            req_status = "rejected"

        decisions.append({**audit, "task_id": req.get("task_id"), "status": req_status})
        newly.extend(applied_now)
        round_slots = max(0, round_slots - len(applied_now))
        if fp:
            prev_fps.add(fp)
        # Only fully terminal requests are consumed; deferred keeps pending.
        if req_status == "applied":
            req["status"] = "consumed"
        elif req_status == "partially_applied":
            req["status"] = "partially_applied"
            # Keep only deferred paths for the next round.
            deferred_paths = {d.get("path") for d in deferred_now if isinstance(d, dict)}
            req["proposed_files"] = [
                p
                for p in (req.get("proposed_files") or [])
                if str(p.get("path") if isinstance(p, dict) else p).replace("\\", "/") in deferred_paths
            ]
        else:
            req["status"] = "rejected"

    scope_updated = False
    snapshot_after = snapshot_before
    scope_fp_after = scope_fp_before
    if newly:
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
        # Re-read and verify files landed.
        reread = read_yaml(scope_path) or {}
        confirmed_after = set(_confirmed_rels(reread))
        if not all(rel in confirmed_after for rel in newly):
            return {
                "ok": False,
                "status": "rework_required",
                "error": "SCOPE_WRITE_VERIFY_FAILED",
                "rounds": rounds,
                "new_files": [],
                "scope_updated": False,
            }
        scope = reread
        scope_updated = True
        snapshot_after = _fp({"files": _confirmed_rels(scope), "revision": scope.get("scope_revision")})
        scope_fp_after = snapshot_after
        write_yaml(
            scope_path.parent / "scope_snapshot.yaml",
            {
                "version": 1,
                "source_snapshot_hash": snapshot_after,
                "scope_fingerprint": scope_fp_after,
                "previous_source_snapshot_hash": snapshot_before,
                "file_count": len(_confirmed_rels(scope)),
                "expanded_files": newly,
            },
        )

    closure_info: dict[str, Any] = {}
    if newly:
        try:
            seeds = []
            for crel in _confirmed_rels(scope):
                p = Path(project_root) / crel
                if p.is_file():
                    seeds.append(p)
            closure = expand_local_include_closure(
                Path(project_root), seeds, architecture=architecture, max_depth=16, max_files=512
            )
            closure_info = write_include_closure_ssot(
                uo_root,
                closure=closure,
                repo_root=Path(project_root),
                scope_revision=scope.get("scope_revision"),
                scope_fingerprint=scope_fp_after,
                source_snapshot_hash=snapshot_after,
            )
        except Exception as exc:  # noqa: BLE001
            closure_info = {"error": str(exc)[:200], "status": "failed"}

    cbm_info: dict[str, Any] = {}
    if newly:
        stage: dict[str, Any] = {}
        try:
            from uo.scripts.stage_cbm_scope import stage_cbm_scope

            stage = stage_cbm_scope(Path(project_root), op_name)
            if not isinstance(stage, dict):
                stage = {"ok": True, "raw": stage}
        except Exception as exc:  # noqa: BLE001
            stage = {"ok": False, "error": str(exc)[:300]}
        try:
            meta_path = uo_root / "cbm" / "index_meta.json"
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            prev_meta: dict[str, Any] = {}
            if meta_path.is_file():
                try:
                    prev_meta = json.loads(meta_path.read_text(encoding="utf-8")) or {}
                except Exception:  # noqa: BLE001
                    prev_meta = {}
            # Merge — never wipe MCP identity with a bare staged document.
            meta = {
                **{k: v for k, v in prev_meta.items() if k not in {"stage", "expanded_files"}},
                "version": int(prev_meta.get("version") or 1),
                "cbm_project": prev_meta.get("cbm_project"),
                "index_id": prev_meta.get("index_id"),
                "indexed_at": prev_meta.get("indexed_at"),
                "repository_revision": prev_meta.get("repository_revision"),
                "indexed_via": prev_meta.get("indexed_via"),
                "status": "pending_index",
                "scope_fingerprint": scope_fp_after,
                "requested_files": newly,
                "indexed_files": list(prev_meta.get("indexed_files") or []),
                "index_mode": "delta",
                "source_snapshot_hash": snapshot_after,
                "stage": stage,
            }
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            write_yaml(
                uo_root / "ir" / "cbm_reindex_request.yaml",
                {
                    "version": 1,
                    "status": "pending_index",
                    "scope_fingerprint": scope_fp_after,
                    "requested_files": newly,
                    "source_snapshot_hash": snapshot_after,
                },
            )
            cbm_info = meta
        except Exception as exc:  # noqa: BLE001
            cbm_info = {"ok": False, "error": str(exc)[:300], "stage": stage}

    # Clear pending only for fully applied/consumed requests (not deferred).
    try:
        tasks_doc = read_yaml(uo_root / "ir" / "llm_tasks.yaml") or {}
        changed = False
        clear_ids = {
            str(d.get("task_id") or "")
            for d in decisions
            if d.get("status") in {"applied", "accepted"} and not d.get("deferred_files")
        }
        keep_ids = {
            str(d.get("task_id") or "")
            for d in decisions
            if d.get("status") == "partially_applied" or d.get("deferred_files")
        }
        for task in tasks_doc.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            tid = str(task.get("task_id") or "")
            if tid in clear_ids and tid not in keep_ids:
                task["pending_scope_expansion"] = False
                changed = True
            elif tid in keep_ids:
                task["pending_scope_expansion"] = True
                changed = True
        if changed:
            write_yaml(uo_root / "ir" / "llm_tasks.yaml", tasks_doc)
    except Exception:  # noqa: BLE001
        pass

    write_yaml(uo_root / "ir" / "scope_expansion_requests.yaml", req_doc)
    write_yaml(uo_root / "ir" / "scope_expansion_decisions.yaml", {"version": 1, "decisions": decisions})

    status = "partially_applied" if any_deferred and newly else ("ok" if newly else "no_progress")
    receipt = {
        "version": 1,
        "rounds": rounds + 1,
        "expanded_files": expanded_total + newly,
        "new_files": newly,
        "previous_request_fingerprints": sorted(prev_fps),
        "scope_updated": scope_updated,
        "scope_fingerprint": scope_fp_after,
        "source_snapshot_hash": snapshot_after,
        "previous_source_snapshot_hash": snapshot_before,
        "closure": {
            "file_count": len(closure_info.get("files") or closure_info.get("resolved_files") or []),
            "status": closure_info.get("status"),
        }
        if closure_info
        else {},
        "cbm": cbm_info,
        "status": status,
    }
    write_yaml(uo_root / "ir" / "scope_expansion_receipt.yaml", receipt)
    out: dict[str, Any] = {"ok": True, **receipt, "decisions": decisions}
    if newly:
        # Must not enter detect_score_post until index receipt lands.
        out["next_actions"] = ["uo_scope_record_index"]
        out["recovery_actions"] = ["uo_scope_record_index"]
        out["pending_index"] = True
    elif any_deferred:
        out["ok"] = True
        out["status"] = "partially_applied"
        out["next_actions"] = ["apply_scope_expansion"]
    return out


def cbm_index_ready_for_score(uo_root: Path) -> dict[str, Any]:
    """Gate helper: pending reindex blocks detect_score_post / negative-evidence conclusions."""
    req = read_yaml(uo_root / "ir" / "cbm_reindex_request.yaml") or {}
    if str(req.get("status") or "") == "pending_index":
        return {
            "ok": False,
            "error": "CBM_REINDEX_PENDING",
            "scope_fingerprint": req.get("scope_fingerprint"),
        }
    meta_path = uo_root / "cbm" / "index_meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            meta = {}
        if str(meta.get("status") or "") in {"pending_index", "staged"}:
            # staged without receipt is not enough after a scope expansion request
            if str(req.get("status") or "") == "pending_index" or meta.get("requested_files"):
                return {"ok": False, "error": "CBM_INDEX_RECEIPT_REQUIRED", "meta_status": meta.get("status")}
    return {"ok": True}
