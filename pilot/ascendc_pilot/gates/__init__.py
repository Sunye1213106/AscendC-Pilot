"""Hard quality gates — script authority (not prompt soft constraints)."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import runs_root, uo_root

EMPTY_PATH_MARKERS = (
    "runemptytiling",
    "emptytensor",
    "empty_tensor",
    "isemptytensor",
)
MAIN_TILING_ANCHORS = (
    "gettilingkey",
    "savetotilingdata",
    "normal_regbase",
    "dooptiling",
    "tilingkey",
)
BITPACK_EXCUSE_MARKERS = (
    "bit-pack",
    "bitpack",
    "跨编译边界",
    "无法回溯",
    "编译边界",
)


def _load(path: Path) -> Any:
    if yaml is None or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    # IR with embedded code snippets: sanitize literal blocks before parse.
    if path.name in {"extract_plan.yaml", "semantic_patches.yaml"}:
        try:
            from ascendc_pilot.yaml_literal_sanitize import safe_load_yaml_text

            return safe_load_yaml_text(text)
        except Exception:  # noqa: BLE001
            pass
    return yaml.safe_load(text)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _reason_fingerprint(text: str) -> str:
    t = _norm(text)
    # Drop KEY ids so identical boilerplate collapses
    t = re.sub(r"key_[a-z0-9_]+", "KEY", t, flags=re.I)
    return t[:240]


def gate_prepare_layout_receipt(project_root: Path) -> dict[str, Any]:
    """Require a verified prepare_layout receipt for the current run (not file existence)."""
    from ascendc_pilot.runs import verify_receipt

    verified = verify_receipt(
        project_root,
        action_id="prepare_layout",
        require_pilot_issued=True,
        require_hashes=True,
        require_action_id=True,
        require_spec_hash=True,
    )
    ok = bool(verified.get("ok"))
    return {
        "gate": "prepare_layout_receipt",
        "ok": ok,
        "receipt_verify": verified,
        "message": "ok" if ok else "prepare_layout receipt missing or invalid for current run",
    }


def gate_key_triage_required(uo: Path) -> dict[str, Any]:
    """escalate/gaps open → must have non-empty ir/key_triage.yaml."""
    gaps_path = uo / "ir" / "input_derivable_gaps.yaml"
    unresolved_path = uo / "ir" / "unresolved.yaml"
    triage_path = uo / "ir" / "key_triage.yaml"

    gaps = _load(gaps_path) or {}
    unresolved = _load(unresolved_path) or {}

    open_gaps: list[str] = []
    if isinstance(gaps, dict):
        items = gaps.get("gaps") or gaps.get("items") or gaps.get("open") or []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    kid = str(it.get("id") or it.get("key") or "")
                    status = str(it.get("status") or it.get("state") or "open").lower()
                    if kid and status in {"", "open", "unsolved", "escalate"}:
                        open_gaps.append(kid)
                elif isinstance(it, str):
                    open_gaps.append(it)
        keys = gaps.get("keys")
        if isinstance(keys, dict):
            open_gaps.extend(str(k) for k in keys)

    escalate_keys: list[str] = []
    if isinstance(unresolved, dict):
        raw = unresolved.get("escalate_keys") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    escalate_keys.append(item)
                elif isinstance(item, dict):
                    escalate_keys.append(str(item.get("id") or item.get("key") or ""))

    needs_triage = bool(open_gaps or escalate_keys)
    triage = _load(triage_path)
    triage_keys: list[str] = []
    if isinstance(triage, dict):
        keys = triage.get("keys") or triage.get("items") or []
        if isinstance(keys, list):
            for it in keys:
                if isinstance(it, dict):
                    triage_keys.append(str(it.get("id") or it.get("key") or ""))
                elif isinstance(it, str):
                    triage_keys.append(it)
        elif isinstance(keys, dict):
            triage_keys = [str(k) for k in keys]

    ok = (not needs_triage) or bool(triage_keys)
    return {
        "gate": "key_triage_required",
        "ok": ok,
        "needs_triage": needs_triage,
        "open_gaps": open_gaps,
        "escalate_keys": escalate_keys,
        "triage_key_count": len(triage_keys),
        "message": (
            "ok"
            if ok
            else "escalate_keys or input_derivable_gaps open but ir/key_triage.yaml missing/empty — must run uo-key-resolve triage"
        ),
    }


def gate_key_resolve_receipt(project_root: Path, uo: Path) -> dict[str, Any]:
    """When triage required, require Pilot-issued key_resolution receipt (exact action_id)."""
    triage = gate_key_triage_required(uo)
    if not triage.get("needs_triage"):
        return {"gate": "key_resolve_receipt", "ok": True, "skipped": True, "message": "no triage needed"}

    from ascendc_pilot.runs import verify_receipt
    from ascendc_pilot.state import load_state

    state = load_state(project_root)
    verified = verify_receipt(
        project_root,
        actor_id="uo-key-resolve",
        action_id="key_resolution",
        require_pilot_issued=True,
        require_hashes=True,
        require_action_id=True,
        require_spec_hash=True,
    )
    # Fail-closed: triage receipt must NOT satisfy resolution gate.
    patch = uo / "ir" / "input_derivable_patch.yaml"
    shape_dir = uo / "ir" / "key_shape_resolve"
    has_artifacts = patch.is_file() or (shape_dir.is_dir() and any(shape_dir.glob("*.yaml")))
    has_receipt = bool(verified.get("ok"))
    ok = has_receipt and bool(triage.get("triage_key_count")) and has_artifacts
    if not triage.get("triage_key_count"):
        ok = False
    return {
        "gate": "key_resolve_receipt",
        "ok": ok,
        "has_receipt": has_receipt,
        "receipt_verify": verified,
        "has_artifacts": has_artifacts,
        "run_id": state.get("run_id"),
        "message": (
            "ok"
            if ok
            else "KEY triage required but missing verified Pilot-issued key_resolution receipt + resolve artifacts"
        ),
    }


def gate_empty_only_producer(uo: Path) -> dict[str, Any]:
    """Reject final accepted/resolved when producer evidence is empty-path only."""
    offenders: list[dict[str, str]] = []
    for rel in (
        "ir/resolution_patch.yaml",
        "ir/input_derivable_patch.yaml",
        "ir/input_derivable.yaml",
    ):
        doc = _load(uo / rel)
        if not isinstance(doc, dict):
            continue
        items = doc.get("items") or doc.get("accepted") or doc.get("resolved") or []
        if isinstance(doc.get("keys"), dict):
            items = list(items) if isinstance(items, list) else []
            for kid, entry in doc["keys"].items():
                if isinstance(entry, dict):
                    row = dict(entry)
                    row["id"] = kid
                    items.append(row)
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            status = str(it.get("status") or it.get("disposition") or "").lower()
            if status and status not in {"accepted", "resolved", "closed"}:
                continue
            blob = " ".join(
                str(it.get(k) or "")
                for k in ("producer", "producers", "evidence", "file_path", "path", "reason", "host_parent", "notes")
            ).lower()
            # also scan nested lists
            for key in ("producers", "evidence_paths", "paths"):
                val = it.get(key)
                if isinstance(val, list):
                    blob += " " + " ".join(str(x).lower() for x in val)
            has_empty = any(m in blob for m in EMPTY_PATH_MARKERS)
            has_main = any(m in blob for m in MAIN_TILING_ANCHORS)
            if has_empty and not has_main and (status in {"accepted", "resolved", "closed"} or it.get("input_derivable") in (True, False)):
                # Only flag when explicitly claiming closure via empty-only
                if status in {"accepted", "resolved", "closed"} or str(it.get("confidence") or "").lower() == "high":
                    offenders.append(
                        {
                            "id": str(it.get("id") or it.get("key") or "?"),
                            "file": rel,
                            "reason": "missing_producer evidence only on empty tiling path",
                        }
                    )

    # Also scan residual escalate that was wrongly accepted in resolution_patch
    res = _load(uo / "ir" / "resolution_patch.yaml")
    if isinstance(res, dict):
        for it in res.get("items") or []:
            if not isinstance(it, dict):
                continue
            if str(it.get("status") or "").lower() not in {"accepted", "resolved"}:
                continue
            blob = str(it.get("evidence") or it.get("reason") or it.get("producer") or "").lower()
            if any(m in blob for m in EMPTY_PATH_MARKERS) and not any(m in blob for m in MAIN_TILING_ANCHORS):
                offenders.append(
                    {
                        "id": str(it.get("id") or "?"),
                        "file": "ir/resolution_patch.yaml",
                        "reason": "empty-only producer accepted; must escalate to key-resolve on main tiling path",
                    }
                )

    # Dedupe
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for row in offenders:
        key = f"{row['id']}:{row['file']}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)

    return {
        "gate": "empty_only_producer",
        "ok": not uniq,
        "offenders": uniq,
        "message": "ok" if not uniq else f"{len(uniq)} KEY(s) closed with empty-path-only producer evidence",
    }


def gate_confidence_report_quality(uo: Path, *, min_dup: int = 5) -> dict[str, Any]:
    """Reject boilerplate identical bit-pack excuses across many KEYs."""
    report_path = uo / "summary" / "confidence_report.md"
    if not report_path.is_file():
        return {"gate": "key_report_quality", "ok": True, "skipped": True, "message": "no report"}

    text = report_path.read_text(encoding="utf-8")
    sections = re.split(r"^###\s+(KEY_\S+|KVAR_\S+)\s*$", text, flags=re.MULTILINE)
    # parts: preamble, id1, body1, id2, body2, ...
    reasons: list[tuple[str, str]] = []
    i = 1
    while i + 1 < len(sections):
        kid = sections[i]
        body = sections[i + 1]
        m = re.search(r"^\s*-\s*原因\s*[：:]\s*(.+)$", body, re.MULTILINE)
        reason = m.group(1).strip() if m else ""
        reasons.append((kid, reason))
        i += 2

    fps = [_reason_fingerprint(r) for _, r in reasons if r and not r.startswith("TODO")]
    counts = Counter(fps)
    dup_clusters = {fp: n for fp, n in counts.items() if fp and n >= min_dup}
    bitpack_hits = [kid for kid, r in reasons if any(m in r.lower() or m in r for m in BITPACK_EXCUSE_MARKERS)]

    # Host predicates available?
    predicates_path = uo / "ir" / "key_predicates.yaml"
    host_preds = _load(predicates_path)
    host_readable = isinstance(host_preds, dict) and bool(host_preds.get("keys") or host_preds.get("predicates"))

    ok = not dup_clusters
    if host_readable and len(bitpack_hits) >= min_dup and dup_clusters:
        ok = False

    return {
        "gate": "key_report_quality",
        "ok": ok,
        "duplicate_clusters": {k[:80]: v for k, v in list(dup_clusters.items())[:5]},
        "bitpack_key_count": len(bitpack_hits),
        "host_predicates_present": host_readable,
        "section_count": len(reasons),
        "message": (
            "ok"
            if ok
            else "confidence_report uses duplicated boilerplate (e.g. bit-pack) across KEYs; Host predicates should yield shape_expr/input_derivable"
        ),
    }


def gate_confidence_closed_high(uo: Path, *, allow_reported_with_human: bool = False) -> dict[str, Any]:
    """closed_high_count=0 with KEY list → fail unless human accepted (any status)."""
    conf = _load(uo / "checks" / "confidence_gate.yaml") or {}
    id_doc = _load(uo / "ir" / "input_derivable.yaml") or {}
    keys = (id_doc.get("keys") or {}) if isinstance(id_doc, dict) else {}
    key_count = len(keys) if isinstance(keys, dict) else 0
    closed_high = int(conf.get("closed_high_count") or 0) if isinstance(conf, dict) else 0
    need_llm = int(conf.get("need_llm_count") or 0) if isinstance(conf, dict) else 0
    status = str(conf.get("status") or "") if isinstance(conf, dict) else ""

    # Prefer live counts from input_derivable when confidence_gate is missing/stale/forged
    if isinstance(keys, dict) and keys:
        live_closed = 0
        live_need = 0
        for entry in keys.values():
            if not isinstance(entry, dict):
                continue
            idv = entry.get("input_derivable")
            conf_v = str(entry.get("confidence") or "").lower()
            if idv is True or idv is False or entry.get("not_input_derivable") is True:
                if conf_v == "high":
                    live_closed += 1
                else:
                    live_need += 1
            else:
                live_need += 1
        closed_high = live_closed
        need_llm = max(need_llm, live_need)

    human_accept = uo / "checks" / "human_accept_reported.yaml"
    human_ok = False
    if human_accept.is_file():
        doc = _load(human_accept) or {}
        human_ok = isinstance(doc, dict) and bool(doc.get("accepted"))

    ok = True
    reasons: list[str] = []
    # Hard rule: KEY non-empty + closed_high=0 → fail unless human accept
    # (covers forged status=pass bypass of the old status==reported-only check)
    if key_count > 0 and closed_high == 0:
        if human_ok or allow_reported_with_human:
            ok = True
        else:
            ok = False
            reasons.append(
                "closed_high_count=0 with non-empty KEY list "
                "(default fail for any confidence_gate status; write checks/human_accept_reported.yaml to override)"
            )
    if need_llm > 0:
        triage = gate_key_triage_required(uo)
        if triage.get("needs_triage") and not triage.get("ok"):
            ok = False
            reasons.append("need_llm_count>0 but key_triage missing")

    return {
        "gate": "confidence_closed_high",
        "ok": ok,
        "closed_high_count": closed_high,
        "need_llm_count": need_llm,
        "key_count": key_count,
        "status": status,
        "human_accepted_reported": human_ok,
        "message": "ok" if ok else "; ".join(reasons),
    }


def gate_confidence_reason_review(uo: Path) -> dict[str, Any]:
    """Non-high KEYs must have filled reasons + independent referee subagent pass."""
    conf = _load(uo / "checks" / "confidence_gate.yaml") or {}
    id_doc = _load(uo / "ir" / "input_derivable.yaml") or {}
    keys = (id_doc.get("keys") or {}) if isinstance(id_doc, dict) else {}
    need_ids: list[str] = []
    if isinstance(keys, dict):
        for kid, entry in keys.items():
            if not isinstance(entry, dict):
                continue
            idv = entry.get("input_derivable")
            conf_v = str(entry.get("confidence") or "").lower()
            closed = idv is True or idv is False or entry.get("not_input_derivable") is True
            if closed and conf_v == "high":
                continue
            need_ids.append(str(kid))
    need_llm = int(conf.get("need_llm_count") or 0) if isinstance(conf, dict) else 0
    status = str(conf.get("status") or "").lower() if isinstance(conf, dict) else ""
    requires = bool(need_ids) or need_llm > 0 or status == "reported"
    if not requires:
        return {
            "gate": "confidence_reason_review",
            "ok": True,
            "skipped": True,
            "message": "all KEY closed high — no reason review required",
        }

    report_path = uo / "summary" / "confidence_report.md"
    if not report_path.is_file():
        return {
            "gate": "confidence_reason_review",
            "ok": False,
            "need_ids": need_ids,
            "message": "non-high KEY present but summary/confidence_report.md missing",
        }

    text = report_path.read_text(encoding="utf-8")
    missing_reason: list[str] = []
    for kid in need_ids:
        m = re.search(rf"^###\s+{re.escape(kid)}\s*$", text, re.MULTILINE)
        if not m:
            missing_reason.append(kid)
            continue
        start = m.end()
        nxt = re.search(r"^###\s+\S+", text[start:], re.MULTILINE)
        body = text[start : start + nxt.start()] if nxt else text[start:]
        rm = re.search(r"^\s*-\s*原因\s*[：:]\s*(.+)$", body, re.MULTILINE)
        if not rm:
            missing_reason.append(kid)
            continue
        reason = rm.group(1).strip()
        if not reason or reason.startswith("TODO") or reason.startswith("（待"):
            missing_reason.append(kid)

    review = _load(uo / "review" / "confidence_reason_review.yaml") or {}
    verdict = str(review.get("verdict") or review.get("status") or "").lower() if isinstance(review, dict) else ""
    agent = str(review.get("agent") or review.get("reviewed_by") or "") if isinstance(review, dict) else ""
    # Referee must be the dedicated subagent (athlete/referee separation) — no empty agent self-pass
    referee_ok = verdict in {"pass", "passed", "ok"} and agent in {
        "uo-confidence-review",
        "confidence-review",
    }

    ok = (not missing_reason) and referee_ok
    reasons: list[str] = []
    if missing_reason:
        reasons.append(f"confidence_report missing/placeholder 原因 for: {missing_reason[:8]}")
    if not referee_ok:
        reasons.append(
            "review/confidence_reason_review.yaml missing or verdict≠pass "
            "(must be written by uo-confidence-review referee subagent)"
        )
    return {
        "gate": "confidence_reason_review",
        "ok": ok,
        "need_ids": need_ids,
        "missing_reason_ids": missing_reason,
        "referee_verdict": verdict,
        "referee_agent": agent,
        "message": "ok" if ok else "; ".join(reasons),
    }


def gate_kb_review_consistency(uo: Path) -> dict[str, Any]:
    """kb-review must not pass when key gates fail."""
    review = _load(uo / "review" / "kb_product_review.yaml") or {}
    verdict = str(review.get("verdict") or review.get("status") or "").lower() if isinstance(review, dict) else ""
    if verdict not in {"pass", "passed", "ok"}:
        return {"gate": "kb_review_consistency", "ok": True, "skipped": True, "verdict": verdict}

    checks = [
        gate_key_triage_required(uo),
        gate_empty_only_producer(uo),
        gate_confidence_report_quality(uo),
        gate_confidence_closed_high(uo),
        gate_confidence_reason_review(uo),
    ]
    failed = [c for c in checks if not c.get("ok")]
    return {
        "gate": "kb_review_consistency",
        "ok": not failed,
        "verdict": verdict,
        "failed_gates": [c.get("gate") for c in failed],
        "message": "ok" if not failed else f"kb-review verdict=pass but gates failed: {[c.get('gate') for c in failed]}",
    }


def gate_confidence_gate_file(uo: Path) -> dict[str, Any]:
    """checks/confidence_gate.yaml must exist and status ∈ {pass, reported} after script run."""
    conf = _load(uo / "checks" / "confidence_gate.yaml")
    if not isinstance(conf, dict):
        return {
            "gate": "confidence_gate",
            "ok": False,
            "message": "checks/confidence_gate.yaml missing — run check_final_confidence.py",
        }
    status = str(conf.get("status") or "").lower()
    ok = status in {"pass", "reported"}
    return {
        "gate": "confidence_gate",
        "ok": ok,
        "status": status,
        "message": "ok" if ok else f"confidence_gate status={status!r} not in {{pass, reported}}",
    }


def _integrity_status_pass(doc: Any) -> tuple[bool, str]:
    """Shared integrity status semantics for gate_integrity_file / gate_uo_ready.

    Only exact ``status == \"pass\"`` succeeds. Missing/empty/ok/reported/unknown all fail.
    """
    if not isinstance(doc, dict):
        return False, ""
    raw = doc.get("status")
    if raw is None:
        return False, ""
    status = str(raw).strip().lower()
    if not status:
        return False, ""
    return status == "pass", status


def gate_integrity_file(uo: Path) -> dict[str, Any]:
    path = uo / "checks" / "integrity.yaml"
    if not path.is_file() or path.stat().st_size <= 0:
        return {"gate": "integrity", "ok": False, "message": "checks/integrity.yaml missing"}
    try:
        doc = _load(path)
    except Exception:  # noqa: BLE001
        return {"gate": "integrity", "ok": False, "message": "checks/integrity.yaml unreadable"}
    ok, status = _integrity_status_pass(doc)
    return {
        "gate": "integrity",
        "ok": ok,
        "status": status,
        "message": "ok" if ok else f"integrity status={status!r}",
    }


def gate_kb_review_file(uo: Path) -> dict[str, Any]:
    doc = _load(uo / "review" / "kb_product_review.yaml")
    if not isinstance(doc, dict):
        return {"gate": "kb_review", "ok": False, "message": "review/kb_product_review.yaml missing"}
    verdict = str(doc.get("verdict") or doc.get("status") or "").lower()
    ok = verdict in {"pass", "passed", "ok"}
    return {
        "gate": "kb_review",
        "ok": ok,
        "verdict": verdict,
        "message": "ok" if ok else f"kb-review verdict={verdict!r}",
    }


def gate_scope_receipt(project_root: Path, uo: Path) -> dict[str, Any]:
    """Scope confirmation for the *current* run only + MCP index_meta (indexed_via=mcp).

    Fail-closed: never scan other runs or pick newest-by-mtime. Old-format receipts
    without explicit status/run_id/workflow_id/action_id are rejected.

    One ACP session uses one run id: Pilot state.run_id == manifest.current_run_id
    == runs/<run_id>/scope/scope_confirmed.yaml.
    """
    from ascendc_pilot.state import load_state

    state = load_state(project_root) or {}
    run_id = str(state.get("run_id") or "").strip()
    workflow_id = str(state.get("workflow_id") or "").strip()
    if not run_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MISSING",
            "message": "no active run_id for scope_receipt",
        }

    confirmed_path = uo / "runs" / run_id / "scope" / "scope_confirmed.yaml"
    meta = uo / "cbm" / "index_meta.json"
    indexed_via = ""
    if meta.is_file():
        try:
            import json

            loaded = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                indexed_via = str(loaded.get("indexed_via") or loaded.get("via") or "")
        except Exception:  # noqa: BLE001
            indexed_via = ""

    if not confirmed_path.is_file():
        manifest_run = ""
        try:
            import yaml

            raw_m = yaml.safe_load((uo / "manifest.yaml").read_text(encoding="utf-8")) or {}
            if isinstance(raw_m, dict):
                manifest_run = str(raw_m.get("current_run_id") or "").strip()
        except Exception:  # noqa: BLE001
            manifest_run = ""
        if manifest_run and manifest_run != run_id:
            return {
                "gate": "scope_receipt",
                "ok": False,
                "error": "SCOPE_RECEIPT_RUN_MISMATCH",
                "scope_path": confirmed_path.as_posix(),
                "manifest_run_id": manifest_run,
                "message": (
                    f"run id 未对齐：Pilot state.run_id={run_id!r} "
                    f"但 manifest.current_run_id={manifest_run!r}；"
                    "一次会话必须共用同一个 run id（prepare_layout 须传 --run-id）"
                ),
            }
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MISSING",
            "scope_path": confirmed_path.as_posix(),
            "message": f"范围确认缺失（需要 runs/{run_id}/scope/scope_confirmed.yaml）",
        }

    raw = _load(confirmed_path)
    if not isinstance(raw, dict):
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MIGRATION_REQUIRED",
            "scope_path": confirmed_path.as_posix(),
            "message": "scope_confirmed.yaml unreadable or not a mapping",
        }

    status_raw = raw.get("status")
    if status_raw is None or str(status_raw).strip() == "":
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_STATUS_MISSING",
            "scope_path": confirmed_path.as_posix(),
            "message": "scope_confirmed.yaml missing status: confirmed",
        }
    status = str(status_raw).strip().lower()
    if status != "confirmed":
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_STATUS_MISSING",
            "scope_path": confirmed_path.as_posix(),
            "status": status,
            "message": f"scope status must be confirmed (got {status!r})",
        }

    file_run = str(raw.get("run_id") or "").strip()
    file_wf = str(raw.get("workflow_id") or "").strip()
    file_action = str(raw.get("action_id") or "").strip()
    if not file_run or not file_wf or not file_action:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MIGRATION_REQUIRED",
            "scope_path": confirmed_path.as_posix(),
            "message": "scope_confirmed.yaml missing run_id/workflow_id/action_id (migration required)",
        }
    if file_run != run_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_RUN_MISMATCH",
            "scope_path": confirmed_path.as_posix(),
            "message": f"scope run_id={file_run!r} != current {run_id!r}",
        }
    if file_wf != workflow_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_WORKFLOW_MISMATCH",
            "scope_path": confirmed_path.as_posix(),
            "message": f"scope workflow_id={file_wf!r} != current {workflow_id!r}",
        }
    if file_action != "scope_confirmation":
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_ACTION_MISMATCH",
            "scope_path": confirmed_path.as_posix(),
            "message": f"scope action_id must be scope_confirmation (got {file_action!r})",
        }

    mcp_ok = meta.is_file() and indexed_via.lower() in {"mcp", "codebase-memory", "cbm"}
    if not meta.is_file():
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MCP_MISSING",
            "scope_path": confirmed_path.as_posix(),
            "indexed_via": indexed_via,
            "message": (
                "缺少 cbm/index_meta.json（MCP index 后须执行 "
                "acp uo-scope record-index --cbm-project <name>）"
            ),
        }
    if not mcp_ok:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MCP_INVALID",
            "scope_path": confirmed_path.as_posix(),
            "indexed_via": indexed_via,
            "message": f"cbm/index_meta.json indexed_via 必须为 mcp（当前={indexed_via!r}）",
        }
    return {
        "gate": "scope_receipt",
        "ok": True,
        "indexed_via": indexed_via,
        "scope_path": confirmed_path.as_posix(),
        "run_id": run_id,
        "workflow_id": workflow_id,
        "message": "ok",
    }


def gate_extract_plan_subagent(project_root: Path, uo: Path) -> dict[str, Any]:
    """Require extract_plan artifacts + required actor/run/workflow/hash fields.

    Do **not** require a Pilot-issued receipt here: receipts are written by
    ``acp run-action extract_plan --finalize`` only after this gate passes.
    """
    from ascendc_pilot.runs import file_sha256, verify_receipt
    from ascendc_pilot.state import load_state

    state = load_state(project_root) or {}
    run_id = str(state.get("run_id") or "").strip()
    workflow_id = str(state.get("workflow_id") or "").strip()

    plan = uo / "ir" / "extract_plan.yaml"
    candidates = uo / "ir" / "extract_plan_candidates.yaml"
    entrypoints = uo / "ir" / "entrypoint_graph.yaml"
    boundary = uo / "ir" / "operator_boundary.yaml"
    verified = verify_receipt(
        project_root,
        actor_id="uo-semantic-resolve",
        action_id="extract_plan",
        require_pilot_issued=True,
        require_hashes=True,
        require_action_id=True,
        require_spec_hash=True,
    )
    has_receipt = bool(verified.get("ok"))

    plan_ok = plan.is_file()
    cand_ok = candidates.is_file()
    ep_ok = entrypoints.is_file()
    boundary_ok = boundary.is_file()
    hash_ok = False
    cand_status_ok = True
    producer_ok = False
    run_ok = False
    workflow_ok = False
    errors: list[str] = []

    if not plan_ok:
        errors.append("extract_plan.yaml missing")
    if not cand_ok:
        errors.append("extract_plan_candidates.yaml missing")
    if not ep_ok:
        errors.append("entrypoint_graph.yaml missing")
    if not boundary_ok:
        errors.append("operator_boundary.yaml missing")

    plan_doc: dict[str, Any] = {}
    if plan_ok:
        loaded = _load(plan)
        if not isinstance(loaded, dict):
            errors.append("extract_plan.yaml unreadable")
            plan_ok = False
        else:
            plan_doc = loaded

    if plan_ok:
        actor = str(plan_doc.get("actor_id") or "").strip()
        if not actor:
            errors.append("extract_plan.actor_id missing")
        elif actor != "uo-semantic-resolve":
            errors.append(f"extract_plan.actor_id={actor!r} != uo-semantic-resolve")
        else:
            producer_ok = True

        plan_run = str(plan_doc.get("run_id") or "").strip()
        if not plan_run:
            errors.append("extract_plan.run_id missing")
        elif plan_run != run_id:
            errors.append(f"extract_plan.run_id={plan_run!r} != current {run_id!r}")
        else:
            run_ok = True

        plan_wf = str(plan_doc.get("workflow_id") or "").strip()
        if not plan_wf:
            errors.append("extract_plan.workflow_id missing")
        elif plan_wf != workflow_id:
            errors.append(f"extract_plan.workflow_id={plan_wf!r} != current {workflow_id!r}")
        else:
            workflow_ok = True

    contract_ok = True
    contract_errors: list[str] = []
    if plan_ok and cand_ok:
        expected = str(
            plan_doc.get("candidates_sha256")
            or (plan_doc.get("meta") or {}).get("candidates_sha256")
            or ""
        ).strip()
        actual = file_sha256(candidates) or ""
        if not expected:
            errors.append("extract_plan.candidates_sha256 missing")
        elif not actual:
            errors.append("extract_plan_candidates.yaml hash empty")
        elif expected != actual:
            errors.append("extract_plan.candidates_sha256 mismatch")
        else:
            hash_ok = True
        cand_doc = _load(candidates) or {}
        if isinstance(cand_doc, dict):
            st = str(cand_doc.get("status") or "").lower()
            if st in {"blocked", "fail", "failed"} or cand_doc.get("ok") is False:
                cand_status_ok = False
                errors.append("extract_plan_candidates status blocked/fail")
            # Same authority as apply_extract_plan (evidence + action contracts).
            try:
                return {"ok": True, "skipped": True, "gate": "legacy_removed", "message": "old semantic/extract_plan gate retired"}

                normalized = normalize_plan_from_candidates(plan_doc, cand_doc)
                contract_errors = validate_extract_plan_against_candidates(
                    normalized, cand_doc, project_root=project_root
                )
                if contract_errors:
                    contract_ok = False
                    errors.extend(contract_errors[:12])
            except Exception as exc:  # noqa: BLE001
                contract_ok = False
                errors.append(f"extract_plan contract validate failed: {exc}")

    ok = bool(
        plan_ok
        and cand_ok
        and hash_ok
        and ep_ok
        and boundary_ok
        and cand_status_ok
        and producer_ok
        and run_ok
        and workflow_ok
        and contract_ok
    )
    # receipt_required=false: pre-finalize gate; receipt_verify failure is informational only.
    msg = "ok" if ok else (
        "extract requires entrypoint_graph + operator_boundary "
        "+ ir/extract_plan.yaml with actor_id/run_id/workflow_id/candidates_sha256 "
        "+ same validate as apply; "
        + "; ".join(errors[:8])
    )
    return {
        "gate": "extract_plan_subagent",
        "ok": ok,
        "has_receipt": has_receipt,
        "receipt_required": False,
        "receipt_verify": verified,
        "receipt_informational": True,
        "has_plan": plan_ok,
        "has_candidates": cand_ok,
        "has_entrypoint_graph": ep_ok,
        "has_operator_boundary": boundary_ok,
        "candidates_status_ok": cand_status_ok,
        "hash_ok": hash_ok,
        "contract_ok": contract_ok,
        "producer_actor_ok": producer_ok,
        "run_id_ok": run_ok,
        "workflow_id_ok": workflow_ok,
        "errors": errors,
        "message": msg,
    }


def gate_input_derivable_closed(uo: Path) -> dict[str, Any]:
    """Host→KEY input_derivable loop must be closed before TG intake."""
    try:
        from ascendc_pilot.legacy_stubs import input_derivable_closure

        detail = input_derivable_closure(uo)
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "input_derivable_closed",
            "ok": False,
            "error": str(exc)[:200],
            "message": "input_derivable closure check failed",
        }
    return {
        "gate": "input_derivable_closed",
        "ok": bool(detail.get("ok")),
        "detail": detail,
        "message": detail.get("message") or ("ok" if detail.get("ok") else "input_derivable open"),
    }


def gate_uo_ready(uo: Path) -> dict[str, Any]:
    """TG intake readiness for the new uo_init KB contract (no old uo.scripts)."""
    manifest = uo / "manifest.yaml"
    integrity_path = uo / "checks" / "integrity.yaml"
    manifest_exists = manifest.is_file() and manifest.stat().st_size > 0
    integrity_exists = integrity_path.is_file() and integrity_path.stat().st_size > 0
    status = ""
    checks: dict[str, Any] = {}
    if integrity_exists:
        try:
            integrity = _load(integrity_path)
        except Exception:  # noqa: BLE001
            return {
                "gate": "uo_ready",
                "ok": False,
                "integrity_status": "",
                "message": "UO KB not ready (integrity.yaml unreadable)",
            }
        ok_status, status = _integrity_status_pass(integrity)
    else:
        ok_status = False
    checks["integrity_pass"] = bool(manifest_exists and integrity_exists and ok_status and status == "pass")

    # SQLite derived index from new engine.
    sqlite_path = uo / "indexes" / "kb_graph.sqlite"
    checks["sqlite_present"] = sqlite_path.is_file()
    checks["sqlite_fresh"] = False
    try:
        import sys

        uo_src = Path(__file__).resolve().parents[3] / "engines" / "understand-operator" / "src"
        if uo_src.is_dir() and str(uo_src) not in sys.path:
            sys.path.insert(0, str(uo_src))
        from uo_init.kb_index import index_summary

        info = index_summary(sqlite_path)
        checks["sqlite_fresh"] = bool(info.get("graph_fingerprint"))
        checks["sqlite_status"] = "fresh" if checks["sqlite_fresh"] else "missing_meta"
        checks["graph_fingerprint"] = info.get("graph_fingerprint")
    except Exception as exc:  # noqa: BLE001
        checks["sqlite_status"] = "error"
        checks["sqlite_error"] = str(exc)[:200]
        if checks["sqlite_present"]:
            checks["sqlite_fresh"] = True  # file exists; meta probe optional

    # New-contract tiling materialize gate.
    exhaustive = {}
    coverage = {}
    reach = {}
    try:
        exhaustive = _load(uo / "tiling" / "exhaustive_key_space.yaml") if (uo / "tiling" / "exhaustive_key_space.yaml").is_file() else {}
        coverage = _load(uo / "tiling" / "coverage_model.yaml") if (uo / "tiling" / "coverage_model.yaml").is_file() else {}
        reach = _load(uo / "tiling" / "key_reachability.yaml") if (uo / "tiling" / "key_reachability.yaml").is_file() else {}
    except Exception as exc:  # noqa: BLE001
        checks["tiling_load_error"] = str(exc)[:200]
    blocks = exhaustive.get("template_blocks") or []
    kfo = coverage.get("key_field_obligations") or {}
    keys = reach.get("keys") or []
    checks["template_blocks"] = len(blocks)
    checks["key_field_obligations"] = len(kfo)
    checks["legal_key_rows"] = len(keys)
    checks["tiling_materialized"] = bool(blocks and kfo and keys)

    branches = {}
    try:
        branches = _load(uo / "kernel" / "branches.yaml") if (uo / "kernel" / "branches.yaml").is_file() else {}
    except Exception:  # noqa: BLE001
        branches = {}
    checks["branch_rows"] = len(branches.get("branches") or [])

    ok = bool(
        checks.get("integrity_pass")
        and checks.get("sqlite_present")
        and checks.get("tiling_materialized")
    )
    reasons = []
    if not checks.get("integrity_pass"):
        reasons.append("integrity")
    if not checks.get("sqlite_present"):
        reasons.append("sqlite")
    if not checks.get("tiling_materialized"):
        reasons.append("tiling_materialize")
    return {
        "gate": "uo_ready",
        "ok": ok,
        "integrity_status": status,
        "checks": checks,
        "message": "ok" if ok else f"UO KB not ready ({','.join(reasons) or 'unknown'})",
    }


def run_key_gates(project_root: Path, *, op_name: str | None = None) -> dict[str, Any]:
    uo = uo_root(project_root, op_name)
    results = [
        gate_key_triage_required(uo),
        gate_key_resolve_receipt(project_root, uo),
        gate_empty_only_producer(uo),
        gate_confidence_report_quality(uo),
        gate_confidence_closed_high(uo),
        gate_confidence_reason_review(uo),
        gate_kb_review_consistency(uo),
    ]
    ok = all(r.get("ok") for r in results)
    payload = {
        "version": 1,
        "ok": ok,
        "uo_root": uo.as_posix(),
        "gates": results,
    }
    out = uo / "checks" / "pilot_key_gates.yaml"
    if yaml is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return payload


def gate_detect_score_pre(uo: Path) -> dict[str, Any]:
    """Pass when pre-semantic score artifacts exist (①)."""
    report = uo / "ir" / "score_report_pre.yaml"
    ep = uo / "ir" / "entrypoint_graph.yaml"
    tasks = uo / "ir" / "llm_tasks.yaml"
    if not ep.is_file():
        return {
            "gate": "detect_score_pre",
            "ok": False,
            "message": "entrypoint_graph missing before detect_score_pre",
        }
    if not report.is_file() or not tasks.is_file():
        return {
            "gate": "detect_score_pre",
            "ok": False,
            "message": "score_report_pre / llm_tasks missing (run detect_score_pre)",
        }
    return {
        "gate": "detect_score_pre",
        "ok": True,
        "has_score_report": True,
        "message": "ok",
    }


def gate_detect_score_post(uo: Path) -> dict[str, Any]:
    """Post-semantic scoring requires plan AND host AND kernel (shared contract)."""
    from ascendc_pilot.legacy_stubs import post_semantic_prerequisites

    prereq = post_semantic_prerequisites(uo)
    post = uo / "ir" / "score_report_post.yaml"
    triage = uo / "ir" / "semantic_task_triage.yaml"
    missing = list(prereq.get("missing") or [])
    if not post.is_file():
        # Gate after engine run also requires the report; engine itself won't write without prereqs.
        missing = missing + (["score_report_post.yaml"] if "score_report_post.yaml" not in missing else [])
    if post.is_file() and not triage.is_file():
        missing = missing + ["semantic_task_triage.yaml"]
    if missing:
        return {
            "gate": "detect_score_post",
            "ok": False,
            "missing": missing,
            "error": "POST_SEMANTIC_PREREQUISITE_MISSING" if prereq.get("missing") else "score_report_post_missing",
            "message": f"detect_score_post requires plan+host+kernel(+report+triage); missing={missing}",
        }
    # Fail-closed on semantic task contract conflicts.
    try:
        from ascendc_pilot.uo_artifacts import read_yaml

        triage_doc = read_yaml(triage) or {}
        conflict_ids = [
            str(r.get("task_id") or "")
            for r in (triage_doc.get("tasks") or triage_doc.get("rows") or [])
            if isinstance(r, dict) and r.get("contract_error")
        ]
        if not conflict_ids:
            llm = read_yaml(uo / "ir" / "llm_tasks.yaml") or {}
            conflict_ids = [
                str(t.get("task_id") or "")
                for t in (llm.get("tasks") or [])
                if isinstance(t, dict) and t.get("contract_error")
            ]
        if conflict_ids:
            return {
                "gate": "detect_score_post",
                "ok": False,
                "error": "SEMANTIC_TASK_CONTRACT_CONFLICT",
                "task_ids": conflict_ids,
                "message": f"semantic task contract conflicts: {conflict_ids[:8]}",
            }
    except Exception:  # noqa: BLE001
        pass
    return {
        "gate": "detect_score_post",
        "ok": True,
        "has_post_report": True,
        "has_triage": True,
        "has_plan": True,
        "has_host": True,
        "has_kernel": True,
        "message": "ok",
    }



def _current_run_id_for_uo(uo: Path, project_root: Path | None = None) -> str:
    """Resolve current run id: Pilot state first, then UO manifest."""
    if project_root is not None:
        try:
            from ascendc_pilot.state import load_state

            st = load_state(project_root) or {}
            rid = str(st.get("run_id") or "").strip()
            if rid:
                return rid
        except Exception:  # noqa: BLE001
            pass
    try:
        import yaml

        raw = yaml.safe_load((uo / "manifest.yaml").read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            return str(raw.get("current_run_id") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def gate_adjudicate_llm_tasks(uo: Path, *, current_run_id: str = "", project_root: Path | None = None) -> dict[str, Any]:
    """Producer patches required when open blocking tasks need LLM (not auto mark_missing).

    Uses the same validate_semantic_patch_set core as Apply (validate-only, no mutate).
    """
    from ascendc_pilot.legacy_stubs import _source_snapshot_hash
    return {"ok": True, "skipped": True, "gate": "legacy_removed", "message": "old semantic/extract_plan gate retired"}

    run_id = str(current_run_id or "").strip() or _current_run_id_for_uo(uo, project_root)
    if not run_id:
        return {
            "gate": "adjudicate_llm_tasks",
            "ok": False,
            "message": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
            "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
        }
    open_blocking = open_blocking_tasks(uo, current_run_id=run_id)
    if not open_blocking:
        return {
            "gate": "adjudicate_llm_tasks",
            "ok": True,
            "skipped": True,
            "message": "no open blocking llm_tasks",
        }

    needs_llm = [t for t in open_blocking if not can_auto_mark_missing(t)]
    if not needs_llm:
        return {
            "gate": "adjudicate_llm_tasks",
            "ok": True,
            "skipped": True,
            "message": "all open blocking are auto mark_missing",
        }

    patches_path = uo / "ir" / "semantic_patches.yaml"
    patches_doc = _load(patches_path) or {}
    raw = patches_doc.get("patches") if isinstance(patches_doc, dict) else None
    if not patches_path.is_file() or not isinstance(raw, list) or not raw:
        return {
            "gate": "adjudicate_llm_tasks",
            "ok": False,
            "message": "semantic_patches.yaml missing; producer must adjudicate open llm_tasks",
            "needs_llm_count": len(needs_llm),
        }

    checked = validate_semantic_patch_set(
        uo,
        [p for p in raw if isinstance(p, dict)],
        _source_snapshot_hash(uo, run_id=run_id),
        current_run_id=run_id,
        require_full_coverage=True,
        mutate=False,
    )
    if not checked.get("ok"):
        return {
            "gate": "adjudicate_llm_tasks",
            "ok": False,
            "message": str(
                checked.get("error") or checked.get("message") or "semantic_patch_validation_failed"
            ),
            "needs_llm_count": len(needs_llm),
            "validation_errors": checked.get("errors") or [],
            "missing_task_ids": checked.get("missing_task_ids") or [],
        }
    return {
        "gate": "adjudicate_llm_tasks",
        "ok": True,
        "needs_llm_count": len(needs_llm),
        "message": "ok",
    }


def gate_apply_semantic_patch(uo: Path, *, current_run_id: str = "", project_root: Path | None = None) -> dict[str, Any]:
    """Post-apply: blocking tasks cleared, or pending patches still valid to apply."""
    from ascendc_pilot.legacy_stubs import _source_snapshot_hash
    return {"ok": True, "skipped": True, "gate": "legacy_removed", "message": "old semantic/extract_plan gate retired"}

    run_id = str(current_run_id or "").strip() or _current_run_id_for_uo(uo, project_root)
    if not run_id:
        return {
            "gate": "apply_semantic_patch",
            "ok": False,
            "message": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
            "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
        }
    open_blocking = open_blocking_tasks(uo, current_run_id=run_id)
    if not open_blocking:
        return {
            "gate": "apply_semantic_patch",
            "ok": True,
            "skipped": True,
            "message": "no open blocking llm_tasks after apply",
        }

    patches_path = uo / "ir" / "semantic_patches.yaml"
    patches_doc = _load(patches_path) if patches_path.is_file() else None
    resolved = resolve_patches_for_apply(
        uo,
        current_run_id=run_id,
        patches_doc=patches_doc if isinstance(patches_doc, dict) else None,
    )
    if not resolved.get("ok"):
        return {
            "gate": "apply_semantic_patch",
            "ok": False,
            "message": str(resolved.get("error") or resolved.get("message") or "patches_unresolved"),
            **{k: v for k, v in resolved.items() if k not in {"ok"}},
        }

    patches = list(resolved.get("patches") or [])
    if not patches:
        return {
            "gate": "apply_semantic_patch",
            "ok": False,
            "open_blocking": len(open_blocking),
            "message": "open blocking remain but no patches to apply",
        }

    checked = validate_semantic_patch_set(
        uo,
        patches,
        _source_snapshot_hash(uo, run_id=run_id),
        current_run_id=run_id,
        require_full_coverage=True,
        mutate=False,
    )
    if checked.get("ok"):
        return {
            "gate": "apply_semantic_patch",
            "ok": False,
            "open_blocking": len(open_blocking),
            "message": "patches still applicable; apply_semantic_patch did not close blocking tasks",
            "patch_count": len(patches),
        }
    return {
        "gate": "apply_semantic_patch",
        "ok": False,
        "open_blocking": len(open_blocking),
        "message": "open blocking remain after apply",
        "validation_errors": checked.get("errors") or [],
    }


def gate_semantic_closure(uo: Path, *, current_run_id: str = "", project_root: Path | None = None) -> dict[str, Any]:
    """Blocking semantic gaps uncleared → cannot advance; recheck does not bump attempts (⑥)."""
    return {"ok": True, "skipped": True, "gate": "legacy_removed", "message": "old semantic/extract_plan gate retired"}

    run_id = str(current_run_id or "").strip() or _current_run_id_for_uo(uo, project_root)
    if not run_id:
        return {
            "gate": "semantic_closure",
            "ok": False,
            "message": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
            "error": "SEMANTIC_DOCUMENT_RUN_ID_MISSING",
        }
    stats = compute_semantic_stats(uo, current_run_id=run_id)
    gaps = blocking_gap_tasks(uo, current_run_id=run_id)
    batches = int((_load(uo / "ir" / "llm_tasks.yaml") or {}).get("total_semantic_batches") or 0)
    max_batches = MAX_SEMANTIC_BATCHES
    if gaps and batches < max_batches:
        return {
            "gate": "semantic_closure",
            "ok": False,
            "blocking_gap_count": len(gaps),
            "open_blocking": len(gaps),
            "total_semantic_batches": batches,
            "message": f"blocking semantic gaps={len(gaps)}; resolve before advance",
        }
    if gaps and batches >= max_batches:
        return {
            "gate": "semantic_closure",
            "ok": False,
            "blocking_gap_count": len(gaps),
            "open_blocking": len(gaps),
            "total_semantic_batches": batches,
            "message": "semantic batch budget exhausted with blocking gaps remaining",
        }
    if int(stats.get("unconsumed_patch_count") or 0) > 0:
        return {
            "gate": "semantic_closure",
            "ok": False,
            "blocking_gap_count": len(gaps),
            "unconsumed_patch_count": stats.get("unconsumed_patch_count"),
            "message": "unconsumed semantic patches remain; rebuild_from_ledger required",
        }
    return {
        "gate": "semantic_closure",
        "ok": True,
        "total_semantic_batches": batches,
        "blocking_gap_count": 0,
        "message": "ok",
    }


def gate_layout_receipt(uo: Path) -> dict[str, Any]:
    man = uo / "manifest.yaml"
    op = uo / "operator.yaml"
    ok = man.is_file() and op.is_file()
    return {
        "gate": "layout_receipt",
        "ok": ok,
        "message": "ok" if ok else "manifest.yaml or operator.yaml missing",
    }


def gate_scope_probe_clean(uo: Path) -> dict[str, Any]:
    cand = uo / "summary" / "scope_candidates.yaml"
    if not cand.is_file():
        # also accept run-scoped copy via any runs/*/scope/candidates.yaml
        runs = list((uo / "runs").glob("*/scope/candidates.yaml")) if (uo / "runs").is_dir() else []
        if not runs:
            return {"gate": "scope_probe_clean", "ok": False, "message": "scope candidates missing"}
        cand = runs[0]
    doc = _load(cand)
    ok = bool(doc.get("probe_clean"))
    return {
        "gate": "scope_probe_clean",
        "ok": ok,
        "message": "ok" if ok else "libclang probe not clean",
        "host_probe_errors": doc.get("host_probe_errors"),
        "kernel_probe_errors": doc.get("kernel_probe_errors"),
    }


def gate_extract_receipt(uo: Path) -> dict[str, Any]:
    host = uo / "ir" / "host_extract_receipt.yaml"
    fold = uo / "kernel" / "fold_receipt.yaml"
    ok = host.is_file() and fold.is_file()
    return {
        "gate": "extract_receipt",
        "ok": ok,
        "message": "ok" if ok else "host/kernel extract receipt missing",
    }


def gate_normalize_receipt(uo: Path) -> dict[str, Any]:
    unresolved = uo / "ir" / "unresolved.yaml"
    patch = uo / "ir" / "gap_patch_receipt.yaml"
    ok = unresolved.is_file() and patch.is_file()
    return {
        "gate": "normalize_receipt",
        "ok": ok,
        "message": "ok" if ok else "unresolved.yaml or gap_patch_receipt missing",
    }


def gate_gap_patch_evidence(uo: Path, project_root: Path | None = None) -> dict[str, Any]:
    """Pass when gaps skipped, or every patch row was validated and loop did not regress."""
    del project_root
    resolve_receipt = uo / "ir" / "resolve_gaps_receipt.yaml"
    patch_receipt = uo / "ir" / "gap_patch_receipt.yaml"
    unresolved = _load(uo / "ir" / "unresolved.yaml")
    count = int(unresolved.get("blocker_count") or len(unresolved.get("blockers") or []))
    if count == 0 or unresolved.get("status") == "closed":
        return {"gate": "gap_patch_evidence", "ok": True, "skipped": True, "blocker_count": 0}
    if not resolve_receipt.is_file():
        return {
            "gate": "gap_patch_evidence",
            "ok": False,
            "message": "resolve_gaps receipt missing while blockers remain",
            "blocker_count": count,
        }
    resolve_doc = _load(resolve_receipt)
    if resolve_doc.get("skipped") or resolve_doc.get("deferred"):
        return {
            "gate": "gap_patch_evidence",
            "ok": bool(resolve_doc.get("ok", True)),
            "skipped": True,
            "blocker_count": count,
        }
    if not patch_receipt.is_file():
        return {
            "gate": "gap_patch_evidence",
            "ok": False,
            "message": "gap_patch_receipt missing after resolve_gaps",
            "blocker_count": count,
        }
    patch_doc = _load(patch_receipt)
    loop = patch_doc.get("loop") or {}
    rejected = patch_doc.get("rejected") or []
    # Format / vocabulary rejects are fine (ok=True overall); loop regression is not.
    ok = bool(patch_doc.get("ok", True)) and bool(loop.get("ok", True))
    return {
        "gate": "gap_patch_evidence",
        "ok": ok,
        "skipped": bool(patch_doc.get("skipped")),
        "blocker_count": count,
        "applied": int(patch_doc.get("applied") or 0),
        "rejected": len(rejected),
        "loop": loop,
        "message": "ok" if ok else "gap patch loop regress or receipt not ok",
    }


def run_named_gate(project_root: Path, gate_id: str, *, op_name: str | None = None) -> dict[str, Any]:
    """Dispatch a workflow registry gate id to a concrete checker."""
    from ascendc_pilot.gates import tg_adapters

    uo = uo_root(project_root, op_name)
    mapping = {
        "prepare_layout_receipt": lambda: gate_prepare_layout_receipt(project_root),
        "layout_receipt": lambda: gate_layout_receipt(uo),
        "scope_probe_clean": lambda: gate_scope_probe_clean(uo),
        "extract_receipt": lambda: gate_extract_receipt(uo),
        "normalize_receipt": lambda: gate_normalize_receipt(uo),
        "gap_patch_evidence": lambda: gate_gap_patch_evidence(uo, project_root),
        "key_triage_required": lambda: gate_key_triage_required(uo),
        "key_resolve_receipt": lambda: gate_key_resolve_receipt(project_root, uo),
        "empty_only_producer": lambda: gate_empty_only_producer(uo),
        "key_report_quality": lambda: gate_confidence_report_quality(uo),
        "confidence_closed_high": lambda: gate_confidence_closed_high(uo),
        "confidence_reason_review": lambda: gate_confidence_reason_review(uo),
        "confidence_gate": lambda: gate_confidence_gate_file(uo),
        "integrity": lambda: gate_integrity_file(uo),
        "kb_review": lambda: gate_kb_review_file(uo),
        "kb_review_consistency": lambda: gate_kb_review_consistency(uo),
        "scope_receipt": lambda: gate_scope_receipt(project_root, uo),
        "extract_plan_subagent": lambda: gate_extract_plan_subagent(project_root, uo),
        "detect_score_pre": lambda: gate_detect_score_pre(uo),
        "detect_score_post": lambda: gate_detect_score_post(uo),
        "adjudicate_llm_tasks": lambda: gate_adjudicate_llm_tasks(uo, project_root=project_root),
        "apply_semantic_patch": lambda: gate_apply_semantic_patch(uo, project_root=project_root),
        "semantic_closure": lambda: gate_semantic_closure(uo, project_root=project_root),
        "uo_ready": lambda: gate_uo_ready(uo),
        "kb_ready": lambda: gate_uo_ready(uo),
        "input_derivable_closed": lambda: gate_input_derivable_closed(uo),
        "family_path_obligation": lambda: tg_adapters.gate_family_path_obligation(project_root),
        "context_pack": lambda: {
            "gate": "context_pack",
            "ok": (project_root / ".ascendc-pilot" / "context" / "context_pack.yaml").is_file(),
            "message": "ok"
            if (project_root / ".ascendc-pilot" / "context" / "context_pack.yaml").is_file()
            else "context pack missing",
        },
        # TG — real engine adapters (kb_fingerprint is NOT an alias of uo_ready)
        "tg_init_confirmed": lambda: tg_adapters.gate_init_confirmed(project_root, op_name=op_name),
        "init_confirmed": lambda: tg_adapters.gate_init_confirmed(project_root, op_name=op_name),
        "plan_approved": lambda: tg_adapters.gate_plan_approved(project_root),
        "kb_fingerprint": lambda: tg_adapters.gate_kb_fingerprint_matches(project_root),
        "kb_fingerprint_fresh": lambda: tg_adapters.gate_kb_fingerprint_fresh(project_root, op_name=op_name),
        "merge_pass": lambda: tg_adapters.gate_merge_pass(project_root),
        "bind_progress": lambda: tg_adapters.gate_bind_progress(project_root),
        "domain_symmetry": lambda: tg_adapters.gate_domain_symmetry(project_root),
        "csv_closure": lambda: tg_adapters.gate_csv_closure(project_root),
        "audit_pass": lambda: tg_adapters.gate_audit_pass(project_root),
        "allow_solve": lambda: tg_adapters.gate_allow_solve(project_root),
        "solve_terminal": lambda: tg_adapters.gate_solve_terminal(project_root),
    }
    fn = mapping.get(gate_id)
    if fn is None:
        return {"gate": gate_id, "ok": False, "message": f"unknown gate id: {gate_id}"}
    return fn()


def _gate_tg_status(project_root: Path, *, want: str) -> dict[str, Any]:
    """Deprecated shallow helper — prefer tg_adapters.gate_init_confirmed."""
    return {
        "gate": "tg_init_confirmed",
        "ok": False,
        "message": f"use tg_adapters; legacy want={want!r}",
    }


def _gate_tg_plan_approved(project_root: Path) -> dict[str, Any]:
    from ascendc_pilot.gates import tg_adapters

    return tg_adapters.gate_plan_approved(project_root)


def run_workflow_gates(project_root: Path, *, gate_ids: list[str] | None = None) -> dict[str, Any]:
    from ascendc_pilot.state import load_state
    from ascendc_pilot.workflows import get_workflow

    state = load_state(project_root)
    wid = str(state.get("workflow_id") or "")
    if not wid:
        return {"ok": False, "error": "no_active_workflow", "gates": []}
    meta = get_workflow(wid)
    ids = list(gate_ids if gate_ids is not None else (meta.get("gates") or []))
    results = [run_named_gate(project_root, gid) for gid in ids]
    ok = all(r.get("ok") for r in results)
    return {
        "version": 1,
        "ok": ok,
        "workflow_id": wid,
        "phase": state.get("phase"),
        "gates": results,
    }


# --- KEY patch rejection helpers (apply / classify) ---

def evidence_blob(item: dict[str, Any]) -> str:
    parts = [
        str(item.get(k) or "")
        for k in ("producer", "producers", "evidence", "file_path", "path", "reason", "host_parent", "notes", "rationale", "host_parent_evidence")
    ]
    for key in ("producers", "evidence_paths", "paths"):
        val = item.get(key)
        if isinstance(val, list):
            parts.extend(str(x) for x in val)
    resolution = item.get("resolution")
    if isinstance(resolution, dict):
        parts.append(str(resolution))
    return " ".join(parts).lower()


def is_empty_only_producer(item: dict[str, Any]) -> bool:
    blob = evidence_blob(item)
    has_empty = any(m in blob for m in EMPTY_PATH_MARKERS)
    has_main = any(m in blob for m in MAIN_TILING_ANCHORS)
    return has_empty and not has_main


def reject_key_closure_item(item: dict[str, Any], *, require_receipt_context: bool = False) -> str | None:
    """Return rejection reason for a KEY closure patch item, or None if allowed."""
    kid = str(item.get("id") or item.get("key") or item.get("key_id") or item.get("target") or "")
    status = str(item.get("status") or item.get("disposition") or item.get("input_derivable") or "").lower()
    conf = str(item.get("confidence") or "").lower()
    closing = status in {"accepted", "resolved", "closed", "true", "false", "not_input_derivable", "input_derivable"}
    closing = closing or item.get("input_derivable") is True or item.get("input_derivable") is False
    closing = closing or item.get("not_input_derivable") is True
    if conf == "high":
        closing = True
    if not closing:
        return None
    if is_empty_only_producer(item):
        return "empty_only_producer: missing_producer evidence only on empty tiling path; escalate to main GetTilingKey/SaveToTilingData path"
    if require_receipt_context and kid.upper().startswith("KEY_"):
        # Caller should also check triage/receipt at batch level; per-item flag for clarity
        return None
    return None


def reject_key_patch_batch(
    project_root: Path,
    uo: Path,
    items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Reject KEY closures when empty-only or triage/receipt missing."""
    rejected: list[dict[str, str]] = []
    closing_keys: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kid = str(it.get("id") or it.get("key") or it.get("key_id") or it.get("target") or "")
        reason = reject_key_closure_item(it)
        if reason:
            rejected.append({"id": kid or "?", "reason": reason})
            continue
        status = str(it.get("status") or it.get("input_derivable") or "").lower()
        conf = str(it.get("confidence") or "").lower()
        is_close = (
            status in {"accepted", "resolved", "closed", "true", "false", "not_input_derivable", "input_derivable"}
            or it.get("input_derivable") in (True, False)
            or it.get("not_input_derivable") is True
            or conf == "high"
        )
        if is_close and kid.upper().startswith(("KEY_", "KVAR_")):
            closing_keys.append(kid)

    if closing_keys:
        triage = gate_key_triage_required(uo)
        receipt = gate_key_resolve_receipt(project_root, uo)
        # If gaps/escalate need triage, refuse parent-written closures without resolve work
        if triage.get("needs_triage") and not receipt.get("ok"):
            for kid in closing_keys:
                rejected.append(
                    {
                        "id": kid,
                        "reason": "key_resolve_receipt_missing: parent must not accept KEY patches without uo-key-resolve triage/artifacts",
                    }
                )
        elif triage.get("needs_triage") and not triage.get("ok"):
            for kid in closing_keys:
                rejected.append(
                    {
                        "id": kid,
                        "reason": "key_triage_missing: ir/key_triage.yaml required before accepting KEY closures",
                    }
                )
    # Dedupe
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for row in rejected:
        key = f"{row['id']}:{row['reason']}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)
    return uniq
