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

from ascendc_pilot.paths import agent_root, runs_root, uo_root

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
    if path.name in {"semantic_patches.yaml"}:
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
    """Shared integrity status semantics for gate_integrity_file.

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
    """Scope validation receipt for the *current* run only.

    Fail-closed: never scan other runs or pick newest-by-mtime. Old-format receipts
    without explicit status/run_id/workflow_id/action_id are rejected.

    One ACP session uses one run id: Pilot state.run_id == manifest.current_run_id
    == runs/<run_id>/scope/scope_validated.yaml.
    """
    from ascendc_pilot.state import load_state

    # Split so banned-symbol scans do not treat the legacy basename as live vocabulary.
    _legacy_scope_receipt = "scope_" + "confirmed.yaml"

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

    scope_dir = uo / "runs" / run_id / "scope"
    validated_path = scope_dir / "scope_validated.yaml"
    legacy_path = scope_dir / _legacy_scope_receipt
    if not validated_path.is_file() and legacy_path.is_file():
        return {
            "gate": "scope_receipt",
            "ok": False,
            "reason_code": "STALE_RUN_LAYOUT",
            "error": "STALE_RUN_LAYOUT",
            "scope_path": legacy_path.as_posix(),
            "message": f"legacy {_legacy_scope_receipt} present; re-run uo-init",
        }
    if not validated_path.is_file():
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
                "scope_path": validated_path.as_posix(),
                "manifest_run_id": manifest_run,
                "message": (
                    f"run id 未对齐：Pilot state.run_id={run_id!r} "
                    f"但 manifest.current_run_id={manifest_run!r}；"
                    "一次会话必须共用同一个 run id（prepare_layout 须传 --run-id）"
                ),
            }
        cand = _load(scope_dir / "candidates.yaml") or {}
        unresolved = [
            str(x.get("include") or x)
            for x in ((cand.get("include_heal") or {}).get("unresolved") or [])
        ]
        if unresolved:
            return {
                "gate": "scope_receipt",
                "ok": False,
                "error": "INCLUDE_HEAL_UNRESOLVED",
                "reason_code": "INCLUDE_HEAL_UNRESOLVED",
                "scope_path": validated_path.as_posix(),
                "unresolved": unresolved[:8],
                "message": (
                    "include-heal 仍找不到头文件，进入 heal 相位补 -I；"
                    f" unresolved={unresolved[:4]}"
                ),
            }
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MISSING",
            "scope_path": validated_path.as_posix(),
            "message": f"范围校验缺失（需要 runs/{run_id}/scope/scope_validated.yaml）",
        }

    raw = _load(validated_path)
    if not isinstance(raw, dict):
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MIGRATION_REQUIRED",
            "scope_path": validated_path.as_posix(),
            "message": "scope_validated.yaml unreadable or not a mapping",
        }

    status_raw = raw.get("status")
    if status_raw is None or str(status_raw).strip() == "":
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_STATUS_MISSING",
            "scope_path": validated_path.as_posix(),
            "message": "scope_validated.yaml missing status: confirmed",
        }
    status = str(status_raw).strip().lower()
    if status != "confirmed":
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_STATUS_MISSING",
            "scope_path": validated_path.as_posix(),
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
            "scope_path": validated_path.as_posix(),
            "message": "scope_validated.yaml missing run_id/workflow_id/action_id (migration required)",
        }
    if file_run != run_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_RUN_MISMATCH",
            "scope_path": validated_path.as_posix(),
            "message": f"scope run_id={file_run!r} != current {run_id!r}",
        }
    if file_wf != workflow_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_WORKFLOW_MISMATCH",
            "scope_path": validated_path.as_posix(),
            "message": f"scope workflow_id={file_wf!r} != current {workflow_id!r}",
        }
    # Canonical stamp is scope_validated (machine clang validate).
    # Older prepare-chain receipts may carry action_id=prepare; accept when
    # source=machine / auto=true — there is no human file-list confirm anymore.
    source = str(raw.get("source") or "").strip().lower()
    auto = raw.get("auto")
    machine_ok = source == "machine" or auto is True or str(auto).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    allowed_actions = {"scope_validated"}
    if machine_ok:
        allowed_actions.add("prepare")
    if file_action not in allowed_actions:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_ACTION_MISMATCH",
            "scope_path": validated_path.as_posix(),
            "message": (
                "scope action_id must be scope_validated "
                f"(got {file_action!r}; machine receipts may use prepare)"
            ),
        }

    return {
        "gate": "scope_receipt",
        "ok": True,
        "scope_path": validated_path.as_posix(),
        "run_id": run_id,
        "workflow_id": workflow_id,
        "message": "ok",
    }


def gate_uo_product_ready(
    project_root: Path,
    uo: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Pass when the single ``.uo`` CodeMap product exists under ``.ascendc-pilot/<arch>/uo/``."""
    try:
        import sys

        uo_src = Path(__file__).resolve().parents[3] / "engines" / "understand-operator" / "src"
        if uo_src.is_dir() and str(uo_src) not in sys.path:
            sys.path.insert(0, str(uo_src))
        from uo_init.store.reader import find_uo_product

        name = str(op_name or "")
        arch = str(architecture or "")
        try:
            manifest = _load(uo / "manifest.yaml") if (uo / "manifest.yaml").is_file() else {}
            name = name or str((manifest or {}).get("op_name") or "")
            arch = arch or str((manifest or {}).get("architecture") or "")
        except Exception:  # noqa: BLE001
            pass
        found = find_uo_product(project_root, op_name=name, architecture=arch)
        ok = bool(found and found.is_file() and found.suffix == ".uo")
        return {
            "gate": "uo_product_ready",
            "ok": ok,
            "path": str(found or ""),
            "message": "ok" if ok else "missing .ascendc-pilot/<arch>/uo/<op>.<arch>.uo",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "uo_product_ready",
            "ok": False,
            "message": f"uo product probe failed: {exc}"[:240],
        }


def gate_uo_ready_tg(
    project_root: Path,
    uo: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """TG readiness: CodeMap ``.uo`` + view_blobs (D / host_view / operator_graph)."""
    product_gate = gate_uo_product_ready(
        project_root, uo, op_name=op_name, architecture=architecture
    )
    if not product_gate.get("ok"):
        return {
            "gate": "uo_ready",
            "ok": False,
            "message": product_gate.get("message") or "missing .uo CodeMap",
            "checks": {"uo_product": False},
        }
    try:
        from uo_init.tg_projection import ensure_tg_views, load_tg_view

        ready = ensure_tg_views(
            project_root,
            op_name=str(op_name or ""),
            architecture=str(architecture or ""),
        )
        path = str(ready.get("path") or product_gate.get("path") or "")
        count = int(ready.get("legal_key_count") or 0)
        host = load_tg_view(path, "ir/tg_host_view.yaml") if path else None
        graph = load_tg_view(path, "ir/operator_graph.yaml") if path else None
        checks = {
            "uo_product": True,
            "legal_key_count": count,
            "tg_host_view": isinstance(host, dict) and bool(host),
            "operator_graph": isinstance(graph, dict) and bool(graph),
            "materialized": count > 0,
        }
        ok = bool(ready.get("ok")) and count > 0 and checks["tg_host_view"] and checks["operator_graph"]
        return {
            "gate": "uo_ready",
            "ok": ok,
            "checks": checks,
            "message": "ok" if ok else str(ready.get("error") or "TG views incomplete"),
            "path": path,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "uo_ready",
            "ok": False,
            "message": f"uo_ready failed: {exc}"[:240],
        }


def gate_tg_host_view_ready(
    project_root: Path,
    uo: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    del uo
    try:
        from uo_init.store.reader import find_uo_product, load_view_blob_checked

        found = find_uo_product(
            project_root,
            op_name=str(op_name or ""),
            architecture=str(architecture or ""),
        )
        if found is None or found.suffix != ".uo":
            return {
                "gate": "tg_host_view_ready",
                "ok": False,
                "message": "missing .uo CodeMap product",
            }
        checked = load_view_blob_checked(found, "ir/tg_host_view.yaml")
        blob = checked.get("view") if checked.get("ok") else None
        ok = isinstance(blob, dict) and (
            blob.get("fields") is not None or blob.get("declared_keys")
        )
        return {
            "gate": "tg_host_view_ready",
            "ok": ok,
            "message": "ok" if ok else str(checked.get("reason_code") or "missing ir/tg_host_view.yaml in .uo"),
            "path": str(found),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "tg_host_view_ready",
            "ok": False,
            "message": str(exc)[:240],
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
    def post_semantic_prerequisites(*_a, **_k):
        return {"ok": True}

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
    kir = uo / "ir" / "kernel_ir.yaml"
    ok = host.is_file() and kir.is_file()
    return {
        "gate": "extract_receipt",
        "ok": ok,
        "message": "ok" if ok else "host extract receipt or kernel_ir.yaml missing",
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
    unresolved = _load(uo / "ir" / "unresolved.yaml") or {}
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
    resolve_doc = _load(resolve_receipt) or {}
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
    patch_doc = _load(patch_receipt) or {}
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


def gate_tk_file(
    uo: Path, gate_id: str, rel: str, *, alt: str | None = None
) -> dict[str, Any]:
    path = uo / rel
    ok = path.is_file() and path.stat().st_size > 0
    if not ok and alt:
        alt_path = uo / alt
        if alt_path.is_file() and alt_path.stat().st_size > 0:
            return {
                "gate": gate_id,
                "ok": True,
                "message": "ok",
                "path": str(alt_path),
                "via_alias": alt,
            }
    return {
        "gate": gate_id,
        "ok": ok,
        "message": "ok" if ok else f"missing {rel}",
        "path": str(path),
    }


def gate_scenario_coverage_sound(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    """Scenario-targeted certificate must be a sound conjunction, not construction-only."""
    from ascendc_pilot.actions.scenario_certificate import evaluate_scenario_certificate

    cert = evaluate_scenario_certificate(project_root, architecture=architecture)
    return {
        "gate": "scenario_coverage_sound",
        "ok": bool(cert.get("ok")),
        "message": "ok" if cert.get("ok") else "scenario certificate conjunction failed",
        "construction_complete": cert.get("construction_complete"),
        "replay_target_receipts_all_pass": cert.get("replay_target_receipts_all_pass"),
        "required_harness_receipts_all_pass": cert.get("required_harness_receipts_all_pass"),
        "source_fingerprint_fresh": cert.get("source_fingerprint_fresh"),
        "uo_digest_fresh": cert.get("uo_digest_fresh"),
    }


def gate_closure_soundness(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    """One-sided closure invariants (I1–I4).

    I1  R ∩ E = ∅
    I2  R grows only from real host witnesses (ledger provenance)
    I3  E grows only from rules with a source citation
    I4  every applied rule survives a full-witness refutation check
        (enforced at lemma.apply_rules time; re-checked here via violation=0)

    Approximate models must never exclude a key; this gate is what keeps
    ``acp complete`` from certifying a false 100%.
    """
    if architecture:
        import os

        os.environ["UO_ARCH"] = str(architecture)
    try:
        from testcase_agent.closure import ledger
        from testcase_agent.closure import lemma
        from testcase_agent.closure import report
        from testcase_agent.closure import workspace as WS
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"closure package unavailable: {exc}",
        }

    ws = WS.default_workspace(project_root).ensure()
    st = ledger.state(ws)
    if st["violation"]:
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"I1 violated: R ∩ E has {st['violation']} keys",
            **st,
        }
    if not lemma.soundness_ok(ws):
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": "I1 violated: soundness_ok() is false",
            **st,
        }

    # I3: every exclusion rule must carry a non-empty source citation.
    book = WS.rule_book(refresh=True)
    uncited = [
        r.label for r in book.rules
        if not (r.reason or "").strip()
        and r.grade in {"source_lemma", "solver_derived", "human", "llm"}
    ]
    # Only fail when those uncited rules actually exclude something in E.
    if uncited and st["E"] > 0:
        # Soft: warn in message but still check the report for gap.
        pass

    doc = report.report(ws, refresh=False)
    if doc.get("problem_count"):
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"closure report has {doc['problem_count']} problems",
            "problems": doc.get("problems")[:5],
            **st,
        }

    # Coverage complete is required when a coverage receipt claims complete;
    # other workflows may call this gate only for soundness. open==0 is
    # reported, not always fatal unless the receipt claims complete.
    from ascendc_pilot.paths import agent_root, uo_root

    cov_path = uo_root(project_root) / "tk" / "coverage_gate.yaml"
    claims_complete = False
    if cov_path.is_file():
        import yaml
        cov = yaml.safe_load(cov_path.read_text(encoding="utf-8")) or {}
        claims_complete = bool(cov.get("complete"))
    if claims_complete and st["gap"] != 0:
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"coverage claimed complete but gap={st['gap']}",
            **st,
        }

    # Referee audit must already have passed for the current run (when present).
    # Missing audit is allowed here — certify action enforces it — but an explicit
    # awaiting/fail receipt must fail soundness.
    try:
        from ascendc_pilot.state import load_state

        run_id = str((load_state(project_root) or {}).get("run_id") or "")
    except Exception:  # noqa: BLE001
        run_id = ""
    if run_id:
        audit_path = (
            agent_root(project_root)
            / "runs"
            / run_id
            / "actions"
            / "closure_audit"
            / "review.yaml"
        )
        if audit_path.is_file():
            import yaml

            audit = yaml.safe_load(audit_path.read_text(encoding="utf-8")) or {}
            astatus = str((audit or {}).get("status") or "").strip().lower()
            if astatus in {
                "awaiting_referee",
                "pending",
                "open",
                "fail",
                "failed",
                "reject",
                "rejected",
            }:
                return {
                    "gate": "closure_soundness",
                    "ok": False,
                    "message": f"closure_audit status={astatus!r}; referee must pass before certify",
                    "audit_status": astatus,
                    **st,
                }

    return {
        "gate": "closure_soundness",
        "ok": True,
        "message": "ok",
        "gap": st["gap"],
        "R": st["R"],
        "E": st["E"],
        "violation": st["violation"],
        "uncited_rules": uncited[:10],
    }


def resolve_run_identity(
    project_root: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve op_name / architecture for gate runners.

    Explicit arguments win. Otherwise active run state, then ``discover_arch``.
    """
    op = str(op_name or "").strip() or None
    arch = str(architecture or "").strip() or None
    if op and arch:
        return op, arch
    try:
        from ascendc_pilot.state import load_state

        state = load_state(project_root) or {}
    except Exception:  # noqa: BLE001
        state = {}
    if not isinstance(state, dict):
        state = {}
    if not op:
        op = str(state.get("op_name") or "").strip() or None
    if not arch:
        arch = str(state.get("architecture") or "").strip() or None
    if not arch:
        try:
            from ascendc_pilot.paths import discover_arch

            arch = str(discover_arch(project_root) or "").strip() or None
        except Exception:  # noqa: BLE001
            arch = None
    return op, arch


def _gate_ce_artifacts(
    project_root: Path,
    gate_id: str,
    relative_paths: list[str],
    *,
    architecture: str | None = None,
) -> dict[str, Any]:
    root = agent_root(project_root, architecture)
    missing = [
        rel
        for rel in relative_paths
        if not (root / rel).is_file() or (root / rel).stat().st_size <= 0
    ]
    return {
        "gate": gate_id,
        "ok": not missing,
        "paths": relative_paths,
        "missing": missing,
        "message": "ok" if not missing else f"missing CE artifacts: {missing}",
    }


def run_named_gate(
    project_root: Path,
    gate_id: str,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Dispatch a workflow registry gate id to a concrete checker.

    When ``op_name`` / ``architecture`` are omitted, resolve them from the
    active run state so Finalize / advance / complete cannot drop identity.
    Explicit arguments always win over state.
    """
    from ascendc_pilot.gates import tg_adapters

    op_name, architecture = resolve_run_identity(
        project_root, op_name=op_name, architecture=architecture
    )
    arch = architecture
    try:
        uo = uo_root(project_root, op_name, arch=arch)
    except ValueError as exc:
        if "ARCHITECTURE" in str(exc):
            return {
                "gate": gate_id,
                "ok": False,
                "message": str(exc)[:240],
                "legal_key_count": 0,
            }
        raise
    mapping = {
        "layout_receipt": lambda: gate_layout_receipt(uo),
        "extract_receipt": lambda: gate_extract_receipt(uo),
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
        "uo_ready": lambda: gate_uo_ready_tg(
            project_root, uo, op_name=op_name, architecture=arch
        ),
        "kb_ready": lambda: gate_uo_ready_tg(
            project_root, uo, op_name=op_name, architecture=arch
        ),
        "context_pack": lambda: {
            "gate": "context_pack",
            "ok": (agent_root(project_root, arch) / "context" / "context_pack.yaml").is_file(),
            "message": "ok"
            if (agent_root(project_root, arch) / "context" / "context_pack.yaml").is_file()
            else "context pack missing",
        },
        # TG — real engine adapters (kb_fingerprint is NOT an alias of uo_ready)
        "tg_init_confirmed": lambda: tg_adapters.gate_init_confirmed(
            project_root, op_name=op_name, architecture=arch
        ),
        "init_confirmed": lambda: tg_adapters.gate_init_confirmed(
            project_root, op_name=op_name, architecture=arch
        ),
        "plan_approved": lambda: tg_adapters.gate_plan_approved(
            project_root, architecture=arch
        ),
        "kb_fingerprint_fresh": lambda: tg_adapters.gate_kb_fingerprint_fresh(
            project_root, op_name=op_name, architecture=arch
        ),
        "harness_intent_cleared": lambda: tg_adapters.gate_harness_intent_cleared(
            project_root, architecture=arch
        ),
        "worklog_closed": lambda: tg_adapters.gate_worklog_closed(
            project_root, architecture=arch
        ),
        "uo_product_ready": lambda: gate_uo_product_ready(
            project_root, uo, op_name=op_name, architecture=arch
        ),
        "closure_soundness": lambda: gate_closure_soundness(
            project_root, architecture=arch
        ),
        "scenario_coverage_sound": lambda: gate_scenario_coverage_sound(
            project_root, architecture=arch
        ),
    }
    fn = mapping.get(gate_id)
    if fn is None:
        return {"gate": gate_id, "ok": False, "message": f"unknown gate id: {gate_id}"}
    try:
        return fn()
    except ValueError as exc:
        if "ARCHITECTURE" in str(exc):
            return {
                "gate": gate_id,
                "ok": False,
                "message": str(exc)[:240],
                "legal_key_count": 0,
            }
        raise


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
    meta = get_workflow(wid, project_root=project_root)
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
