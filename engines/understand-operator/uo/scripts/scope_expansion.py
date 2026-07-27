"""Controlled scope expansion: LLM proposes, deterministic audit applies."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.source_path_resolve import resolve_scoped_source_path

MAX_SCOPE_EXPANSION_ROUNDS = 3
MAX_FILES_PER_ROUND = 8
MAX_TOTAL_EXPANDED_FILES = 32


def _fp(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def load_requests(uo_root: Path) -> dict[str, Any]:
    return read_yaml(uo_root / "ir" / "scope_expansion_requests.yaml") or {"version": 1, "requests": []}


def audit_scope_expansion_request(
    project_root: Path,
    op_name: str,
    request: dict[str, Any],
    *,
    architecture: str = "arch35",
    already_expanded: set[str] | None = None,
) -> dict[str, Any]:
    """Deterministic audit of one expansion request."""
    already = already_expanded or set()
    proposed = list(request.get("proposed_files") or [])
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    for item in proposed:
        rel = str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/")
        if not rel:
            continue
        if rel in already:
            rejected.append({"path": rel, "reason": "duplicate"})
            continue
        if "/arch" in rel and architecture and f"/{architecture}/" not in rel and "common/" not in rel:
            # Allow op_host top-level; reject other-arch exclusive trees.
            if any(f"/arch{i}/" in rel for i in ("22", "25", "30", "32") if f"arch{i}" != architecture):
                rejected.append({"path": rel, "reason": "other_architecture"})
                continue
        resolved = resolve_scoped_source_path(project_root, rel, op_name, architecture=architecture)
        if not resolved.get("ok"):
            rejected.append({"path": rel, "reason": "not_found"})
            continue
        # Must stay under op or common markers.
        posix = str(resolved.get("rel") or rel)
        if not any(m in posix for m in ("op_host/", "op_kernel/", "op_api/", "common/", "op_graph/")):
            rejected.append({"path": rel, "reason": "outside_allowed_roots"})
            continue
        if ".." in Path(rel).parts:
            rejected.append({"path": rel, "reason": "path_traversal"})
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
) -> dict[str, Any]:
    """Audit pending requests and append accepted files into latest scope_confirmed."""
    req_doc = load_requests(uo_root)
    requests = [r for r in (req_doc.get("requests") or []) if isinstance(r, dict)]
    receipt_prev = read_yaml(uo_root / "ir" / "scope_expansion_receipt.yaml") or {}
    rounds = int(receipt_prev.get("rounds") or 0)
    expanded_total = list(receipt_prev.get("expanded_files") or [])
    prev_fps = set(receipt_prev.get("previous_request_fingerprints") or [])

    if rounds >= MAX_SCOPE_EXPANSION_ROUNDS:
        return {
            "ok": False,
            "error": "SCOPE_EXPANSION_BUDGET_EXCEEDED",
            "rounds": rounds,
            "status": "human_required",
        }

    decisions: list[dict[str, Any]] = []
    newly: list[str] = []
    for req in requests:
        audit = audit_scope_expansion_request(
            project_root,
            op_name,
            req,
            architecture=architecture,
            already_expanded=set(expanded_total) | set(newly),
        )
        fp = str(audit.get("request_fingerprint") or "")
        if fp and fp in prev_fps and not audit.get("accepted_files"):
            decisions.append({**audit, "task_id": req.get("task_id"), "status": "no_progress"})
            continue
        decisions.append({**audit, "task_id": req.get("task_id"), "status": "accepted" if audit.get("ok") else "rejected"})
        newly.extend(list(audit.get("accepted_files") or []))
        if fp:
            prev_fps.add(fp)

    if len(expanded_total) + len(newly) > MAX_TOTAL_EXPANDED_FILES:
        newly = newly[: max(0, MAX_TOTAL_EXPANDED_FILES - len(expanded_total))]

    # Update latest scope_confirmed if present.
    runs = sorted((uo_root / "runs").glob("*/scope/scope_confirmed.yaml"), reverse=True)
    scope_updated = False
    if newly and runs:
        scope_path = runs[0]
        scope = read_yaml(scope_path) or {}
        files = list(scope.get("confirmed_source_files") or scope.get("confirmed_file_list") or [])
        existing = {
            str(i.get("path") if isinstance(i, dict) else i).replace("\\", "/") for i in files
        }
        for rel in newly:
            if rel not in existing:
                files.append({"path": rel, "source": "scope_expansion"})
                existing.add(rel)
        scope["confirmed_source_files"] = files
        write_yaml(scope_path, scope)
        scope_updated = True

    write_yaml(
        uo_root / "ir" / "scope_expansion_decisions.yaml",
        {"version": 1, "decisions": decisions},
    )
    receipt = {
        "version": 1,
        "rounds": rounds + 1,
        "expanded_files": expanded_total + newly,
        "new_files": newly,
        "previous_request_fingerprints": sorted(prev_fps),
        "scope_updated": scope_updated,
        "status": "ok" if newly else "no_progress",
    }
    write_yaml(uo_root / "ir" / "scope_expansion_receipt.yaml", receipt)
    return {"ok": True, **receipt, "decisions": decisions}
