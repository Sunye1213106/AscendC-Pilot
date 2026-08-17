"""Deterministic engine entrypoints invoked only by acp run-action."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable


EngineFn = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _uo(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import uo_root

    return uo_root(project_root, arch=arch)


def _tg(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import tg_root

    return tg_root(project_root, arch=arch)


def _ctx_root(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import context_root

    return context_root(project_root, arch=arch)


def _ce(project_root: Path, *, arch: str | None = None) -> Path:
    from ascendc_pilot.paths import agent_root

    return agent_root(project_root, arch) / "ce"


def _resolve_ce_arch(project_root: Path, ctx: dict[str, Any]) -> str:
    from ascendc_pilot.paths import discover_arch

    return str(ctx.get("architecture") or "").strip() or discover_arch(project_root)


def _dump_ce_yaml(path: Path, doc: Any) -> Path:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _write_run_receipt(
    project_root: Path,
    ctx: dict[str, Any] | None,
    filename: str,
    payload: dict[str, Any],
) -> Path:
    """Write a gate/check receipt under ``runs/<run_id>/receipts/``."""
    import yaml

    from ascendc_pilot.runs import receipts_dir

    ctx = dict(ctx or {})
    run_id = str(ctx.get("run_id") or "").strip()
    if not run_id:
        try:
            from ascendc_pilot.state import load_state

            st = load_state(project_root) or {}
            run_id = str(st.get("run_id") or "").strip()
            for key in ("workflow_id", "action_id", "architecture"):
                if not ctx.get(key) and st.get(key):
                    ctx[key] = st.get(key)
        except Exception:  # noqa: BLE001
            run_id = ""
    body = dict(payload)
    body.setdefault("kind", "receipt")
    if run_id:
        body.setdefault("run_id", run_id)
    for key in ("workflow_id", "action_id", "architecture"):
        val = ctx.get(key)
        if val and key not in body:
            body[key] = val
    out = receipts_dir(project_root, run_id or None) / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def _run_ce_change_capture(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.change.capture import capture

    arch = _resolve_ce_arch(project_root, ctx)
    out = _ce(project_root, arch=arch) / "impact" / "change_capture.yaml"
    try:
        payload = capture(
            project_root,
            base=str(ctx.get("base") or "HEAD"),
            head=str(ctx.get("head") or ""),
            architecture=arch,
            output=out,
        )
        return {"ok": out.is_file(), "engine": "change_capture", "artifact": out.as_posix(), **payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "change_capture", "error": str(exc)[:400]}


def _run_ce_uo_freshness(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.change.freshness import check_freshness
    from code_engineering.product_uo import identity

    arch = _resolve_ce_arch(project_root, ctx)
    try:
        product_identity = identity(project_root, architecture=arch)
    except (FileNotFoundError, RuntimeError) as exc:
        return {"ok": False, "engine": "uo_freshness", "error": str(exc)[:400]}
    pinned = str(ctx.get("expected_fingerprint") or ctx.get("pinned_digest") or "").strip()
    if not pinned:
        try:
            from ascendc_pilot.state import load_state

            live = load_state(project_root, workflow_id="ce-impact") or {}
            pinned = str(live.get("pinned_digest") or "").strip()
        except Exception:  # noqa: BLE001
            pinned = ""
    # Never copy the live product fingerprint as "expected" — that compares
    # the current graph to itself and cannot prove freshness.
    result = check_freshness(project_root, pinned, architecture=arch)
    try:
        from ascendc_pilot.occupancy import binding_is_stale

        digest_check = binding_is_stale(
            project_root,
            pinned_digest=pinned,
            architecture=arch,
        )
        if digest_check.get("stale"):
            result["mode"] = "stale"
            result["fresh"] = False
            result["reason"] = "UO_DIGEST_CHANGED"
            result["reason_code"] = "UO_DIGEST_CHANGED"
            result["pinned_digest"] = digest_check.get("pinned_digest")
            result["live_digest"] = digest_check.get("live_digest")
    except Exception:  # noqa: BLE001
        pass
    doc = {"schema": "ce-uo-freshness/v1", "product": product_identity, **result}
    out = _dump_ce_yaml(_ce(project_root, arch=arch) / "impact" / "freshness.yaml", doc)
    return {
        "ok": result.get("mode") != "stale",
        "engine": "uo_freshness",
        "artifact": out.as_posix(),
        **doc,
    }


def _run_ce_impact_slice(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.impact import impact_from_diff
    from code_engineering.primitives import anchor_resolve, slice_backward, slice_forward

    arch = _resolve_ce_arch(project_root, ctx)
    capture = _load_yaml(_ce(project_root, arch=arch) / "impact" / "change_capture.yaml") or {}
    diff_text = str(capture.get("diff") or "")
    report = impact_from_diff(
        diff_text,
        project_root=project_root,
        architecture=arch,
    ).to_dict()
    spans = {
        str(path): [(int(pair[0]), int(pair[1])) for pair in pairs if len(pair) >= 2]
        for path, pairs in (capture.get("diff_spans") or {}).items()
    }
    from uo_init.query.evidence import USEFUL_EDGE_KINDS

    edge_kinds = list(ctx.get("edge_kinds") or USEFUL_EDGE_KINDS)
    depth = int(ctx.get("depth") or 2)
    budget = int(ctx.get("budget") or 10_000)
    try:
        anchors = anchor_resolve(spans, project_root=project_root, architecture=arch)
        seed_ids = [str(row.get("id")) for row in anchors if row.get("id")]
        forward = slice_forward(
            seed_ids, edge_kinds, depth,
            project_root=project_root, architecture=arch, budget=budget,
        )
        backward = slice_backward(
            seed_ids, edge_kinds, depth,
            project_root=project_root, architecture=arch, budget=budget,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        return {"ok": False, "engine": "impact_slice", "error": str(exc)[:400]}
    doc = {
        "schema": "ce-impact-slice/v1",
        **report,
        "anchors": anchors,
        "forward": forward,
        "backward": backward,
    }
    dim_values = ctx.get("affected_key_dims")
    if isinstance(dim_values, dict) and dim_values and not doc.get("affected_keys"):
        from code_engineering.primitives import key_subset

        try:
            doc["affected_keys"] = key_subset(
                dim_values, project_root=project_root, architecture=arch
            )
        except (FileNotFoundError, RuntimeError) as exc:
            return {"ok": False, "engine": "impact_slice", "error": str(exc)[:400]}
    out = _dump_ce_yaml(_ce(project_root, arch=arch) / "impact" / "impact_slice.yaml", doc)
    return {"ok": True, "engine": "impact_slice", "artifact": out.as_posix(), **doc}


def _run_ce_risk_classify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.risk.rules import evaluate_risks

    arch = _resolve_ce_arch(project_root, ctx)
    impact = _load_yaml(_ce(project_root, arch=arch) / "impact" / "impact_slice.yaml") or {}
    obligations = evaluate_risks(
        list(impact.get("anchors") or []),
        list(ctx.get("risk_classes") or []) or None,
    )
    doc = {
        "schema": "ce-risk-classification/v1",
        "risk_classes": sorted({str(row.get("risk_class")) for row in obligations}),
        "obligations": obligations,
    }
    out = _dump_ce_yaml(
        _ce(project_root, arch=arch) / "impact" / "risk_classification.yaml", doc
    )
    return {"ok": True, "engine": "risk_classify", "artifact": out.as_posix(), **doc}


def _run_ce_obligation_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.ledger import Ledger, save_ledger
    from code_engineering.validation import validate_obligations

    arch = _resolve_ce_arch(project_root, ctx)
    risk = _load_yaml(_ce(project_root, arch=arch) / "impact" / "risk_classification.yaml") or {}
    obligations = [row for row in (risk.get("obligations") or []) if isinstance(row, dict)]
    validation = validate_obligations(obligations)
    doc = {
        "schema": "ce-obligations/v1",
        "obligations": obligations,
        "validation": validation,
    }
    root = _ce(project_root, arch=arch) / "impact"
    out = _dump_ce_yaml(root / "obligations.yaml", doc)
    ledger = Ledger(O={str(row["id"]) for row in obligations if row.get("id")})
    ledger_path = save_ledger(ledger, project_root, architecture=arch, path=root / "ledger.yaml")
    from code_engineering.change_test_intent import (
        build_change_test_intent,
        build_tg_plan_intent,
        write_yaml,
    )
    from ascendc_pilot.actions.scenario_certificate import live_source_fingerprint, live_uo_digest

    impact = _load_yaml(root / "impact_slice.yaml") or {}
    intent_doc = build_change_test_intent(
        impact=impact,
        obligations=obligations,
        uo_digest=live_uo_digest(project_root, architecture=arch),
        source_fingerprint=live_source_fingerprint(project_root),
        change_revision=str(ctx.get("change_revision") or impact.get("head") or ""),
    )
    write_yaml(root / "change_test_intent.yaml", intent_doc)
    tg_intent = build_tg_plan_intent(
        impact=impact,
        architecture=arch,
        op_name=str(ctx.get("op_name") or ""),
        source="ce-impact",
    )
    write_yaml(root / "tg_plan_intent.yaml", tg_intent)
    return {
        "ok": bool(validation.get("ok")),
        "engine": "obligation_build",
        "artifact": out.as_posix(),
        "ledger": ledger_path.as_posix(),
        "change_test_intent": str(root / "change_test_intent.yaml"),
        "tg_plan_intent": str(root / "tg_plan_intent.yaml"),
        "target_count": len(intent_doc.get("targets") or []),
        **doc,
    }


def _run_ce_scenario_infer(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.scenarios import (
        anchors_from_slice,
        infer_scenario_set,
        write_scenario_set,
    )

    arch = _resolve_ce_arch(project_root, ctx)
    ce_root = _ce(project_root, arch=arch)
    impact = _load_yaml(ce_root / "impact" / "impact_slice.yaml") or {}
    intent = _load_yaml(ce_root / "intent" / "anchors.yaml") or {}
    freshness = _load_yaml(ce_root / "impact" / "freshness.yaml") or {}
    anchors = anchors_from_slice(impact)
    for row in intent.get("anchors") or []:
        if isinstance(row, dict):
            anchors.append(row)
    entry = "static" if str(ctx.get("workflow_id") or "") == "ce-intent" else "diff"
    if not impact and intent.get("anchors"):
        entry = "static"
    fingerprint = str(
        (freshness.get("product") or {}).get("graph_fingerprint")
        or freshness.get("fingerprint")
        or ctx.get("fingerprint")
        or ""
    )
    doc = infer_scenario_set(anchors, entry=entry, fingerprint=fingerprint, origin="inferred")
    if str(ctx.get("workflow_id") or "") == "ce-intent":
        out = write_scenario_set(doc, ce_root / "intent" / "planned_scenarios.yaml")
        write_scenario_set(doc, ce_root / "scenarios" / "scenario_set.yaml")
        return {"ok": True, "engine": "scenario_infer", "artifact": out.as_posix(), **doc}
    actual_path = write_scenario_set(doc, ce_root / "impact" / "scenario_set.yaml")
    planned = _load_yaml(ce_root / "intent" / "planned_scenarios.yaml") or {}
    from code_engineering.change_test_intent import scenario_delta, write_yaml

    delta = scenario_delta(planned, doc)
    write_yaml(ce_root / "impact" / "scenario_delta.yaml", delta)
    write_scenario_set(doc, ce_root / "scenarios" / "scenario_set.yaml")
    return {
        "ok": True,
        "engine": "scenario_infer",
        "artifact": actual_path.as_posix(),
        "delta": delta,
        **doc,
    }


def _run_ce_scenario_apply(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.scenarios import merge_knobs, write_scenario_set

    arch = _resolve_ce_arch(project_root, ctx)
    ce_root = _ce(project_root, arch=arch)
    skeleton = _load_yaml(ce_root / "scenarios" / "scenario_set.yaml") or {}
    run_id = str(ctx.get("run_id") or "")
    staging: dict[str, Any] = {}
    if run_id:
        staging = _load_yaml(
            project_root / ".ascendc-pilot" / arch / "runs" / run_id
            / "actions" / "scenario_knobs" / "staging.yaml"
        ) or {}
        if not staging:
            parts_dir = (
                project_root / ".ascendc-pilot" / arch / "runs" / run_id
                / "actions" / "scenario_knobs" / "parts"
            )
            items: list[dict[str, Any]] = []
            for part in sorted(parts_dir.glob("*.yaml")):
                doc = _load_yaml(part) or {}
                items.extend(row for row in (doc.get("items") or []) if isinstance(row, dict))
            if items:
                staging = {"schema": "ce-scenario-knobs/v1", "items": items}
    doc = merge_knobs(skeleton, staging) if staging else skeleton
    out = write_scenario_set(doc, ce_root / "scenarios" / "scenario_set.yaml")
    return {
        "ok": True,
        "engine": "scenario_apply",
        "artifact": out.as_posix(),
        "merged": bool(staging),
        **doc,
    }


def _run_ce_harness_evidence(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.harness import load_adapter
    from code_engineering.scenarios.catalog import PERF_IDS, PRECISION_IDS

    arch = _resolve_ce_arch(project_root, ctx)
    ce_root = _ce(project_root, arch=arch)
    capture = _load_yaml(ce_root / "impact" / "change_capture.yaml") or {}
    head_sha = str(capture.get("head_sha") or capture.get("head") or "unknown")
    obligations = _load_yaml(ce_root / "impact" / "obligations.yaml") or {}
    scenarios = _load_yaml(ce_root / "scenarios" / "scenario_set.yaml") or {}
    results = _load_yaml(
        _tg(project_root, arch=arch) / "closure" / "scenarios" / "harness_results.yaml"
    ) or {}
    adapter = load_adapter(project_root, architecture=arch)
    wanted = {
        str(row.get("id"))
        for row in (obligations.get("obligations") or [])
        if isinstance(row, dict)
        and str(row.get("risk_class") or "") in {"precision", "perf"}
        and row.get("id")
    }
    items = [row for row in (scenarios.get("items") or []) if isinstance(row, dict)]
    scenario_ids = {str(row.get("id") or "") for row in items}
    precision_hit = bool(scenario_ids & set(PRECISION_IDS))
    runs = list(results.get("runs") or [])
    missing = (not runs) or any(str(row.get("reason") or "") == "harness_missing" for row in runs)
    ok = bool(runs) and (not missing) and all(bool(row.get("ok")) for row in runs)
    from ascendc_pilot.actions.scenario_certificate import load_replay_receipts

    cti = _load_yaml(ce_root / "impact" / "change_test_intent.yaml") or {}
    cti_ids = {
        str(row.get("obligation_id") or "")
        for row in (cti.get("targets") or [])
        if isinstance(row, dict) and row.get("obligation_id")
    }
    reached_ids = {
        str(rec.get("obligation_id") or "")
        for rec in load_replay_receipts(project_root, arch=arch)
        if rec.get("target_reached") and rec.get("obligation_id")
    }
    missing_replay = sorted(cti_ids - reached_ids)
    if missing_replay:
        ok = False
    mode = "only_grad" if precision_hit else "profiler"
    receipt = adapter.to_evidence(
        {
            "ok": ok,
            "mode": mode,
            "reason": "harness_missing" if missing else ("missing_target_reached" if missing_replay else ""),
            "csv": str(results.get("csv") or ""),
        },
        change_head_sha=head_sha,
        obligation_ids=sorted(wanted & reached_ids) if ok else [],
    )
    if missing:
        receipt["reason"] = "harness_missing"
        receipt["ok"] = False
        receipt["verified_obligations"] = []
    if missing_replay:
        receipt["reason"] = "missing_target_reached"
        receipt["ok"] = False
        receipt["verified_obligations"] = []
        receipt["missing_target_reached"] = missing_replay
    out = _dump_ce_yaml(ce_root / "verify" / "harness_evidence.yaml", receipt)
    return {"ok": bool(receipt.get("ok")), "engine": "harness_evidence", "artifact": out.as_posix(), **receipt}


_PRECISION_RECEIPT_KINDS = frozenset({"golden", "only_grad", "precision", "precision_compare"})
_PERF_RECEIPT_KINDS = frozenset({"profiler", "profiling", "perf"})
_HOST_REPLAY_KINDS = frozenset({"host_replay", "default_input"})


def _ce_receipt_kinds(row: dict[str, Any]) -> set[str]:
    kinds: set[str] = set()
    for key in ("kind", "mode", "oracle"):
        val = str(row.get(key) or "").strip().lower()
        if val:
            kinds.add(val)
    return kinds


def _ce_evidence_receipts(ce_root: Path) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    harness_path = ce_root / "verify" / "harness_evidence.yaml"
    harness = _load_yaml(harness_path)
    if isinstance(harness, dict) and harness:
        out.append((harness_path.as_posix(), harness))
    ext_path = ce_root / "verify" / "external_evidence.yaml"
    ext = _load_yaml(ext_path)
    if isinstance(ext, dict) and ext:
        receipts = ext.get("receipts")
        if isinstance(receipts, list):
            for row in receipts:
                if not isinstance(row, dict):
                    continue
                src = str(row.get("artifact") or row.get("source") or ext_path.as_posix())
                out.append((src, row))
        elif ext.get("kind") or ext.get("verified_obligations") is not None:
            out.append((ext_path.as_posix(), ext))
    return out


def _run_ce_harness_evidence_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Closed-set check: precision/perf obligations vs golden/profiler receipts."""
    from code_engineering.harness import load_adapter

    arch = _resolve_ce_arch(project_root, ctx)
    ce_root = _ce(project_root, arch=arch)
    obligations_doc = _load_yaml(ce_root / "impact" / "obligations.yaml") or {}
    scenarios = _load_yaml(ce_root / "scenarios" / "scenario_set.yaml") or {}
    adapter = load_adapter(project_root, architecture=arch)
    adapter_kind = str((adapter.identity() or {}).get("kind") or "").strip().lower()
    adapter_missing = adapter_kind in {"", "default_input", "host_replay"}
    receipts = _ce_evidence_receipts(ce_root)
    if any(str(row.get("reason") or "") == "harness_missing" for _, row in receipts):
        adapter_missing = True

    wanted: list[dict[str, Any]] = []
    for row in obligations_doc.get("obligations") or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("id") or "").strip()
        risk = str(row.get("risk_class") or "").strip().lower()
        if oid and risk in {"precision", "perf"}:
            wanted.append({"id": oid, "risk_class": risk})
    scenario_ids = {
        str(row.get("id") or "").strip()
        for row in (scenarios.get("items") or [])
        if isinstance(row, dict) and row.get("id")
    }
    seen_ids = {row["id"] for row in wanted}
    for sid in sorted(scenario_ids):
        if sid in seen_ids:
            continue
        if sid.startswith("P-"):
            wanted.append({"id": sid, "risk_class": "precision"})
            seen_ids.add(sid)
        elif sid.startswith("F-"):
            wanted.append({"id": sid, "risk_class": "perf"})
            seen_ids.add(sid)

    items: list[dict[str, Any]] = []
    for row in wanted:
        oid = row["id"]
        risk = row["risk_class"]
        accepted = _PRECISION_RECEIPT_KINDS if risk == "precision" else _PERF_RECEIPT_KINDS
        pf_locked = oid.startswith(("P-", "F-")) or risk in {"precision", "perf"}
        covered_by = ""
        open_reason = "uncovered"
        host_replay_claimed = False
        wrong_kind = False
        for src, rec in receipts:
            verified = {str(v) for v in (rec.get("verified_obligations") or []) if v}
            if oid not in verified:
                continue
            kinds = _ce_receipt_kinds(rec)
            if kinds & _HOST_REPLAY_KINDS or str(rec.get("kind") or "") == "host_replay":
                host_replay_claimed = True
                if pf_locked:
                    continue
            if not (kinds & accepted):
                wrong_kind = True
                continue
            if rec.get("ok") is False:
                continue
            covered_by = src
            break
        if covered_by:
            status = "covered"
            reason = ""
        else:
            status = "open"
            if adapter_missing:
                reason = "harness_missing"
            elif host_replay_claimed and pf_locked:
                reason = "host_replay_not_closing"
            elif wrong_kind:
                reason = "wrong_receipt_kind"
            else:
                reason = open_reason
        items.append(
            {
                "obligation_id": oid,
                "risk_class": risk,
                "status": status,
                "receipt": covered_by,
                "reason": reason,
            }
        )

    doc = {
        "schema": "ce-harness-evidence-check/v1",
        "ok": True,
        "adapter_kind": adapter_kind or "missing",
        "harness_missing": adapter_missing,
        "excepted_obligations": [],
        "items": items,
        "covered": [row["obligation_id"] for row in items if row["status"] == "covered"],
        "open": [row["obligation_id"] for row in items if row["status"] == "open"],
    }
    out = _dump_ce_yaml(ce_root / "verify" / "harness_evidence_check.yaml", doc)
    return {
        "ok": True,
        "engine": "harness_evidence_check",
        "artifact": out.as_posix(),
        **doc,
    }


def _run_ce_verify_gate(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate

    arch = _resolve_ce_arch(project_root, ctx)
    gate = run_named_gate(project_root, "impact_ledger_ready", architecture=arch)
    doc = {"schema": "ce-verify-gate/v1", "ok": bool(gate.get("ok")), "gate": gate}
    out = _dump_ce_yaml(_ce(project_root, arch=arch) / "verify" / "gate.yaml", doc)
    return {"engine": "verify_gate", "artifact": out.as_posix(), **doc}


def _run_ce_coverage_bridge(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.bridge_tg import bridge_tg

    arch = _resolve_ce_arch(project_root, ctx)
    impact = _load_yaml(_ce(project_root, arch=arch) / "impact" / "impact_slice.yaml") or {}
    limit = int(ctx.get("limit") or 256)
    result = bridge_tg(project_root, impact, architecture=arch, limit=limit)
    intent = _load_yaml(_ce(project_root, arch=arch) / "impact" / "change_test_intent.yaml") or {}
    targets = [row for row in (intent.get("targets") or []) if isinstance(row, dict)]
    truncated = int(result.get("case_count") or 0) >= limit
    uncovered = []
    if truncated:
        uncovered.append(
            {
                "obligation_id": "CE-OBL-BRIDGE-TRUNCATED",
                "reason": "regress_pool_limit",
                "limit": limit,
            }
        )
    for row in targets:
        oid = str(row.get("obligation_id") or "")
        if oid:
            uncovered.append({"obligation_id": oid, "reason": "requires_targeted_construct"})
    result["uncovered_obligations"] = uncovered
    result["primary"] = "change_test_intent" if targets else "regress_pool"
    result["ok"] = bool(result.get("ok")) and not truncated
    if truncated:
        result["error"] = "REGRESS_POOL_TRUNCATED"
    return {"engine": "coverage_bridge", **result}


def _run_ce_residual_analyse(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.ledger import load_ledger, save_ledger

    arch = _resolve_ce_arch(project_root, ctx)
    verify_root = _ce(project_root, arch=arch) / "verify"
    verify_ledger = verify_root / "ledger.yaml"
    source = verify_ledger if verify_ledger.is_file() else _ce(project_root, arch=arch) / "impact" / "ledger.yaml"
    ledger = load_ledger(project_root, architecture=arch, path=source)
    ledger.V.update(str(value) for value in (ctx.get("verified") or []))
    ledger.X.update(str(value) for value in (ctx.get("excepted") or []))
    save_ledger(ledger, project_root, architecture=arch, path=verify_ledger)
    doc = {
        "schema": "ce-verify-residual/v1",
        **ledger.to_dict(),
        "closed": not ledger.Open,
    }
    out = _dump_ce_yaml(verify_root / "residual.yaml", doc)
    return {"ok": True, "engine": "residual_analyse", "artifact": out.as_posix(), **doc}


def _run_ce_external_ingest(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.external_evidence import load_external_evidence
    from code_engineering.ledger import load_ledger, save_ledger

    arch = _resolve_ce_arch(project_root, ctx)
    declared = str(ctx.get("external_evidence_path") or "").strip()
    verify_root = _ce(project_root, arch=arch) / "verify"
    sources: list[str] = []
    if declared:
        sources.append(declared)
    default_receipt = verify_root / "harness_evidence.yaml"
    if default_receipt.is_file() and str(default_receipt) not in sources:
        sources.append(str(default_receipt))
    try:
        receipts: list[dict[str, Any]] = []
        for source in sources:
            receipts.extend(load_external_evidence(source))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "external_ingest", "error": str(exc)[:400]}
    verified = {
        str(value)
        for receipt in receipts
        for value in (receipt.get("verified_obligations") or [])
    }
    excepted = {
        str(value)
        for receipt in receipts
        for value in (receipt.get("excepted_obligations") or [])
    }
    verify_ledger = verify_root / "ledger.yaml"
    source = verify_ledger if verify_ledger.is_file() else _ce(project_root, arch=arch) / "impact" / "ledger.yaml"
    ledger = load_ledger(project_root, architecture=arch, path=source)
    ledger.V.update(verified)
    save_ledger(ledger, project_root, architecture=arch, path=verify_ledger)
    doc = {
        "schema": "ce-external-evidence-batch/v1",
        "declared_path": declared,
        "receipts": receipts,
        "verified_obligations": sorted(verified),
        "excepted_obligations": sorted(excepted),
        "excepted_ignored": True,
    }
    out = _dump_ce_yaml(verify_root / "external_evidence.yaml", doc)
    return {"ok": True, "engine": "external_ingest", "artifact": out.as_posix(), **doc}


def _run_ce_certify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.certificate import write_certificate
    from code_engineering.ledger import load_ledger

    arch = _resolve_ce_arch(project_root, ctx)
    verify_root = _ce(project_root, arch=arch) / "verify"
    verify_ledger = verify_root / "ledger.yaml"
    source = verify_ledger if verify_ledger.is_file() else _ce(project_root, arch=arch) / "impact" / "ledger.yaml"
    ledger = load_ledger(project_root, architecture=arch, path=source)
    out = verify_root / "certificate.yaml"
    doc = write_certificate(
        project_root, ledger, architecture=arch, path=out
    )
    return {"ok": bool(doc.get("closed")), "engine": "ce_certify", "artifact": out.as_posix(), **doc}


def _run_ce_intent_capture(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    arch = _resolve_ce_arch(project_root, ctx)
    doc = {
        "schema": "ce-intent/v1",
        "intent": str(ctx.get("intent") or ctx.get("description") or ""),
        "targets": list(ctx.get("targets") or []),
        "constraints": list(ctx.get("constraints") or []),
    }
    out = _dump_ce_yaml(_ce(project_root, arch=arch) / "intent" / "intent.yaml", doc)
    return {"ok": bool(doc["intent"] or doc["targets"]), "engine": "intent_capture", "artifact": out.as_posix(), **doc}


def _run_ce_intent_kb_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate

    arch = _resolve_ce_arch(project_root, ctx)
    gate = run_named_gate(
        project_root,
        "kb_ready",
        op_name=str(ctx.get("op_name") or "") or None,
        architecture=arch,
    )
    doc = {"schema": "ce-intent-kb-check/v1", "ok": bool(gate.get("ok")), "gate": gate}
    out = _dump_ce_yaml(_ce(project_root, arch=arch) / "intent" / "kb_check.yaml", doc)
    return {"engine": "kb_check", "artifact": out.as_posix(), **doc}


def _run_ce_anchor_locate(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.primitives import anchor_resolve

    arch = _resolve_ce_arch(project_root, ctx)
    spans = {
        str(path): [(int(pair[0]), int(pair[1])) for pair in pairs if len(pair) >= 2]
        for path, pairs in (ctx.get("diff_spans") or {}).items()
    }
    anchors = anchor_resolve(spans, project_root=project_root, architecture=arch)
    doc = {"schema": "ce-intent-anchors/v1", "anchors": anchors, "span_count": len(spans)}
    out = _dump_ce_yaml(_ce(project_root, arch=arch) / "intent" / "anchors.yaml", doc)
    return {"ok": True, "engine": "anchor_locate", "artifact": out.as_posix(), **doc}


def _run_ce_feature_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.intent import promote_feature_decomposition

    arch = _resolve_ce_arch(project_root, ctx)
    return promote_feature_decomposition(
        project_root,
        architecture=arch,
        run_id=str(ctx.get("run_id") or ""),
    )


def _run_ce_grill_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.intent import promote_intent_grill

    arch = _resolve_ce_arch(project_root, ctx)
    return promote_intent_grill(
        project_root,
        architecture=arch,
        run_id=str(ctx.get("run_id") or ""),
    )


def _run_ce_apply_gate(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.apply import apply_gate

    arch = _resolve_ce_arch(project_root, ctx)
    return apply_gate(project_root, architecture=arch)


def _run_ce_apply_capture(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.change.capture import capture

    arch = _resolve_ce_arch(project_root, ctx)
    out = _ce(project_root, arch=arch) / "apply" / "change_capture.yaml"
    try:
        payload = capture(
            project_root,
            base=str(ctx.get("base") or "HEAD"),
            head=str(ctx.get("head") or ""),
            architecture=arch,
            output=out,
        )
        return {"ok": out.is_file(), "engine": "change_capture", "artifact": out.as_posix(), **payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "change_capture", "error": str(exc)[:400]}


def _run_ce_patch_guard(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.apply import patch_guard

    arch = _resolve_ce_arch(project_root, ctx)
    return patch_guard(project_root, architecture=arch)


def _run_ce_codemap_refresh(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Independent UO transaction: never write .uo under the CE apply lock alone."""
    from ascendc_pilot.occupancy import (
        acquire_exclusive_lock,
        live_exclusive_lock,
        live_resource_conflict,
        publish_uo_digest,
        release_exclusive_lock,
    )

    arch = _resolve_ce_arch(project_root, ctx)
    holder = live_exclusive_lock(project_root, "uo")
    if holder:
        doc = {
            "schema": "ce-codemap-refresh/v1",
            "ok": False,
            "error": "UO_PRODUCT_LOCKED",
            "holder": holder,
            "message_zh": "UO 产物锁被占用，禁止在 CE apply 内静默双写 .uo",
        }
        out = _dump_ce_yaml(_ce(project_root, arch=arch) / "apply" / "codemap_refresh.yaml", doc)
        return {"ok": False, "engine": "codemap_refresh", "artifact": out.as_posix(), **doc}
    conflict = live_resource_conflict(
        project_root, "uo-update", ignore_run_id=str(ctx.get("run_id") or "")
    )
    if conflict:
        doc = {
            "schema": "ce-codemap-refresh/v1",
            "ok": False,
            "error": "UO_REFRESH_CONFLICT",
            **conflict,
        }
        out = _dump_ce_yaml(_ce(project_root, arch=arch) / "apply" / "codemap_refresh.yaml", doc)
        return {"ok": False, "engine": "codemap_refresh", "artifact": out.as_posix(), **doc}

    refresh_run = f"{ctx.get('run_id') or 'CE'}-uo-refresh"
    nested = False
    try:
        acquire_exclusive_lock(
            project_root,
            occupancy_group="uo",
            workflow_id="uo-update",
            run_id=refresh_run,
            architecture=arch,
            session_id=str(ctx.get("session_id") or ""),
        )
        nested = True
        detect = _run_detect_changes(project_root, ctx)
        plan = _run_plan_update(project_root, ctx)
        applied = _run_apply_update(project_root, ctx)
        export = _run_export_integrity(project_root, ctx)
        diff = _run_diff_summary(project_root, ctx)
        ok = all(bool(step.get("ok")) for step in (detect, plan, applied, export, diff))
        published = {}
        try:
            published = publish_uo_digest(project_root, architecture=arch)
        except Exception as exc:  # noqa: BLE001
            published = {"ok": False, "error": str(exc)[:200]}
        doc = {
            "schema": "ce-codemap-refresh/v1",
            "ok": ok,
            "uo_transaction": refresh_run,
            "uo_digest": published.get("digest") or "",
            "detect": {k: detect.get(k) for k in ("ok", "engine", "error", "scoped_change_count") if k in detect},
            "plan": {k: plan.get(k) for k in ("ok", "engine", "error") if k in plan},
            "apply": {k: applied.get(k) for k in ("ok", "engine", "error") if k in applied},
            "export": {k: export.get(k) for k in ("ok", "engine", "error") if k in export},
            "diff": {k: diff.get(k) for k in ("ok", "engine", "error") if k in diff},
        }
    finally:
        if nested:
            release_exclusive_lock(project_root, "uo", run_id=refresh_run)
    out = _dump_ce_yaml(_ce(project_root, arch=arch) / "apply" / "codemap_refresh.yaml", doc)
    return {"ok": ok, "engine": "codemap_refresh", "artifact": out.as_posix(), **doc}


def _run_ce_session_handoff(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.handoff import write_session_handoff

    arch = _resolve_ce_arch(project_root, ctx)
    wid = str(ctx.get("workflow_id") or "").strip()
    next_slash = {
        "ce-intent": "/ce-apply",
        "ce-apply": "/ce-impact",
        "ce-impact": "/ce-verify",
        "ce-handoff": str(ctx.get("next_slash") or "/ce-apply"),
    }.get(wid, "/ce-apply")
    artifacts = [
        "ce/intent/plan.md",
        "ce/apply/todo.md",
        "ce/session_handoff.md",
    ]
    return write_session_handoff(
        project_root,
        architecture=arch,
        next_slash=next_slash,
        artifact_paths=artifacts,
        open_items=list(ctx.get("open_items") or []),
    )



def _run_export_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Delegate integrity to uo_init.pilot_engines.export_integrity."""
    try:
        from uo_init.pilot_engines import export_integrity

        return export_integrity(Path(project_root), ctx or {})
    except Exception as exc:  # noqa: BLE001
        uo = _uo(project_root)
        gate = uo / "checks" / "integrity.yaml"
        if not gate.is_file():
            gate.parent.mkdir(parents=True, exist_ok=True)
            gate.write_text("status: fail\nmessage: engine_invoke_failed\n", encoding="utf-8")
        return {"ok": False, "errors": [str(exc)[:200]]}


def _run_detect_changes(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "detect_changes", "error": "op_name required"}
    try:
        from uo_init.update import detect_kb_changes

        payload = detect_kb_changes(project_root, op_name, write=True)
        out = uo / "diff" / "change_set.yaml"
        return {
            "ok": out.is_file(),
            "engine": "detect_changes",
            "artifact": out.as_posix() if out.is_file() else "",
            "scoped_change_count": payload.get("scoped_change_count"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_changes", "error": str(exc)[:300]}


def _run_plan_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "plan_update", "error": "op_name required"}
    try:
        from uo_init.update import detect_kb_changes, load_change_set_if_fresh, plan_kb_update

        change_set = load_change_set_if_fresh(uo, repo_root=project_root)
        reused = change_set is not None
        if change_set is None:
            change_set = detect_kb_changes(project_root, op_name, write=True)
        plan_kb_update(project_root, op_name, change_set=change_set, write=True)
        out = uo / "summary" / "update_plan.yaml"
        return {
            "ok": out.is_file(),
            "engine": "plan_update",
            "artifact": out.as_posix() if out.is_file() else "",
            "change_set_reused": reused,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_update", "error": str(exc)[:300]}


def _run_apply_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "apply_update", "error": "op_name required"}
    run_id = str((ctx or {}).get("run_id") or "").strip()
    try:
        from uo_init.update import update_operator

        result = update_operator(
            project_root,
            op_name,
            architecture=arch,
            run_id=run_id or None,
            reuse_artifacts=True,
            cann_root=str((ctx or {}).get("cann_root") or "") or None,
            ops_root=str((ctx or {}).get("ops_root") or "") or None,
        )
        status = str((result or {}).get("status") or "")
        receipt_ok = any((uo / "runs").glob("*/update/receipt.yaml")) if (uo / "runs").is_dir() else False
        diff_ok = (uo / "diff" / "index.yaml").is_file() and (uo / "diff" / "change_set.yaml").is_file()
        eng_ok = status in {"pass", "blocked", "noop"} or status == "pass"
        if status == "fail":
            eng_ok = False
        return {
            "ok": eng_ok and (diff_ok or status == "blocked"),
            "engine": "apply_update",
            "receipt_present": receipt_ok,
            "diff_present": diff_ok,
            "publish_deferred": bool((result or {}).get("publish_deferred")),
            "run_id": (result.get("run_id") if isinstance(result, dict) else None) or run_id,
            "result_keys": list(result.keys())[:12] if isinstance(result, dict) else [],
            "status": status,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_update", "error": str(exc)[:300]}


def _run_diff_summary(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Emit canonical diff/ product from existing change_set/update_plan when fresh."""
    uo, op_name, _arch = _uo_op_ctx(project_root, ctx)
    if not op_name:
        return {"ok": False, "engine": "diff_summary", "error": "op_name required"}
    try:
        from uo_init.update import (
            detect_kb_changes,
            export_diff_product,
            load_change_set_if_fresh,
            load_update_plan_if_fresh,
            plan_kb_update,
        )

        change_set = load_change_set_if_fresh(uo, repo_root=project_root)
        plan = load_update_plan_if_fresh(uo, change_set=change_set) if change_set else None
        reused = change_set is not None and plan is not None
        if change_set is None:
            change_set = detect_kb_changes(project_root, op_name, write=True)
        if plan is None:
            plan = plan_kb_update(project_root, op_name, change_set=change_set, write=True)
        product = export_diff_product(
            project_root,
            op_name,
            change_set=change_set,
            update_plan=plan,
            write=True,
        )
        return {"ok": True, "engine": "diff_summary", "product": product, "artifacts_reused": reused}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "diff_summary", "error": str(exc)[:300]}


def _run_tg_kb_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Require CodeMap ``.uo`` with TG view blobs (D / host_view / graph)."""
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    ready = _ensure_uo_tg_views(project_root, tg_ctx)
    ok = bool(ready.get("ok")) and int(ready.get("legal_key_count") or 0) > 0
    receipt = {
        "schema": "tg-uo-ready/v1",
        "kind": "receipt",
        "ok": ok,
        "mode": str(tg_ctx.get("mode") or "tilingkey_full_coverage"),
        "op_name": str(tg_ctx.get("op_name") or ""),
        "architecture": str(tg_ctx.get("architecture") or ""),
        "uo_product": str(ready.get("path") or ""),
        "legal_key_count": int(ready.get("legal_key_count") or 0),
        "error": "" if ok else str(ready.get("error") or "UO TG views not ready"),
    }
    out = _write_run_receipt(project_root, ctx, "uo_ready.yaml", receipt)
    return {
        "ok": ok,
        "engine": "kb_check",
        "mode": receipt["mode"],
        "gate": {
            "gate": "uo_ready",
            "ok": ok,
            "message": "ok" if ok else receipt["error"],
            "detail": ready,
        },
        "uo": ready,
        "receipt_path": out.as_posix(),
    }


def _ensure_uo_tg_views(project_root: Path, tg_ctx: dict[str, Any]) -> dict[str, Any]:
    """Locate ``.uo`` and confirm TPL/D + host/graph view_blobs are readable."""
    try:
        from uo_init.tg_projection import ensure_tg_views

        return ensure_tg_views(
            project_root,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400]}


def _load_uo_tg_doc(project_root: Path, tg_ctx: dict[str, Any], name: str) -> dict[str, Any]:
    """Load a TG view exclusively from the CodeMap ``.uo`` view_blob."""
    try:
        from testcase_agent import product_uo

        blob = product_uo.view(
            project_root,
            name,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
        return blob if isinstance(blob, dict) else {}
    except Exception:
        return {}


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return None
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _resolve_tg_ctx(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Resolve op_name / architecture / consumer root / level / focus / mode for TG engines."""
    import os

    from ascendc_pilot.paths import discover_arch, resolve_arch
    from ascendc_pilot.state import load_state

    # Prefer ctx.architecture; otherwise discover (env → active_run → sole workflow).
    # Do not call resolve_arch(None): that only reads env and breaks fresh acp
    # subprocesses after start already pinned active_run.yaml.
    arch_explicit = str(ctx.get("architecture") or "").strip() or None
    try:
        arch_hint = (
            resolve_arch(arch_explicit)
            if arch_explicit
            else discover_arch(project_root)
        )
    except ValueError as exc:
        text = str(exc)
        if "ARCHITECTURE_AMBIGUOUS" in text:
            raise
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE") from exc
    state = load_state(project_root) or {}
    params = _load_yaml(_ctx_root(project_root, arch=arch_hint) / "pilot_params.yaml") or {}
    if not isinstance(params, dict):
        params = {}
    pack = _load_yaml(_ctx_root(project_root, arch=arch_hint) / "context_pack.yaml") or {}
    if not isinstance(pack, dict):
        pack = {}
    run_ctx = _load_yaml(_tg(project_root, arch=arch_hint) / "init" / "run_context.yaml") or {}
    if not isinstance(run_ctx, dict):
        run_ctx = {}
    init_intent = _load_yaml(
        _tg(project_root, arch=arch_hint) / "init" / "init_intent.yaml"
    ) or {}
    if not isinstance(init_intent, dict):
        init_intent = {}
    plan_intent = _load_yaml(
        _tg(project_root, arch=arch_hint) / "plan" / "plan_intent.yaml"
    ) or {}
    if not isinstance(plan_intent, dict):
        plan_intent = {}
    man = _load_yaml(_uo(project_root, arch=arch_hint) / "manifest.yaml") or {}
    if not isinstance(man, dict):
        man = {}

    def _pick(*vals: Any, default: str = "") -> str:
        for v in vals:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return default

    op_name = _pick(
        ctx.get("op_name"),
        state.get("op_name"),
        params.get("op_name"),
        pack.get("op_name"),
        run_ctx.get("op_name"),
        man.get("op_name"),
        project_root.name,
    )
    architecture = _pick(
        ctx.get("architecture"),
        state.get("architecture"),
        params.get("architecture"),
        pack.get("architecture"),
        man.get("architecture"),
        default=arch_hint,
    )
    if not architecture:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    level = _pick(ctx.get("level"), state.get("level"), params.get("level"), pack.get("level"), default="L0")
    focus = _pick(ctx.get("focus"), state.get("focus"), params.get("focus"), pack.get("focus"))
    test_script_root = _pick(
        ctx.get("test_script_root"),
        state.get("test_script_root"),
        params.get("test_script_root"),
        pack.get("test_script_root"),
        run_ctx.get("test_script_root"),
        os.environ.get("ASCENDC_TEST_SCRIPT_ROOT"),
        init_intent.get("consumer_root"),
    )
    mode = _pick(
        ctx.get("mode"),
        ctx.get("tg_mode"),
        state.get("mode"),
        params.get("mode"),
        init_intent.get("mode"),
        plan_intent.get("mode"),
        default="tilingkey_full_coverage",
    )
    return {
        "op_name": op_name,
        "architecture": architecture,
        "level": level,
        "focus": focus,
        "test_script_root": test_script_root,
        "mode": mode,
    }


_FULL_TK_MODES = frozenset({"tilingkey_full_coverage", "tilingkey_full"})


def _is_tilingkey_full(tg_ctx: dict[str, Any]) -> bool:
    return str(tg_ctx.get("mode") or "").strip() in _FULL_TK_MODES


def _run_tg_init_intent(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Write tg/init/init_intent.yaml — defaults to tilingkey_full_coverage."""
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    intent_path = _tg(project_root) / "init" / "init_intent.yaml"
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_yaml(intent_path) or {}
    if not isinstance(existing, dict):
        existing = {}
    mode = str(
        ctx.get("mode")
        or existing.get("mode")
        or tg_ctx.get("mode")
        or "tilingkey_full_coverage"
    ).strip()
    doc = {
        "schema": "tg-init-intent/v1",
        "mode": mode,
        "source": str(ctx.get("source") or existing.get("source") or "default"),
        "consumer_root": str(
            ctx.get("consumer_root")
            or existing.get("consumer_root")
            or tg_ctx.get("test_script_root")
            or ""
        ),
        "test_script_root": str(
            ctx.get("test_script_root")
            or existing.get("test_script_root")
            or tg_ctx.get("test_script_root")
            or ctx.get("consumer_root")
            or existing.get("consumer_root")
            or ""
        ),
        "op_name": tg_ctx["op_name"],
        "architecture": tg_ctx["architecture"],
        "description": str(ctx.get("description") or existing.get("description") or ""),
    }
    try:
        import yaml

        intent_path.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "init_intent", "error": str(exc)[:200]}
    return {"ok": True, "engine": "init_intent", "artifact": intent_path.as_posix(), **doc}


def _write_tilingkey_contract(project_root: Path, tg_ctx: dict[str, Any]) -> dict[str, Any]:
    """Build tilingkey contract from CodeMap ``.uo`` view_blobs only."""
    import yaml

    tg = _tg(project_root)
    errors: list[str] = []
    ready = _ensure_uo_tg_views(project_root, tg_ctx)
    if not ready.get("ok"):
        errors.append(str(ready.get("error") or "uo_tg_views_unavailable"))
    graph_doc = _load_uo_tg_doc(project_root, tg_ctx, "ir/operator_graph.yaml")
    key_doc = _load_uo_tg_doc(project_root, tg_ctx, "tiling/exhaustive_key_space.yaml")
    view_doc = _load_uo_tg_doc(project_root, tg_ctx, "ir/tg_host_view.yaml")
    if not graph_doc:
        errors.append("missing view_blob ir/operator_graph.yaml in .uo")
    if not key_doc:
        errors.append("missing view_blob tiling/exhaustive_key_space.yaml in .uo")
    if not view_doc:
        errors.append("missing view_blob ir/tg_host_view.yaml in .uo")
    declared_count = int(key_doc.get("legal_key_count") or 0)
    if declared_count <= 0:
        declared_count = int(ready.get("legal_key_count") or 0)
    if declared_count <= 0:
        errors.append("DECLARED_SET_EMPTY: legal_key_count missing or zero")
    index_rel = str(key_doc.get("legal_key_index") or "tiling/legal_key_index.jsonl")
    try:
        from uo_init.tg_projection import legal_key_rows
        from uo_init.store.reader import find_uo_product

        product = find_uo_product(
            project_root,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
        if product is not None and declared_count > 0:
            n_rows = len(legal_key_rows(product))
            if n_rows and n_rows != declared_count:
                errors.append(
                    f"DECLARED_SET_MISMATCH: legal_key_count={declared_count} "
                    f"but legal_key_index has {n_rows} rows"
                )
    except Exception:
        pass
    contract = {
        "schema": "tg-tilingkey-contract/v1",
        "status": "pass" if not errors else "fail",
        "mode": "tilingkey_full_coverage",
        "op_name": tg_ctx["op_name"],
        "architecture": tg_ctx["architecture"],
        "declared_set": {
            "source": "uo:tiling/exhaustive_key_space.yaml",
            "fingerprint": str(
                key_doc.get("fingerprint")
                or graph_doc.get("fingerprint")
                or ready.get("graph_fingerprint")
                or ""
            ),
            "count": declared_count,
            "legal_key_index": index_rel,
        },
        "graph_fingerprint": str(
            graph_doc.get("fingerprint") or ready.get("graph_fingerprint") or ""
        ),
        "host_view": "uo:ir/tg_host_view.yaml",
        "uo_product": str(ready.get("path") or ""),
        "errors": errors,
    }
    out = tg / "contract" / "tilingkey_contract.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return contract


def _run_tg_contract_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op_name = tg_ctx["op_name"]
    if not op_name:
        return {"ok": False, "engine": "contract_build", "error": "op_name required"}
    try:
        if _is_tilingkey_full(tg_ctx):
            payload = _write_tilingkey_contract(project_root, tg_ctx)
            ok = str(payload.get("status") or "").lower() == "pass"
            # Persist mode for subsequent TG actions.
            params_path = _ctx_root(project_root) / "pilot_params.yaml"
            params_path.parent.mkdir(parents=True, exist_ok=True)
            existing = _load_yaml(params_path) or {}
            if not isinstance(existing, dict):
                existing = {}
            existing.update(
                {
                    "op_name": op_name,
                    "architecture": tg_ctx["architecture"],
                    "mode": tg_ctx["mode"],
                    "level": tg_ctx["level"],
                    "focus": tg_ctx["focus"],
                }
            )
            try:
                import yaml

                params_path.write_text(
                    yaml.safe_dump(existing, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass
            return {
                "ok": ok,
                "engine": "contract_build",
                "op_name": op_name,
                "mode": tg_ctx["mode"],
                "payload": payload,
                "errors": payload.get("errors") or [],
            }
        return {
            "ok": False,
            "engine": "contract_build",
            "error": "legacy CSV contract path removed; use tilingkey_full_coverage",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "contract_build", "error": str(exc)[:400]}


def _write_test_repo_bind(
    project_root: Path,
    tg_ctx: dict[str, Any],
    view_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scan optional test-script repo and write a generic consume contract."""
    import yaml
    from testcase_agent.test_repo import contract_from_inventory, scan

    inventory = scan(str(tg_ctx.get("test_script_root") or "") or None)
    view_doc = view_doc if isinstance(view_doc, dict) else {}
    host_fields = [str(f.get("name") or "") for f in (view_doc.get("fields") or []) if isinstance(f, dict)]
    host_fields = [name for name in host_fields if name]
    key_dims = [str(name) for name in (view_doc.get("declared_keys") or {}) if name]
    knob_defaults: dict[str, Any] = {}
    try:
        from replay import inputs as I

        sem = getattr(I, "SEMANTICS", None)
        schema = sem.knob_schema() if sem is not None and hasattr(sem, "knob_schema") else {}
        for name, meta in (schema or {}).items():
            if isinstance(meta, dict) and "default" in meta:
                knob_defaults[str(name)] = meta["default"]
    except Exception:
        knob_defaults = {}
    contract = contract_from_inventory(
        inventory,
        host_fields=host_fields,
        key_dims=key_dims,
        knob_defaults=knob_defaults,
    )
    init = _tg(project_root) / "init"
    init.mkdir(parents=True, exist_ok=True)
    (init / "test_repo_inventory.yaml").write_text(
        yaml.safe_dump(inventory, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (init / "test_repo_contract.yaml").write_text(
        yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return contract


def _run_tg_semantic_bind(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    try:
        if _is_tilingkey_full(tg_ctx):
            import yaml

            _ensure_uo_tg_views(project_root, tg_ctx)
            view = _load_uo_tg_doc(project_root, tg_ctx, "ir/tg_host_view.yaml")
            graph_doc = _load_uo_tg_doc(project_root, tg_ctx, "ir/operator_graph.yaml")
            repo_contract = _write_test_repo_bind(project_root, tg_ctx, view)
            if not view:
                return {
                    "ok": False,
                    "engine": "semantic_bind",
                    "error": "missing view_blob ir/tg_host_view.yaml in .uo",
                    "test_repo": repo_contract.get("kind"),
                }
            rows = []
            for f in view.get("fields") or []:
                name = str(f.get("name") or "")
                if not name:
                    continue
                reads = list(f.get("reads") or [])
                rows.append({
                    "field": name,
                    "kind": f.get("kind"),
                    "tiling_key": f.get("tiling_key"),
                    "reads": reads,
                    "exactness": f.get("exactness"),
                    "entity_id": f.get("entity_id"),
                    "packing": list(f.get("packing") or []),
                })
            # Also bind declared key dims when host fields are sparse.
            for dim, meta in (view.get("declared_keys") or {}).items():
                if any(r.get("field") == dim or r.get("tiling_key") == dim for r in rows):
                    continue
                rows.append({
                    "field": str(dim),
                    "kind": "key_dim",
                    "tiling_key": str(dim),
                    "reads": [],
                    "exactness": "",
                    "packing": list((meta or {}).get("packing") or []),
                })
            inv = {
                "schema": "tg-tilingkey-binding-inventory/v1",
                "mode": "tilingkey_full_coverage",
                "fields": rows,
                "field_count": len(rows),
                "graph_fingerprint": str(
                    graph_doc.get("fingerprint")
                    or (view.get("source") or {}).get("graph_fingerprint")
                    or ""
                ),
            }
            inv_path = tg / "realization" / "binding_inventory.yaml"
            inv_path.parent.mkdir(parents=True, exist_ok=True)
            inv_path.write_text(
                yaml.safe_dump(inv, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            return {
                "ok": True,
                "engine": "semantic_bind",
                "mode": "tilingkey_full_coverage",
                "artifacts": {},
                "inventory_path": inv_path.as_posix(),
                "field_count": len(rows),
                "test_repo": repo_contract.get("kind"),
            }

        return {
            "ok": False,
            "engine": "semantic_bind",
            "error": "legacy CSV bind path removed; use tilingkey_full_coverage",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "semantic_bind", "error": str(exc)[:400]}




def _run_tg_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    # Full TK mode: key contract / host-view readiness instead of CSV closure.
    contract = _load_yaml(tg / "contract" / "tilingkey_contract.yaml") or {}
    status = str(contract.get("status") or "").lower()
    ok = status == "pass" and not list(contract.get("errors") or [])
    receipt = {
        "schema": "tg-tilingkey-integrity/v1",
        "kind": "receipt",
        "mode": "tilingkey_full_coverage",
        "status": "pass" if ok else "fail",
        "tilingkey_contract_status": status or "missing",
        "errors": list(contract.get("errors") or []),
    }
    out = _write_run_receipt(project_root, ctx, "integrity_gate.yaml", receipt)
    return {
        "ok": ok,
        "engine": "integrity_gate",
        "mode": "tilingkey_full_coverage",
        "artifact": out.as_posix(),
        "gates": {
            "tilingkey_contract": {
                "ok": ok,
                "status": status or "missing",
                "errors": list(contract.get("errors") or []),
            }
        },
    }


def _tg_init_audit_check(
    check_id: str,
    *,
    ok: bool,
    detail: str,
) -> dict[str, str]:
    return {
        "id": check_id,
        "status": "pass" if ok else "fail",
        "detail": detail,
    }


def _run_tg_init_audit(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Closed tilingkey checklist → ``tg/init/audit_report.yaml``."""
    from datetime import datetime, timezone

    import yaml
    from testcase_agent.resolve_policy import TILINGKEY_AUDIT_CHECKLIST_IDS

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    contract_path = tg / "contract" / "tilingkey_contract.yaml"
    inventory_path = tg / "realization" / "binding_inventory.yaml"
    contract = _load_yaml(contract_path) or {}
    inventory = _load_yaml(inventory_path) or {}
    if not isinstance(contract, dict):
        contract = {}
    if not isinstance(inventory, dict):
        inventory = {}

    contract_status = str(contract.get("status") or "").strip().lower()
    contract_present = contract_path.is_file() and bool(contract)
    contract_ok = (
        contract_present
        and contract_status == "pass"
        and not list(contract.get("errors") or [])
    )
    declared = contract.get("declared_set") if isinstance(contract.get("declared_set"), dict) else {}
    declared_count = int(declared.get("count") or 0)
    fields = [row for row in (inventory.get("fields") or []) if isinstance(row, dict)]
    inventory_ok = inventory_path.is_file() and bool(fields)
    fingerprint = str(
        contract.get("graph_fingerprint")
        or inventory.get("graph_fingerprint")
        or declared.get("fingerprint")
        or ""
    ).strip()

    run_id = str(ctx.get("run_id") or "").strip()
    if not run_id:
        try:
            from ascendc_pilot.state import load_state

            run_id = str((load_state(project_root) or {}).get("run_id") or "").strip()
        except Exception:  # noqa: BLE001
            run_id = ""
    from ascendc_pilot.runs import receipts_dir

    integrity = _load_yaml(receipts_dir(project_root, run_id or None) / "integrity_gate.yaml") or {}
    if not isinstance(integrity, dict):
        integrity = {}
    integrity_status = str(integrity.get("status") or "").strip().lower()
    integrity_ok = integrity_status == "pass"

    warnings: list[str] = []
    for row in fields:
        name = str(row.get("field") or row.get("name") or "").strip() or "(unnamed)"
        reads = row.get("reads")
        exactness = str(row.get("exactness") or "").strip()
        if not reads:
            warnings.append(f"{name}: empty reads (non-blocking in tilingkey full coverage)")
        if not exactness:
            warnings.append(f"{name}: empty exactness (non-blocking in tilingkey full coverage)")

    checks = [
        _tg_init_audit_check(
            "tilingkey_contract",
            ok=contract_ok,
            detail=(
                "tilingkey contract present and status=pass"
                if contract_ok
                else (
                    "tilingkey_contract.yaml missing"
                    if not contract_present
                    else f"tilingkey contract status={contract_status or 'missing'}"
                )
            ),
        ),
        _tg_init_audit_check(
            "declared_set_nonempty",
            ok=declared_count > 0,
            detail=(
                f"declared TilingKey set count={declared_count}"
                if declared_count > 0
                else "declared TilingKey set is empty or missing"
            ),
        ),
        _tg_init_audit_check(
            "binding_inventory",
            ok=inventory_ok,
            detail=(
                f"host binding inventory fields={len(fields)}"
                if inventory_ok
                else "binding_inventory.yaml missing or has no fields"
            ),
        ),
        _tg_init_audit_check(
            "host_view_aligned",
            ok=inventory_path.is_file(),
            detail=(
                "host view inventory present; empty reads/exactness are warnings only"
                if inventory_path.is_file()
                else "binding inventory missing; host view cannot be aligned"
            ),
        ),
        _tg_init_audit_check(
            "graph_fingerprint",
            ok=bool(fingerprint),
            detail=(
                "graph fingerprint present on contract or inventory"
                if fingerprint
                else "graph fingerprint missing on contract and inventory"
            ),
        ),
        _tg_init_audit_check(
            "integrity_gate",
            ok=integrity_ok,
            detail=(
                "integrity gate receipt status=pass"
                if integrity_ok
                else f"integrity gate status={integrity_status or 'missing'}"
            ),
        ),
    ]
    by_id = {row["id"]: row for row in checks}
    ordered = [by_id[cid] for cid in TILINGKEY_AUDIT_CHECKLIST_IDS if cid in by_id]
    for row in checks:
        if row["id"] not in {c["id"] for c in ordered}:
            ordered.append(row)
    blockers = [
        f"{row['id']}: {row['detail']}" for row in ordered if row["status"] == "fail"
    ]
    status = "fail" if blockers else "pass"
    report = {
        "version": 1,
        "status": status,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "op_name": str(tg_ctx.get("op_name") or ctx.get("op_name") or ""),
        "checks": ordered,
        "blockers": blockers,
        "warnings": warnings,
    }
    out = tg / "init" / "audit_report.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "ok": status == "pass",
        "engine": "init_audit",
        "artifact": out.as_posix(),
        **report,
    }


def _run_tg_plan_intent(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Write plan_intent.yaml. Default mode = tilingkey_full_coverage."""
    import yaml

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    init_intent = _load_yaml(tg / "init" / "init_intent.yaml") or {}
    existing = _load_yaml(tg / "plan" / "plan_intent.yaml") or {}
    arch = str(tg_ctx.get("architecture") or "").strip() or _resolve_ce_arch(project_root, ctx)
    ce_intent = _load_yaml(_ce(project_root, arch=arch) / "impact" / "tg_plan_intent.yaml") or {}
    requested = (
        str(ctx.get("mode") or "").strip()
        or str(existing.get("mode") or "").strip()
        or str(ce_intent.get("mode") or "").strip()
        or str(init_intent.get("mode") or "").strip()
    )
    full_coverage = {
        "tilingkey_full_coverage",
        "branch_outcome_coverage",
        "ce_change_scoped",
    }
    scenario_doc = _load_yaml(
        _ce(project_root, arch=arch) / "scenarios" / "scenario_set.yaml"
    ) or {}
    scenario_ids = [
        str(row.get("id"))
        for row in (scenario_doc.get("items") or [])
        if isinstance(row, dict) and row.get("id")
    ]
    if requested == "scenario_targeted" or requested == "scenario_set":
        mode = "scenario_targeted"
    elif requested in full_coverage:
        mode = requested
    else:
        mode = requested or "tilingkey_full_coverage"
    source = (
        str(ctx.get("source") or "").strip()
        or str(existing.get("source") or "").strip()
        or str(ce_intent.get("source") or "").strip()
        or ("init_intent" if init_intent.get("mode") else "default")
    )
    intent = {
        "schema": "tg-plan-intent/v1",
        "mode": mode,
        "source": source,
        "description": str(ctx.get("description") or existing.get("description") or ""),
        "pr_ref": str(ctx.get("pr_ref") or existing.get("pr_ref") or ""),
        "op_name": tg_ctx.get("op_name") or "",
        "architecture": tg_ctx.get("architecture") or "",
    }
    if mode == "ce_change_scoped" and ce_intent:
        for key in (
            "target_keys",
            "target_dimensions",
            "target_mode",
            "dimension_names",
            "do_not_widen_to_declared_set",
        ):
            if key in ce_intent and ce_intent.get(key) not in (None, ""):
                intent[key] = ce_intent[key]
        intent["source"] = str(ce_intent.get("source") or "ce-impact")
        intent["do_not_widen_to_declared_set"] = True
        if not intent.get("target_mode"):
            intent["target_mode"] = (
                "explicit_keys"
                if intent.get("target_keys") or not intent.get("target_dimensions")
                else "dimension_filter"
            )
    if mode == "scenario_targeted":
        if not scenario_ids:
            return {
                "ok": False,
                "engine": "plan_intent",
                "error": "SCENARIO_SET_EMPTY",
                "reason_code": "SCENARIO_SET_EMPTY",
                "message_zh": (
                    "scenario_targeted 需要已确认 ScenarioSet；"
                    "禁止静默扩大成全部合法 Key，禁止笛卡尔展开 D。"
                ),
            }
        intent["target_mode"] = "scenario_set"
        intent["scenarios"] = scenario_ids
        intent["scenario_set"] = "ce/scenarios/scenario_set.yaml"
        intent["forbid_cartesian_over_declared"] = True
        intent["do_not_widen_to_declared_set"] = True
    out = tg / "plan" / "plan_intent.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(intent, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "engine": "plan_intent", "artifact": out.as_posix(), **intent}


def _run_tg_plan_scope(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    tg = _tg(project_root)
    level = tg_ctx["level"] or "L0"
    intent = _load_yaml(tg / "plan" / "plan_intent.yaml") or {}
    mode = (
        str(intent.get("mode") or "").strip()
        or tg_ctx.get("mode")
        or "tilingkey_full_coverage"
    )
    scope = {
        "version": 1,
        "op_name": tg_ctx["op_name"],
        "level": level,
        "focus": tg_ctx["focus"],
        "mode": mode,
        "architecture": tg_ctx["architecture"],
    }
    out = tg / "plan" / "levels" / level / "plan_scope.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml

        out.write_text(yaml.safe_dump(scope, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # Keep plan_intent in sync with resolved mode.
        if not intent:
            intent = {
                "schema": "tg-plan-intent/v1",
                "mode": mode,
                "source": "plan_scope",
                "op_name": tg_ctx["op_name"],
            }
            intent_path = tg / "plan" / "plan_intent.yaml"
            intent_path.write_text(
                yaml.safe_dump(intent, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_scope", "error": str(exc)[:200]}
    return {"ok": True, "engine": "plan_scope", "artifact": out.as_posix(), **scope}


def _run_tg_plan_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del project_root, ctx
    return {"ok": True, "engine": "plan_precheck", "pre_gates": "runtime"}


def _run_tg_plan_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    op_name = tg_ctx["op_name"]
    if not op_name:
        return {"ok": False, "engine": "plan_build", "error": "op_name required"}
    try:
        level = tg_ctx["level"] or "L0"
        if _is_tilingkey_full(tg_ctx):
            import yaml

            uo = _uo(project_root)
            keys = _load_yaml(uo / "tiling" / "exhaustive_key_space.yaml") or {}
            graph = _load_yaml(uo / "ir" / "operator_graph.yaml") or {}
            count = int(keys.get("legal_key_count") or 0)
            if count <= 0:
                count = int(
                    keys.get("count")
                    or len(keys.get("keys") or keys.get("declared_keys") or [])
                    or 0
                )
            if count <= 0:
                return {
                    "ok": False,
                    "engine": "plan_build",
                    "error": "DECLARED_SET_EMPTY",
                    "mode": "tilingkey_full_coverage",
                }
            fp = str(keys.get("fingerprint") or graph.get("fingerprint") or "")
            obligations = {
                "schema": "coverage-obligations/v2",
                "mode": "tilingkey_full_coverage",
                "version": 2,
                "plan_hash": fp,
                "declared_set": {
                    "source": "uo/tiling/exhaustive_key_space.yaml",
                    "fingerprint": fp,
                    "count": count,
                    "legal_key_index": str(keys.get("legal_key_index") or ""),
                },
                "obligations": [
                    {
                        "id": "CLOSE_DECLARED_SET",
                        "kind": "set_closure",
                        "invariant": "D = (R ∩ D) ∪ E",
                    },
                    {
                        "id": "EXCLUSION_SOUNDNESS",
                        "kind": "proof_policy",
                        "invariant": "R ∩ E = ∅",
                    },
                    {
                        "id": "WITNESS_PROVENANCE",
                        "kind": "provenance",
                        "invariant": "every R key has successful replay evidence",
                    },
                    {
                        "id": "EXCLUSION_PROVENANCE",
                        "kind": "provenance",
                        "invariant": "every E key has verified rule evidence",
                    },
                ],
            }
            text = yaml.safe_dump(obligations, allow_unicode=True, sort_keys=False)
            obl = _tg(project_root) / "plan" / "levels" / level / "coverage_obligations.yaml"
            obl.parent.mkdir(parents=True, exist_ok=True)
            obl.write_text(text, encoding="utf-8")
            # plan-build-v1 also requires the root alias used by ownership/contracts.
            root_obl = _tg(project_root) / "plan" / "coverage_obligations.yaml"
            root_obl.parent.mkdir(parents=True, exist_ok=True)
            root_obl.write_text(text, encoding="utf-8")
            unresolved = {
                "schema": "tg-unresolved/v1",
                "status": "ready_for_manual_review",
                "allow_solve": True,
                "allow_solve_reason": "tilingkey_full_coverage T=D approved for closure",
                "blocking_hard_obligations": [],
                "contract_gaps": [],
                "plan_hash": fp,
            }
            unresolved_path = obl.parent / "unresolved.yaml"
            unresolved_path.write_text(
                yaml.safe_dump(unresolved, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return {
                "ok": True,
                "engine": "plan_build",
                "op_name": op_name,
                "level": level,
                "mode": "tilingkey_full_coverage",
                "artifact": obl.as_posix(),
                "root_artifact": root_obl.as_posix(),
                "unresolved": unresolved_path.as_posix(),
                "declared_count": count,
            }

        return {
            "ok": False,
            "engine": "plan_build",
            "error": "legacy CSV plan path removed; use tilingkey_full_coverage",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_build", "error": str(exc)[:400]}


def _run_tg_solve_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    from ascendc_pilot.source_snapshot import bind_snapshot_env, materialize_source_snapshot

    ident = materialize_source_snapshot(project_root)
    bind_snapshot_env(ident)
    arch = str(tg_ctx.get("architecture") or ctx.get("architecture") or "").strip() or None
    out = _tg(project_root, arch=arch) / "closure" / "source_snapshot.yaml"
    _dump_closure_yaml(out, ident)
    return {
        "ok": bool(ident.get("ok")),
        "engine": "solve_precheck",
        "mode": tg_ctx.get("mode"),
        "pre_gates": "runtime",
        "snapshot": ident,
        "artifact": out.as_posix(),
    }


def _run_tg_local_capability_bootstrap(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.local_extension import bootstrap_local_capability

    arch = str(ctx.get("architecture") or "").strip()
    interface = str(ctx.get("interface") or ctx.get("local_interface") or "case_builder")
    result = bootstrap_local_capability(
        project_root,
        interface,
        architecture=arch,
        reason=str(ctx.get("reason") or "LOCAL_CAPABILITY_REQUIRED"),
    )
    run_id = str(ctx.get("run_id") or "")
    receipt_path = ""
    if run_id:
        from ascendc_pilot.paths import runs_root

        dest = runs_root(project_root) / run_id / "actions" / "local_capability_bootstrap" / "receipt.yaml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        import yaml

        dest.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
        receipt_path = dest.as_posix()
        result["artifact"] = receipt_path
    result.setdefault("engine", "local_capability_bootstrap")
    return result




def _closure_ws(project_root: Path):
    from testcase_agent.closure import workspace as WS

    return WS.default_workspace(project_root).ensure()


def _dump_closure_yaml(path: Path, doc: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _closure_live_default(ctx: dict[str, Any], key: str) -> bool:
    """Production defaults to live Host; CI/synthetic may opt out explicitly."""
    if key in ctx:
        return bool(ctx.get(key))
    import os

    if str(os.environ.get("TG_CLOSURE_CI") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    if str(os.environ.get("UO_OPERATOR") or "").startswith("_synthetic"):
        return False
    return True


def _run_oracle_probe(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Oracle integrity probe — live Host by default (CI/synthetic may opt out)."""
    tg = _tg(project_root)
    ws = _closure_ws(project_root)
    from testcase_agent.closure.ledger import baseline_fingerprint

    baseline = baseline_fingerprint(project_root)
    issues: list[str] = []
    live: dict[str, Any] = {"attempted": False}
    try:
        from testcase_agent.closure import workspace as WS

        sch = WS.schema()
        if not sch.dims:
            issues.append("tiling schema has no dims")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"schema_unavailable: {exc}")

    live_probe = _closure_live_default(ctx, "live_probe")
    selfcheck_doc: dict[str, Any] = {}
    if live_probe:
        live["attempted"] = True
        try:
            from testcase_agent.closure import generate as G
            from testcase_agent.closure import oracle as O
            from testcase_agent.closure.oracle import HostOracle

            rng = __import__("random").Random(0)
            cases = [G.sample_case(rng) for _ in range(int(ctx.get("probe_n") or 10))]
            # One illegal / empty case for reject path when possible.
            oracle = HostOracle()
            verdicts = oracle.judge(cases, tag="oracle_probe")
            batch_accounting = oracle.last_accounting
            judged = batch_accounting["judged"]
            accepted = batch_accounting["accepted"]
            with_key = sum(1 for v in verdicts if v.key)
            live.update({
                "sent": len(cases),
                "judged": judged,
                "accepted": accepted,
                "with_key": with_key,
                "accounting": batch_accounting,
            })
            if not batch_accounting["conserved"]:
                issues.append("ORACLE_ACCOUNTING_MISMATCH")
            if batch_accounting["not_run"]:
                issues.append("ORACLE_SUSPECT:not_run")
                O.write_oracle_suspect(ws, "ORACLE_SUSPECT:not_run")
            if accepted == 0:
                issues.append("ORACLE_SUSPECT:accepted==0")
            if with_key == 0:
                issues.append("ORACLE_SUSPECT:accepted_with_key==0")

            # Strengthened selfcheck: DONE count, wide CSV, driver config, singleton dims.
            done_count = batch_accounting.get("judged")
            log_text = str(ctx.get("driver_log") or live.get("driver_log") or "")
            if log_text:
                done_count = O.count_done_marks(log_text)
            wide = ctx.get("wide_csv")
            if not wide:
                # Best-effort: newest key_cases CSV under artifacts.
                try:
                    cands = sorted(ws.artifacts.glob("*key_cases*.csv"), key=lambda p: p.stat().st_mtime)
                    wide = str(cands[-1]) if cands else None
                except Exception:
                    wide = None
            driver_doc = None
            try:
                from replay.package_data import resolve_adapter_file, package_file, load_yaml
                import yaml as _yaml

                man = resolve_adapter_file("operator.yaml") or package_file("operator.yaml")
                if man.is_file():
                    driver_doc = _yaml.safe_load(man.read_text(encoding="utf-8")) or {}
                proto = load_yaml("log_protocol.yaml", refresh=True)
                if proto:
                    driver_doc = {**(driver_doc or {}), **proto}
            except Exception:
                pass
            corpus_rows: list[dict[str, Any]] = []
            try:
                from testcase_agent.closure import corpus as C

                df = C.load(ws)
                if df is not None and not df.empty:
                    corpus_rows = df.to_dict(orient="records")
            except Exception:
                corpus_rows = []
            dim_names: list[str] = []
            try:
                dim_names = list(WS.dim_names())
            except Exception:
                dim_names = []
            selfcheck_doc = O.selfcheck(
                sent=len(cases),
                done_count=int(done_count) if done_count is not None else None,
                wide_csv=wide,
                driver_doc=driver_doc,
                corpus_rows=corpus_rows,
                dims=dim_names,
                ws=ws,
            )
            issues.extend(selfcheck_doc.get("issues") or [])
            live["selfcheck_warnings"] = list(selfcheck_doc.get("warnings") or [])
        except Exception as exc:  # noqa: BLE001
            issues.append(f"live_probe_failed: {exc}")
            live["error"] = str(exc)[:300]
    else:
        issues.append("live_probe_disabled: schema-only probe (CI/synthetic)")
        # Schema-only is allowed only when explicitly opted out; do not fail CI.
        if str((__import__("os").environ.get("TG_CLOSURE_CI") or "")).strip().lower() in {
            "1", "true", "yes",
        } or str((__import__("os").environ.get("UO_OPERATOR") or "")).startswith("_synthetic"):
            issues = [i for i in issues if not i.startswith("live_probe_disabled")]
        # Still run offline selfcheck pieces when artifacts exist.
        try:
            from testcase_agent.closure import oracle as O

            wide = ctx.get("wide_csv")
            selfcheck_doc = O.selfcheck(
                sent=ctx.get("sent"),
                done_count=ctx.get("done_count"),
                wide_csv=wide,
                driver_doc=ctx.get("driver_doc"),
                corpus_rows=ctx.get("corpus_rows"),
                dims=ctx.get("dims"),
                ws=ws,
            )
            # Offline mismatches still raise suspect, but CI schema-only may ignore.
            if selfcheck_doc.get("issues") and not (
                str((__import__("os").environ.get("TG_CLOSURE_CI") or "")).strip().lower()
                in {"1", "true", "yes"}
            ):
                issues.extend(selfcheck_doc["issues"])
            live["selfcheck_warnings"] = list(selfcheck_doc.get("warnings") or [])
        except Exception:
            pass

    doc = {
        "schema": "tg-oracle-probe/v3",
        "ok": len(issues) == 0,
        "issues": issues,
        "state": str(ws.state),
        "baseline": baseline,
        "live": live,
        "live_probe": live_probe,
        "selfcheck": selfcheck_doc,
        "note": (
            "Production requires live_probe; set TG_CLOSURE_CI=1 or UO_OPERATOR=_synthetic_* "
            "for schema-only CI probes"
        ),
    }
    out = tg / "closure" / "oracle_probe.yaml"
    _dump_closure_yaml(out, doc)
    return {"ok": doc["ok"], "engine": "oracle_probe", "artifact": out.as_posix(), **doc}


def _run_closure_ledger(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import ledger
    from testcase_agent.closure import lemma
    from testcase_agent.closure import closure_state

    ws = _closure_ws(project_root)
    try:
        rebuilt = ledger.rebuild(ws)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "closure_ledger", "error": str(exc)[:300]}
    # Only re-verify / apply already-promoted active rules. Package seed rules
    # must not enter E before lemma_review (methodology §6.5).
    try:
        current_fp = ""
        try:
            import yaml

            graph = _uo(project_root) / "ir" / "operator_graph.yaml"
            if graph.is_file():
                current_fp = str(
                    (yaml.safe_load(graph.read_text(encoding="utf-8")) or {}).get("fingerprint")
                    or ""
                )
        except Exception:
            current_fp = ""
        applied = lemma.reverify_active(ws, current_uo_graph_fingerprint=current_fp)
    except TypeError:
        # Older signature without fingerprint kwarg.
        try:
            applied = lemma.reverify_active(ws)
        except Exception as exc:  # noqa: BLE001
            applied = {"ok": False, "error": str(exc)[:200]}
    except Exception as exc:  # noqa: BLE001
        applied = {"ok": False, "error": str(exc)[:200]}
    st = ledger.state(ws)
    try:
        snapshot = closure_state.write(ws, relations=list(ctx.get("finite_relations") or []))
    except Exception as exc:  # noqa: BLE001
        snapshot = {"error": str(exc)[:200]}
    return {
        "ok": bool(rebuilt.get("ok", True)) and bool(applied.get("ok", True)) and not snapshot.get("error"),
        "engine": "closure_ledger",
        "rebuild": rebuilt,
        "apply_rules": {
            "excluded": applied.get("excluded"),
            "gap": applied.get("gap"),
            "revoked_count": applied.get("revoked_count", 0),
            "error": applied.get("error"),
        },
        "closure_state": snapshot,
        **st,
    }


def _run_closure_search(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    import os

    from testcase_agent.closure import search_round

    ws = _closure_ws(project_root)
    budget = int(ctx.get("budget") or 64)
    seed = int(ctx.get("seed") or 0)
    oracle = ctx.get("oracle")
    if oracle is None and (
        str(os.environ.get("TG_CLOSURE_CI") or "").strip().lower() in {"1", "true", "yes"}
        or str(os.environ.get("UO_OPERATOR") or "").startswith("_synthetic")
    ):
        try:
            from testcase_agent.closure.oracle import StubOracle

            keys = ctx.get("stub_keys") or []
            oracle = StubOracle(keys=[int(k) for k in keys] if keys else [1, 2, 3, 4])
        except Exception:
            oracle = None
    try:
        out = search_round.run_round(ws, budget=budget, seed=seed, oracle=oracle)
    except Exception as exc:  # noqa: BLE001
        # Still leave a round stub so the output contract is satisfiable.
        rounds = ws.state / "rounds" / "round_0001"
        rounds.mkdir(parents=True, exist_ok=True)
        stub = {
            "schema": "tg-closure-search-stub/v1",
            "ok": False,
            "error": str(exc)[:300],
            "new_R": 0,
        }
        _dump_closure_yaml(rounds / "progress.yaml", stub)
        return {"ok": False, "engine": "closure_search", **stub}
    return {"engine": "closure_search", **out}


def _run_closure_residual(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import residual
    from testcase_agent.closure import search_round

    ws = _closure_ws(project_root)
    analysis = residual.analyse(ws)
    routed = search_round.route(ws)
    reason = str(routed.get("reason") or "PROOF_BLOCKED")

    # Round budget for automatic rework (control plane closes the loop).
    budget = int(ctx.get("round_budget") or 32)
    budget_path = ws.state / "round_budget.yaml"
    used = 0
    try:
        import yaml

        if budget_path.is_file():
            used = int((yaml.safe_load(budget_path.read_text(encoding="utf-8")) or {}).get("used") or 0)
    except Exception:
        used = 0

    # Do not mutate workflow state inside this action. Controllers / acp
    # advance apply rework after the action receipt is finalized.
    auto_rework: dict[str, Any] = {"attempted": False, "deferred": True}
    escalate = reason in {"ORACLE_SUSPECT", "PROOF_BLOCKED"}
    needs_rework = reason not in {"GAP_ZERO"} and not escalate and used < budget
    if used >= budget and reason not in {"GAP_ZERO"} and not escalate:
        escalate = True
        reason = "PROOF_BLOCKED"
        auto_rework = {"attempted": False, "budget_exhausted": True, "used": used, "deferred": False}
        needs_rework = False
    elif needs_rework:
        used += 1
        try:
            import yaml

            budget_path.write_text(
                yaml.safe_dump(
                    {"used": used, "budget": budget, "last_reason": reason},
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
        auto_rework = {
            "attempted": False,
            "deferred": True,
            "reason_code": reason,
            "used": used,
            "budget": budget,
        }

    route_doc = {
        "schema": "tg-closure-route/v1",
        "reason": reason,
        "growth_match": routed.get("growth_match"),
        "round_budget": {"used": used, "budget": budget},
        "auto_rework": auto_rework,
        "rework_hint": (
            f"acp rework --reason {reason}"
            if needs_rework
            else ""
        ),
        "residual": {
            "open": analysis.get("open"),
            "distance": analysis.get("distance"),
            "mostly_distance_1": analysis.get("mostly_distance_1"),
        },
        "state": {k: routed.get(k) for k in ("declared", "R", "E", "gap", "violation")},
        "target_hit_rate": routed.get("target_hit_rate"),
        "rewrite_share": routed.get("rewrite_share"),
        "refuse_share": routed.get("refuse_share"),
        "round_growth": routed.get("round_growth") or {},
        "lemma_trigger": routed.get("lemma_trigger"),
        "construct_trigger": routed.get("construct_trigger"),
    }
    out = _tg(project_root) / "closure" / "route.yaml"
    _dump_closure_yaml(out, route_doc)

    new_r = None
    new_declared_r = None
    rounds_dir = ws.state / "rounds"
    if rounds_dir.is_dir():
        rounds = sorted(rounds_dir.glob("round_*"))
        if rounds:
            latest_prog = rounds[-1] / "progress.yaml"
            if latest_prog.is_file():
                try:
                    import yaml

                    prog_doc = yaml.safe_load(latest_prog.read_text(encoding="utf-8")) or {}
                    new_r = prog_doc.get("new_R")
                    new_declared_r = prog_doc.get("new_declared_R", new_r)
                except Exception:
                    new_r = None

    round_analysis = {
        "schema": "tg-closure-round-analysis/v1",
        "blame": analysis.get("blame"),
        "distance_histogram": analysis.get("distance"),
        "mostly_distance_1": analysis.get("mostly_distance_1"),
        "open_patterns": analysis.get("open_patterns"),
        "pattern_dims": analysis.get("pattern_dims"),
        "r_witness_values": analysis.get("r_witness_values"),
        "reason": reason,
        "growth_match": routed.get("growth_match"),
        "state": route_doc["state"],
        "target_hit_rate": routed.get("target_hit_rate"),
        "rewrite_share": routed.get("rewrite_share"),
        "refuse_share": routed.get("refuse_share"),
        "round_growth": routed.get("round_growth") or {},
        "lemma_trigger": routed.get("lemma_trigger"),
        "construct_trigger": routed.get("construct_trigger"),
        "new_R": new_r,
        "new_declared_R": new_declared_r,
        "timestamp": time.time(),
        "note": (
            "Analyse after every replay round. expected→lemma on rejects; "
            "unexpected→directed construct from discovered R + source."
        ),
    }
    analysis_out = _tg(project_root) / "closure" / "round_analysis.yaml"
    _dump_closure_yaml(analysis_out, round_analysis)
    stamp_path = ws.state / "round_analysis.stamp"
    stamp_path.write_text(str(round_analysis["timestamp"]), encoding="utf-8")

    return {
        "ok": True,
        "engine": "closure_residual",
        "reason_code": reason,
        "reason_codes": [reason],
        "needs_rework": needs_rework,
        "escalate": escalate,
        "artifact": out.as_posix(),
        "round_analysis": analysis_out.as_posix(),
        **route_doc,
    }


def _run_closure_construct(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import construct
    from testcase_agent.closure import residual
    from testcase_agent.closure import workspace as WS

    ws = _closure_ws(project_root)
    skip_gate = bool(ctx.get("skip_analysis_gate")) or os.environ.get("TG_SKIP_ANALYSIS_GATE") == "1"
    analysis_path = _tg(project_root) / "closure" / "round_analysis.yaml"
    stamp_path = ws.state / "round_analysis.stamp"
    if not skip_gate:
        if not analysis_path.is_file() or not stamp_path.is_file():
            return {
                "ok": False,
                "engine": "closure_construct",
                "reason": "ANALYSIS_REQUIRED",
                "error": "Host/residual round_analysis required before construct",
            }
        try:
            import yaml

            analysis_doc = yaml.safe_load(analysis_path.read_text(encoding="utf-8")) or {}
            analysis_ts = float(analysis_doc.get("timestamp") or 0)
            corpus_mtime = 0.0
            for pattern in ("*key_cases*.csv", "rounds/**/*key_cases*.csv"):
                for csv_path in ws.artifacts.glob(pattern):
                    if csv_path.is_file():
                        corpus_mtime = max(corpus_mtime, csv_path.stat().st_mtime)
            if corpus_mtime > analysis_ts + 1:
                return {
                    "ok": False,
                    "engine": "closure_construct",
                    "reason": "ANALYSIS_REQUIRED",
                    "error": "Host corpus newer than round_analysis; rerun residual",
                }
        except Exception:
            pass

    analysis = residual.analyse(ws)
    targets = residual.distance_one_targets(analysis)[: int(ctx.get("limit") or 32)]
    built = 0
    cases: list = []
    traces: list[dict[str, Any]] = []
    path_counts: dict[str, int] = {"hook": 0, "codemap": 0, "hints": 0, "empty": 0}
    for t in targets:
        key = t.get("key")
        try:
            inst = WS.decode(int(key))
            spelled, meta = construct.build_with_meta(inst)
            path = str(meta.get("path") or construct.last_build_path() or "empty")
            path_counts[path] = path_counts.get(path, 0) + 1
            codemap_traces = construct.last_traces()
            cases.extend(spelled)
            built += 1
            traces.append(
                {
                    "key": int(key),
                    "differing_dims": t.get("differing_dims"),
                    "spelled": len(spelled),
                    "path": path,
                    "codemap": codemap_traces,
                }
            )
        except Exception as exc:  # noqa: BLE001
            traces.append({"key": key, "error": str(exc)[:200]})
            continue
    # Production defaults to live Host; CI/synthetic may opt out.
    replayed = 0
    if cases and _closure_live_default(ctx, "live_replay"):
        try:
            from testcase_agent.closure.oracle import HostOracle

            verdicts = HostOracle().judge(cases[:64], tag="construct")
            replayed = sum(1 for v in verdicts if v.verdict)
            rows = []
            for i, v in enumerate(verdicts):
                if not v.verdict:
                    continue
                rows.append({
                    "ok": int(v.ok),
                    "tiling_key": int(v.key),
                    "reject": v.reject,
                    "_arm": "construct",
                })
            if rows:
                from testcase_agent.closure import corpus as C
                from testcase_agent.closure import ledger

                C.commit(rows, ws, name="construct_key_cases.csv")
                ledger.rebuild(ws)
        except Exception as exc:  # noqa: BLE001
            doc_err = str(exc)[:200]
        else:
            doc_err = ""
    else:
        doc_err = ""

    trace_with_codemap = sum(1 for x in traces if x.get("codemap"))
    trace_coverage = (trace_with_codemap / len(traces)) if traces else 0.0
    warnings: list[str] = []
    # trace_coverage cannot detect hook dominance: the hook path also emits
    # CodeMap traces, so it sits at 1.0 even when nothing was CodeMap-directed.
    codemap_share = (path_counts.get("codemap", 0) / built) if built else 0.0
    hook_share = (path_counts.get("hook", 0) / built) if built else 0.0
    if trace_coverage < 0.2 and built > 0:
        warnings.append("codemap_trace_low")
    if built > 0 and codemap_share < 0.5:
        warnings.append(
            f"construct_hook_dominated:codemap_share={codemap_share:.2f}"
        )
    construct_issues: list[str] = []
    if built > 0 and hook_share >= 1.0:
        # A hook may implement knobs but must not replace the CodeMap path.
        construct_issues.append(
            "construct_bypassed_codemap: every target came from the "
            "operator hook; CodeMap-directed construction produced nothing"
        )

    doc = {
        "schema": "tg-closure-construct/v1",
        "targets": len(targets),
        "built_cases": len(cases),
        "targets_decoded": built,
        "replayed": replayed,
        "sample_keys": [t.get("key") for t in targets[:10]],
        "error": doc_err,
        "codemap_directed": any(bool(x.get("codemap")) for x in traces),
        "trace_coverage": round(trace_coverage, 4),
        "path_counts": path_counts,
        "codemap_share": round(codemap_share, 4),
        "warnings": warnings,
        "issues": construct_issues,
    }
    out = _tg(project_root) / "closure" / "construct" / "targets.yaml"
    _dump_closure_yaml(out, doc)
    trace_path = _tg(project_root) / "closure" / "construct" / "trace.yaml"
    _dump_closure_yaml(
        trace_path,
        {"schema": "tg-closure-construct-trace/v1", "traces": traces[:64]},
    )
    ok = not construct_issues or bool(ctx.get("allow_hook_only"))
    return {
        "ok": ok,
        "engine": "closure_construct",
        "artifact": out.as_posix(),
        "trace": trace_path.as_posix(),
        "reason": "" if ok else "CODEMAP_PATH_REQUIRED",
        **doc,
    }


def _run_closure_explain(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    ws = _closure_ws(project_root)
    why = ws.state / "why.csv"
    ran = False
    err = ""
    result: dict[str, Any] = {}
    if _closure_live_default(ctx, "live_explain"):
        try:
            from testcase_agent.closure import construct
            from testcase_agent.closure import explain

            result = explain.run_explain(
                construct.build,
                open_limit=int(ctx.get("open_limit") or 60),
                per_target=int(ctx.get("per_target") or 24),
                ws=ws,
            )
            ran = True
            why = Path(result.get("path") or why)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:300]
            return {
                "ok": True,
                "engine": "closure_explain",
                "evidence": "none",
                "why_exists": why.is_file() if why else False,
                "path": "",
                "ran": False,
                "accepted": 0,
                "error": err,
            }
    doc = {
        "schema": "tg-closure-explain/v1",
        "why_exists": why.is_file() if why else False,
        "path": str(why) if why and why.is_file() else "",
        "ran": ran,
        "accepted": result.get("accepted", 0),
        "error": err,
    }
    out = _tg(project_root) / "closure" / "construct" / "explain_receipt.yaml"
    _dump_closure_yaml(out, doc)
    return {"ok": True, "engine": "closure_explain", **doc}


def _run_lemma_leads(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    from testcase_agent.closure import observations as OBS

    ws = _closure_ws(project_root)
    try:
        leads = OBS.build_leads(ws, top=40)
        err = str(leads.get("error") or "")
    except Exception as exc:  # noqa: BLE001
        leads = {
            "schema": "tg-lemma-leads/v1",
            "source": "oracle_observation",
            "observation_count": 0,
            "lead_count": 0,
            "leads": [],
            "pairs": [],
            "triples": [],
            "pair_count": 0,
            "triple_count": 0,
            "error": str(exc)[:300],
            "note": "lemma leads require Host REWRITE/REFUSE observations",
        }
        err = leads["error"]
    out = _tg(project_root) / "closure" / "lemmas" / "leads.yaml"
    _dump_closure_yaml(out, leads)
    return {
        "ok": not err,
        "engine": "lemma_leads",
        "artifact": out.as_posix(),
        "lead_count": int(leads.get("lead_count") or 0),
        "observation_count": int(leads.get("observation_count") or 0),
        "pair_count": int(leads.get("pair_count") or 0),
        "triple_count": int(leads.get("triple_count") or 0),
        "error": err,
    }


def _run_lemma_evidence(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic evidence packs for observation leads (pre-mine)."""
    del ctx
    from testcase_agent.closure import lemma_evidence as LE

    ws = _closure_ws(project_root)
    leads_path = _tg(project_root) / "closure" / "lemmas" / "leads.yaml"
    leads_doc = _load_yaml(leads_path) or {}
    try:
        out = LE.collect_for_leads(leads_doc, ws=ws, top=40)
        err = ""
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "written": [], "lead_count": 0, "error": str(exc)[:300]}
        err = str(exc)[:300]
    receipt = {
        "schema": "tg-lemma-evidence-batch/v1",
        "ok": bool(out.get("ok")),
        "lead_count": int(out.get("lead_count") or 0),
        "written": list(out.get("written") or []),
        "evidence_dir": str(
            out.get("evidence_dir")
            or (_tg(project_root) / "closure" / "lemmas" / "evidence")
        ),
        "error": err,
    }
    receipt_path = _tg(project_root) / "closure" / "lemmas" / "evidence_receipt.yaml"
    _dump_closure_yaml(receipt_path, receipt)
    return {
        "ok": bool(out.get("ok")) and not err,
        "engine": "lemma_evidence",
        "artifact": receipt_path.as_posix(),
        "lead_count": receipt["lead_count"],
        "written_count": len(receipt["written"]),
        "error": err,
    }


def _run_lemma_mine(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Producer scaffold — real proof writing is done by tg-lemma-producer subagent."""
    import yaml

    from ascendc_pilot.paths import agent_root

    run_id = str(ctx.get("run_id") or "local")
    parts = (
        agent_root(project_root)
        / "runs"
        / run_id
        / "actions"
        / "lemma_mine"
    )
    parts.mkdir(parents=True, exist_ok=True)
    leads = _load_yaml(_tg(project_root) / "closure" / "lemmas" / "leads.yaml") or {}
    lead_n = int(
        leads.get("lead_count")
        or len(leads.get("leads") or [])
        or (int(leads.get("pair_count") or 0) + int(leads.get("triple_count") or 0))
    )
    # Hand the producer minimised, R-consistent antecedents plus the values R
    # actually witnessed per dimension. Without these it has to invent
    # propositions and most get refuted on arrival.
    #
    # Aiming information, not a precondition: an operator whose key schema does
    # not parse still gets a staging contract, just without hypotheses. Catching
    # SystemExit is deliberate — the replay runner exits rather than raises when
    # it cannot locate the key header.
    hyp: dict[str, Any] = {}
    r_witness: dict[str, Any] = {}
    try:
        from testcase_agent.closure import hypothesis as HYP
        from testcase_agent.closure import residual as RES

        ws_mine = _closure_ws(project_root)
        analysis = RES.analyse(ws_mine)
        hyp = HYP.propose(ws_mine, analysis=analysis)
        r_witness = analysis.get("r_witness_values") or {}
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        hyp = {"unavailable": str(exc)[:300].splitlines()[0], "hypotheses": []}

    staging = {
        "schema": "tg-lemma-mine-staging/v1",
        "status": "awaiting_subagent",
        "lead_count": lead_n,
        "hypotheses": hyp.get("hypotheses") or [],
        "hypothesis_stats": {
            k: hyp.get(k)
            for k in (
                "open",
                "R",
                "candidate_count",
                "covered_open",
                "pattern_dims",
                "unavailable",
            )
            if hyp.get(k) is not None
        },
        "r_witness_values": r_witness,
        "contract": {
            "required_fields": [
                "proposition",
                "codemap_anchors",
                "obligations",
                "source_citations",
                "verdict",
            ],
            "verdict_enum": ["PROVED", "REFUTED", "INSUFFICIENT"],
            "obligation_status": ["OPEN", "CLOSED", "BLOCKED"],
            "rules": [
                "Each candidate must state P => Q as proposition",
                "codemap_anchors: list of {entity_id or relation_id, query}",
                "obligations: list of {id, status, evidence}",
                "source_citations: list of {file, line, quote}",
                "PROVED requires all required obligations CLOSED",
                "No empty candidates allowed for lemma_apply",
                "A hypothesis is not evidence: absence from R never proves unreachability",
                "Never exclude a value listed under r_witness_values[dim].in_R",
                "when values may be scalars, [a,b], {in:[...]} or {not_in:[...]}",
            ],
        },
        "instructions": (
            "Start from staging hypotheses: each is a minimised antecedent that no "
            "witness satisfies. For each one, either cite the host code that forbids "
            "the combination (verdict PROVED, obligations CLOSED) or mark it REFUTED / "
            "INSUFFICIENT with the reason. Write results to parts/part_0.yaml keeping "
            "the `when` clause as given unless the source says a weaker or stronger "
            "antecedent is the real one. Check r_witness_values before narrowing. "
            "Follow skills/source-proof/SKILL.md."
        ),
    }
    (parts / "staging.yaml").write_text(
        yaml.safe_dump(staging, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    part0 = parts / "parts" / "part_0.yaml"
    if not part0.is_file():
        part0.parent.mkdir(parents=True, exist_ok=True)
        _dump_closure_yaml(part0, {
            "schema": "tg-lemma-part/v1",
            "candidates": [],
            "note": "placeholder — producer replaces with cited lemmas per staging contract",
        })
    return {
        "ok": True,
        "engine": "lemma_mine",
        "staging": str(parts / "staging.yaml"),
        "need_subagent": True,
        "hypotheses": len(staging["hypotheses"]),
        "covered_open": hyp.get("covered_open"),
    }


def _run_lemma_review(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Referee scaffold — tg-closure-referee fills runs/.../review.yaml only."""
    import yaml

    run_id = str(ctx.get("run_id") or "local")
    from ascendc_pilot.paths import agent_root

    review_dir = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    existing = review_dir / "review.yaml"
    if existing.is_file():
        doc = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
    else:
        doc = {
            "schema": "tg-lemma-review/v1",
            "status": "awaiting_referee",
            "accepted": [],
            "rejected": [],
            "note": "Referee must verify source citations before lemma_apply",
        }
        existing.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    # Persistent canon is promoted by lemma_apply (deterministic), not referee.
    return {
        "ok": True,
        "engine": "lemma_review",
        "artifact": existing.as_posix(),
        "status": doc.get("status"),
    }


def _mine_candidates(project_root: Path, run_id: str) -> list[dict[str, Any]]:
    """Candidates written by lemma_mine, placeholders dropped."""
    from ascendc_pilot.paths import agent_root

    mine = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine"
    out: list[dict[str, Any]] = []
    paths = sorted(mine.glob("parts/*.yaml"))
    if not paths and (mine / "staging.yaml").is_file():
        paths = [mine / "staging.yaml"]
    for path in paths:
        doc = _load_yaml(path) or {}
        for cand in doc.get("candidates") or []:
            if not isinstance(cand, dict) or not cand:
                continue
            if "placeholder" in str(cand.get("note") or "").lower():
                continue
            out.append(cand)
    return out


def _verify_candidates(ws, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Project each candidate onto R and report refutations with witnesses."""
    from testcase_agent.closure import lemma

    checked = lemma.verify_lemmas(candidates, ws)
    return {
        "candidates": len(candidates),
        "survivors": checked.get("survivors"),
        "refuted": checked.get("refuted") or [],
        "closes": checked.get("closed"),
        "open_before": checked.get("open_before"),
        "open_after": checked.get("open_after"),
        "lemmas": checked.get("lemmas") or [],
    }


def _run_lemma_verify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Refute mined candidates against R before a referee reviews them.

    A candidate that some witness already satisfies is wrong no matter how good
    the prose is, and finding that out here costs nothing.
    """
    ws = _closure_ws(project_root)
    run_id = str(ctx.get("run_id") or "local")
    candidates = _mine_candidates(project_root, run_id)
    if not candidates:
        return {
            "ok": False,
            "engine": "lemma_verify",
            "reason": "PROOF_REQUIRED",
            "error": "no lemma_mine candidates to verify",
            "candidates": 0,
        }

    result = _verify_candidates(ws, candidates)
    doc = {
        "schema": "tg-lemma-verify/v1",
        **{k: result[k] for k in ("candidates", "survivors", "refuted", "closes", "open_before", "open_after")},
        "survivor_labels": [
            {"label": s.get("label"), "closes": s.get("closes")}
            for s in result["lemmas"]
        ],
    }
    from ascendc_pilot.paths import agent_root

    out = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_verify" / "verify.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    _dump_closure_yaml(out, doc)
    _dump_closure_yaml(_tg(project_root) / "closure" / "lemmas" / "verify.yaml", doc)
    return {
        "ok": True,
        "engine": "lemma_verify",
        "artifact": out.as_posix(),
        "reason": "REFUTED" if result["refuted"] else "",
        **doc,
    }


def _run_lemma_apply(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.closure import lemma

    ws = _closure_ws(project_root)
    tg = _tg(project_root)
    run_id = str(ctx.get("run_id") or "local")
    from ascendc_pilot.paths import agent_root

    review_path = (
        agent_root(project_root) / "runs" / run_id / "actions" / "lemma_review" / "review.yaml"
    )
    review = _load_yaml(review_path) or _load_yaml(tg / "closure" / "lemmas" / "reviews.yaml") or {}
    parts_dir = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine" / "parts"
    part_docs: list[dict[str, Any]] = []
    if parts_dir.is_dir():
        for part_path in sorted(parts_dir.glob("*.yaml")):
            doc = _load_yaml(part_path) or {}
            if doc:
                part_docs.append(doc)

    def _candidate_count(docs: list[dict[str, Any]]) -> int:
        total = 0
        for doc in docs:
            for cand in doc.get("candidates") or []:
                if isinstance(cand, dict) and cand:
                    note = str(cand.get("note") or "").lower()
                    if "placeholder" in note:
                        continue
                    total += 1
        return total

    accepted = list(review.get("accepted") or [])
    review_status = str(review.get("status") or "").strip().lower()
    candidate_n = _candidate_count(part_docs)

    if review_status in {"awaiting_referee", "pending", "open", ""} and not accepted:
        return {
            "ok": False,
            "engine": "lemma_apply",
            "reason": "REVIEW_REQUIRED",
            "error": "lemma_review awaiting referee before apply",
        }

    if not accepted:
        if part_docs and candidate_n == 0 and not ctx.get("allow_empty_apply"):
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": (
                    "lemma_mine produced no candidates; producer must write "
                    "PROVED/REFUTED certificates before apply"
                ),
            }
        if not part_docs and not ctx.get("allow_empty_apply"):
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": "lemma_mine parts missing; proof required before apply",
            }

    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("proposition") or "").strip():
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": "accepted entry missing proposition",
            }
        verdict = str(entry.get("verdict") or "").strip().upper()
        if verdict != "PROVED":
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROOF_REQUIRED",
                "error": f"accepted entry verdict must be PROVED (got {verdict or 'missing'})",
            }
        obligations = entry.get("obligations") or []
        if obligations:
            open_obs = [
                o for o in obligations
                if isinstance(o, dict)
                and str(o.get("status") or "").strip().upper() not in {"CLOSED"}
            ]
            if open_obs:
                return {
                    "ok": False,
                    "engine": "lemma_apply",
                    "reason": "PROOF_REQUIRED",
                    "error": "PROVED certificate has open obligations",
                }

    # Persist referee receipt into the closure ledger for subsequent rounds.
    if review:
        _dump_closure_yaml(tg / "closure" / "lemmas" / "reviews.yaml", review)
    promoted = {"promoted": 0}
    verification: dict[str, Any] = {}
    if accepted:
        # An accepted entry that a witness already satisfies must never reach E,
        # whatever the referee wrote.
        verification = _verify_candidates(ws, [e for e in accepted if isinstance(e, dict)])
        if verification["refuted"]:
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "REFUTED_BY_R",
                "error": (
                    f"{len(verification['refuted'])} accepted lemma(s) are satisfied "
                    "by real witnesses; they cannot exclude declared keys"
                ),
                "refuted": verification["refuted"],
            }

        from testcase_agent.closure import cold_start as _cs

        pre = _cs.require_cold_start(ws)
        if not pre["ok"]:
            return {
                "ok": False,
                "engine": "lemma_apply",
                "reason": "PROVENANCE_REQUIRED",
                "error": (
                    "E may not grow without a sealed cold start: "
                    f"{','.join(pre['issues'])}; run tg-cold-start before apply"
                ),
                "provenance": pre,
            }
        tg_ctx = _resolve_tg_ctx(project_root, ctx)
        uo = _uo(project_root, arch=tg_ctx.get("architecture"))
        man = _load_yaml(uo / "manifest.yaml") or {}
        promoted = lemma.promote_reviewed(
            review,
            ws,
            source_revision=str(man.get("source_revision") or ""),
            uo_graph_fingerprint=str(
                ((man.get("fingerprint") or man.get("graph_fingerprint") or ""))
            ),
        )
    out = lemma.apply_rules(ws, refresh=True)
    if promoted.get("promoted"):
        # E grew, so a saturated search may be worth reopening.
        try:
            from testcase_agent.closure import search_round

            search_round.clear_lockout(ws)
        except Exception:
            pass
    return {
        "engine": "lemma_apply",
        "promote": promoted,
        "verification": {
            k: verification.get(k) for k in ("candidates", "survivors", "closes")
        } if verification else {},
        **out,
    }


def _run_lemma_loop(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-entrant lemma convergence: analyse → hypothesize → verify → apply.

    Replaces the one-shot scripts under artifacts/fa-pr13. Each round records
    ``tg/closure/rounds/round_N/lemma.yaml``. The engine cannot invent source
    citations: when survivors need a producer proof it stops with
    ``NEED_PRODUCER`` and leaves the verified hypotheses in staging for the
    next mine/review turn. When proved candidates are already present it
    promotes them and continues until gap stops falling or the round budget
    is spent.
    """
    from testcase_agent.closure import hypothesis as HYP
    from testcase_agent.closure import ledger
    from testcase_agent.closure import residual as RES
    from ascendc_pilot.paths import agent_root

    ws = _closure_ws(project_root)
    run_id = str(ctx.get("run_id") or "local")
    max_rounds = int(ctx.get("max_rounds") or 8)
    rounds_dir = ws.state / "rounds"
    rounds_dir.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    stop_reason = "ROUND_BUDGET"
    final_st = ledger.state(ws)

    for i in range(max_rounds):
        analysis = RES.analyse(ws)
        gap_before = int(analysis.get("open") or 0)
        if gap_before == 0:
            stop_reason = "GAP_ZERO"
            final_st = ledger.state(ws)
            break

        hyp = HYP.propose(ws, analysis=analysis)
        hypotheses = list(hyp.get("hypotheses") or [])
        verification = _verify_candidates(ws, hypotheses) if hypotheses else {
            "candidates": 0, "survivors": 0, "refuted": [], "closes": 0, "lemmas": []
        }

        # Prefer already-proved candidates from mine parts / ctx; otherwise
        # stage the verified hypotheses for a producer.
        proved = [
            c for c in _mine_candidates(project_root, run_id)
            if str(c.get("verdict") or "").upper() == "PROVED"
        ]
        proved.extend(
            c for c in (ctx.get("proved") or [])
            if isinstance(c, dict) and str(c.get("verdict") or "").upper() == "PROVED"
        )

        apply_out: dict[str, Any] = {"skipped": True}
        if proved:
            # Re-verify proved set against R before promote.
            pv = _verify_candidates(ws, proved)
            survivors = [
                c for c in proved
                if not any(
                    str(r.get("label")) == str(c.get("label"))
                    for r in (pv.get("refuted") or [])
                )
            ]
            if not survivors:
                apply_out = {
                    "ok": False,
                    "reason": "REFUTED_BY_R",
                    "refuted": pv.get("refuted"),
                }
            else:
                apply_ctx = {
                    **ctx,
                    "run_id": run_id,
                    "review": {
                        "schema": "tg-lemma-review/v1",
                        "status": "accepted",
                        "accepted": survivors,
                        "rejected": [],
                    },
                }
                # lemma_apply reads review from disk normally; inject via the
                # same path the referee writes.
                review_dir = (
                    agent_root(project_root)
                    / "runs"
                    / run_id
                    / "actions"
                    / "lemma_review"
                )
                review_dir.mkdir(parents=True, exist_ok=True)
                _dump_closure_yaml(review_dir / "review.yaml", apply_ctx["review"])
                apply_out = _run_lemma_apply(project_root, apply_ctx)
        else:
            # Deterministic fallback: put verified hypotheses into mine staging
            # so a producer (or the next loop call after proof) can continue.
            mine_dir = (
                agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine"
            )
            mine_dir.mkdir(parents=True, exist_ok=True)
            staging = {
                "schema": "tg-lemma-mine-staging/v1",
                "status": "awaiting_subagent",
                "hypotheses": verification.get("lemmas") or hypotheses,
                "r_witness_values": analysis.get("r_witness_values") or {},
                "open_patterns": analysis.get("open_patterns") or [],
                "loop_round": i,
                "note": (
                    "Engine-verified antecedents for this round. Absence from R "
                    "is not unreachability — source proof required before apply."
                ),
            }
            _dump_closure_yaml(mine_dir / "staging.yaml", staging)
            apply_out = {
                "ok": False,
                "reason": "NEED_PRODUCER",
                "hypotheses": len(hypotheses),
                "survivors": verification.get("survivors"),
            }

        st_after = ledger.state(ws)
        gap_after = int(st_after.get("gap") or 0)
        round_doc = {
            "schema": "tg-lemma-loop-round/v1",
            "round": i,
            "gap_before": gap_before,
            "gap_after": gap_after,
            "hypotheses": len(hypotheses),
            "verify": {
                k: verification.get(k)
                for k in ("candidates", "survivors", "closes", "refuted")
            },
            "apply": {
                k: apply_out.get(k)
                for k in ("ok", "reason", "promote", "E", "gap", "error")
                if k in apply_out or apply_out.get(k) is not None
            },
            "state": st_after,
        }
        round_path = rounds_dir / f"round_{i}" / "lemma.yaml"
        round_path.parent.mkdir(parents=True, exist_ok=True)
        _dump_closure_yaml(round_path, round_doc)
        history.append(round_doc)
        final_st = st_after

        if gap_after == 0:
            stop_reason = "GAP_ZERO"
            break
        if apply_out.get("reason") == "NEED_PRODUCER":
            stop_reason = "NEED_PRODUCER"
            break
        if apply_out.get("reason") == "PROVENANCE_REQUIRED":
            stop_reason = "PROVENANCE_REQUIRED"
            break
        if gap_after >= gap_before:
            stop_reason = "GAP_STALLED"
            break

    summary = {
        "schema": "tg-lemma-loop/v1",
        "ok": stop_reason == "GAP_ZERO",
        "engine": "lemma_loop",
        "stop_reason": stop_reason,
        "rounds": len(history),
        "history": history,
        "state": final_st,
    }
    out = _tg(project_root) / "closure" / "lemma_loop.yaml"
    _dump_closure_yaml(out, summary)
    return {**summary, "artifact": out.as_posix()}


def _producer_id(project_root: Path, run_id: str) -> str:
    """Identity that mined the lemmas, read from lemma_mine parts/staging."""
    from ascendc_pilot.paths import agent_root

    mine = agent_root(project_root) / "runs" / run_id / "actions" / "lemma_mine"
    for path in sorted(mine.glob("parts/*.yaml")) + [mine / "staging.yaml"]:
        doc = _load_yaml(path) or {}
        pid = str(doc.get("producer_id") or doc.get("producer") or "").strip()
        if pid:
            return pid
    return ""


def _run_closure_audit(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Referee scaffold for post-apply invariant review (runs/.../review.yaml only)."""
    import yaml

    from testcase_agent.closure import ledger
    from testcase_agent.closure import lemma
    from ascendc_pilot.paths import agent_root

    run_id = str(ctx.get("run_id") or "local")
    ws = _closure_ws(project_root)
    st = ledger.state(ws)
    audit_dir = agent_root(project_root) / "runs" / run_id / "actions" / "closure_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    existing = audit_dir / "review.yaml"
    soundness = lemma.soundness_ok(ws)
    if existing.is_file():
        doc = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
        # A referee may set the verdict, but never invent the facts or the
        # writer_role — leaving role empty is how certify rejects a hand-written
        # review that bypasses this action.
        doc["state"] = st
        doc["soundness_ok"] = soundness
        existing.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    else:
        # auto_ok is an engine shortcut only: gap already closed and soundness
        # holds. Certify refuses auto_ok unless writer_role=engine.
        doc = {
            "schema": "tg-closure-audit/v1",
            "status": "awaiting_referee" if st.get("gap", 1) else "auto_ok",
            "state": st,
            "soundness_ok": soundness,
            "writer_role": "engine",
            "note": "Referee confirms I1–I4 before certify",
        }
        existing.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    status = str(doc.get("status") or "").strip().lower()
    # Scaffold may still be awaiting a human/subagent referee — do not claim success.
    awaiting = status in {"", "awaiting_referee", "pending", "open"}
    return {
        "ok": not awaiting,
        "engine": "closure_audit",
        "artifact": existing.as_posix(),
        "status": doc.get("status"),
        "needs_referee": awaiting,
        **st,
    }


def _run_closure_certify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate
    from ascendc_pilot.paths import agent_root
    from testcase_agent.closure import ledger
    from testcase_agent.closure import report

    ws = _closure_ws(project_root)
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    gate = run_named_gate(
        project_root,
        "closure_soundness",
        architecture=str(tg_ctx.get("architecture") or "") or None,
    )
    rep = report.report(ws, refresh=True)
    st = ledger.state(ws)

    uo = _uo(project_root, arch=tg_ctx.get("architecture"))
    man = _load_yaml(uo / "manifest.yaml") or {}
    uo_fp = str(man.get("fingerprint") or man.get("graph_fingerprint") or "")
    invariants = report.certify_invariants(ws, uo_graph_fingerprint=uo_fp)

    # Promote referee audit receipt into the durable closure ledger.
    run_id = str(ctx.get("run_id") or "local")
    audit_review = (
        agent_root(project_root) / "runs" / run_id / "actions" / "closure_audit" / "review.yaml"
    )
    audit_doc = _load_yaml(audit_review) or {}
    if audit_doc:
        _dump_closure_yaml(_tg(project_root) / "closure" / "audit_report.yaml", audit_doc)

    audit_status = str(audit_doc.get("status") or "").strip().lower()
    audit_reason = ""
    writer_role = str(audit_doc.get("writer_role") or "").strip().lower()
    # Never trust the verdict written in the file: recompute the facts it claims.
    from testcase_agent.closure import lemma as _lemma

    soundness_now = bool(_lemma.soundness_ok(ws))
    if not audit_doc:
        audit_ok = False
        audit_reason = "audit_missing"
    elif not writer_role:
        # Hand-written review.yaml without role is the bypass
        # certify_with_provenance.py used; refuse it by name.
        audit_ok = False
        audit_reason = "audit_writer_role_invalid"
    elif audit_status in {"awaiting_referee", "pending", "open", "fail", "failed", "reject", "rejected"}:
        audit_ok = False
        audit_reason = f"audit_status={audit_status or 'empty'}"
    elif audit_status == "auto_ok":
        # auto_ok is only an engine shortcut and must be re-derivable right now.
        if writer_role != "engine":
            audit_ok = False
            audit_reason = "audit_writer_role_invalid"
        else:
            audit_ok = soundness_now and bool(rep.get("gap_zero"))
            if not audit_ok:
                audit_reason = (
                    f"auto_ok_not_rederivable soundness={soundness_now} "
                    f"gap_zero={bool(rep.get('gap_zero'))}"
                )
    elif audit_status in {"pass", "passed", "accepted"}:
        # A human/model referee verdict requires writer_role=referee and an
        # identity distinct from the producer that mined the lemmas.
        referee_id = str(audit_doc.get("referee_id") or "").strip()
        producer_id = _producer_id(project_root, run_id)
        if writer_role != "referee":
            audit_ok = False
            audit_reason = "audit_writer_role_invalid"
        elif not referee_id:
            audit_ok = False
            audit_reason = "referee_id_missing"
        elif producer_id and referee_id == producer_id:
            audit_ok = False
            audit_reason = f"referee_equals_producer={referee_id}"
        else:
            audit_ok = soundness_now
            if not audit_ok:
                audit_reason = "referee_verdict_contradicts_soundness"
    else:
        audit_ok = False
        audit_reason = f"audit_status_unknown={audit_status}"

    cert = {
        "schema": "tg-closure-certificate/v1",
        "ok": (
            bool(gate.get("ok"))
            and bool(rep.get("gap_zero"))
            and bool(invariants.get("ok"))
            and audit_ok
        ),
        "gate": gate,
        "audit": {
            "ok": audit_ok,
            "status": audit_status or "missing",
            "path": audit_review.as_posix() if audit_review.is_file() else "",
            "soundness_ok": soundness_now,
            "reason": audit_reason,
            "writer_role": audit_doc.get("writer_role") or "",
        },
        "invariants": invariants,
        "report": {
            "gap_zero": rep.get("gap_zero"),
            "open": rep.get("open"),
            "problem_count": rep.get("problem_count"),
            "undeclared": rep.get("undeclared"),
            "undeclared_path": rep.get("undeclared_path"),
        },
        "state": st,
        "note": "R−D is reported separately and does not block D-closure when I9 path exists",
    }
    if not audit_ok:
        cert["error"] = f"closure_audit rejected: {audit_reason or 'unknown'}"
    out = _tg(project_root) / "closure" / "certificate.yaml"
    _dump_closure_yaml(out, cert)
    # Also drop a standalone undeclared defect receipt.
    if rep.get("undeclared_path"):
        defect = {
            "schema": "tg-undeclared-key-defect/v1",
            "count": rep.get("undeclared"),
            "path": rep.get("undeclared_path"),
        }
        _dump_closure_yaml(_tg(project_root) / "closure" / "undeclared_defect.yaml", defect)
    return {
        "ok": cert["ok"],
        "engine": "closure_certify",
        "artifact": out.as_posix(),
        **cert,
    }


def _run_tg_targeted_construct(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.harness import load_adapter
    from code_engineering.scenarios import merge_knobs

    arch = _resolve_ce_arch(project_root, ctx)
    ce_root = _ce(project_root, arch=arch)
    skeleton = _load_yaml(ce_root / "scenarios" / "scenario_set.yaml") or {}
    run_id = str(ctx.get("run_id") or "")
    staging = {}
    if run_id:
        staging = _load_yaml(
            project_root / ".ascendc-pilot" / arch / "runs" / run_id
            / "actions" / "scenario_knobs" / "staging.yaml"
        ) or {}
    doc = merge_knobs(skeleton, staging) if staging else skeleton
    items = [row for row in (doc.get("items") or []) if isinstance(row, dict) and row.get("id")]
    adapter = load_adapter(project_root, architecture=arch)
    dest_root = _tg(project_root, arch=arch) / "closure" / "scenarios"
    emitted: list[dict[str, Any]] = []
    for item in items:
        sid = str(item.get("id") or "")
        cases = adapter.retrieve(item)
        if sid == "P-ILLEGAL":
            patched = []
            for row in cases or [{"Testcase_Name": "illegal_disable", "enable": "disable"}]:
                payload = dict(row)
                payload["enable"] = "disable"
                patched.append(payload)
            cases = patched
        csv_path = dest_root / f"{sid}.csv"
        adapter.emit(cases, csv_path)
        emitted.append({
            "id": sid,
            "oracle": str(item.get("oracle") or ""),
            "csv": csv_path.as_posix(),
            "count": len(cases),
        })
    intent = _load_yaml(ce_root / "impact" / "change_test_intent.yaml") or {}
    for target in intent.get("targets") or []:
        if not isinstance(target, dict):
            continue
        oid = str(target.get("obligation_id") or "").strip()
        if not oid:
            continue
        sid = f"CTI-{oid}"
        row = {
            "Testcase_Name": sid,
            "obligation_id": oid,
            "kind": str(target.get("kind") or ""),
            "symbol": str(target.get("symbol") or ""),
        }
        pred = target.get("predicate") if isinstance(target.get("predicate"), dict) else {}
        for key, value in pred.items():
            row[str(key)] = value
        csv_path = dest_root / f"{sid}.csv"
        adapter.emit([row], csv_path)
        emitted.append({
            "id": sid,
            "oracle": "host_replay",
            "csv": csv_path.as_posix(),
            "count": 1,
            "obligation_id": oid,
            "kind": target.get("kind"),
        })
    from ascendc_pilot.actions.scenario_certificate import (
        live_source_fingerprint,
        live_uo_digest,
    )

    receipt = {
        "schema": "tg-targeted-construct/v1",
        "adapter": adapter.identity(),
        "scenarios": emitted,
        "source_fingerprint": live_source_fingerprint(project_root),
        "uo_digest": live_uo_digest(project_root, architecture=arch),
    }
    out = dest_root / "construct.yaml"
    _dump_ce_yaml(out, receipt)
    return {"ok": bool(emitted), "engine": "targeted_construct", "artifact": out.as_posix(), **receipt}


def _run_tg_harness_run(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.harness import load_adapter

    arch = _resolve_ce_arch(project_root, ctx)
    dest_root = _tg(project_root, arch=arch) / "closure" / "scenarios"
    construct = _load_yaml(dest_root / "construct.yaml") or {}
    adapter = load_adapter(project_root, architecture=arch)
    runs: list[dict[str, Any]] = []
    csv_paths: list[str] = []
    for row in construct.get("scenarios") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "")
        csv_path = Path(str(row.get("csv") or dest_root / f"{sid}.csv"))
        csv_paths.append(str(csv_path))
        oracle = str(row.get("oracle") or "")
        if sid == "P-ILLEGAL" or oracle == "none":
            runs.append({
                "id": sid,
                "ok": True,
                "mode": "none",
                "verdict": "skipped_by_design",
                "reason": "skipped_by_design",
                "csv": str(csv_path),
            })
            continue
        result = adapter.run(csv_path, oracle or "only_grad")
        result["id"] = sid
        reason = str(result.get("reason") or "")
        if reason == "disabled_no_npu" or str(result.get("verdict") or "") == "not_executed":
            result["verdict"] = "not_executed"
            result["ok"] = False
        runs.append(result)
    doc = {
        "schema": "tg-harness-run/v1",
        "adapter": adapter.identity(),
        "csv": csv_paths[0] if csv_paths else "",
        "runs": runs,
    }
    out = dest_root / "harness_results.yaml"
    _dump_ce_yaml(out, doc)
    from ascendc_pilot.actions.scenario_certificate import harness_row_pass

    ok = bool(runs) and all(harness_row_pass(row) for row in runs)
    from ascendc_pilot.actions.scenario_certificate import write_replay_receipt
    from ascendc_pilot.source_snapshot import snapshot_identity

    snap = snapshot_identity(project_root)
    construct_rows = {
        str(row.get("id") or ""): row
        for row in (construct.get("scenarios") or [])
        if isinstance(row, dict)
    }
    for row in runs:
        sid = str(row.get("id") or "")
        constructed = construct_rows.get(sid) or {}
        oracle = str(constructed.get("oracle") or row.get("mode") or "")
        reached = bool(row.get("target_reached"))
        reason = str(row.get("reason") or "")
        if not reached:
            # Host Replay is the only oracle that may set target_reached.
            reason = reason or "replay_not_executed"
        if oracle == "host_replay" and not reached:
            reason = reason or "replay_not_executed"
        write_replay_receipt(
            project_root,
            architecture=arch,
            scenario_id=sid,
            obligation_id=str(constructed.get("obligation_id") or ""),
            target_reached=reached,
            reason=reason,
            extra={
                "harness_ok": harness_row_pass(row),
                "csv": row.get("csv"),
                **snap,
            },
        )
    return {"ok": ok, "engine": "harness_run", "artifact": out.as_posix(), **doc}


def _run_tg_scenario_certify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.actions.scenario_certificate import evaluate_scenario_certificate

    arch = _resolve_ce_arch(project_root, ctx)
    cert = evaluate_scenario_certificate(project_root, architecture=arch)
    out = _tg(project_root, arch=arch) / "closure" / "scenario_certificate.yaml"
    _dump_ce_yaml(out, cert)
    return {"ok": bool(cert["ok"]), "engine": "scenario_certify", "artifact": out.as_posix(), **cert}


def _uo_op_ctx(project_root: Path, ctx: dict[str, Any]) -> tuple[Path, str, str]:
    uo = _uo(project_root)
    op_name = str(ctx.get("op_name") or "").strip()
    if not op_name:
        try:
            from ascendc_pilot.uo_artifacts import read_yaml

            man = read_yaml(uo / "manifest.yaml") or {}
            op_name = str(man.get("op_name") or "").strip()
        except Exception:  # noqa: BLE001
            op_name = ""
    architecture = str(ctx.get("architecture") or "").strip()
    if not architecture:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    return uo, op_name, architecture


def _uo_init_engine(action_id: str) -> EngineFn:
    def _run(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
        from uo_init.pilot_engines import ENGINES

        fn = ENGINES[action_id]
        return fn(Path(project_root), ctx or {})

    _run.__name__ = f"_run_uo_init_{action_id}"
    return _run


ENGINE_REGISTRY: dict[tuple[str, str], EngineFn] = {
    # CodeMap compiler public surface (5 Actions).
    ("uo-init", "prepare"): _uo_init_engine("prepare"),
    ("uo-init", "extract"): _uo_init_engine("extract"),
    ("uo-init", "analyze"): _uo_init_engine("analyze"),
    ("uo-init", "commit"): _uo_init_engine("commit"),
    ("uo-init", "verify"): _uo_init_engine("verify"),
    ("uo-update", "detect_changes"): _run_detect_changes,
    ("uo-update", "plan_update"): _run_plan_update,
    ("uo-update", "apply_update"): _run_apply_update,
    ("uo-update", "export_integrity"): _run_export_integrity,
    ("uo-update", "diff_summary"): _run_diff_summary,
    ("uo-update", "diff_only"): _run_diff_summary,
    ("ce-impact", "change_capture"): _run_ce_change_capture,
    ("ce-impact", "uo_freshness"): _run_ce_uo_freshness,
    ("ce-impact", "impact_slice"): _run_ce_impact_slice,
    ("ce-impact", "risk_classify"): _run_ce_risk_classify,
    ("ce-impact", "obligation_build"): _run_ce_obligation_build,
    ("ce-impact", "scenario_infer"): _run_ce_scenario_infer,
    ("ce-impact", "scenario_apply"): _run_ce_scenario_apply,
    ("ce-verify", "verify_gate"): _run_ce_verify_gate,
    ("ce-verify", "coverage_bridge"): _run_ce_coverage_bridge,
    ("ce-verify", "residual_analyse"): _run_ce_residual_analyse,
    ("ce-verify", "external_ingest"): _run_ce_external_ingest,
    ("ce-verify", "harness_evidence"): _run_ce_harness_evidence,
    ("ce-verify", "harness_evidence_check"): _run_ce_harness_evidence_check,
    ("ce-verify", "ce_certify"): _run_ce_certify,
    ("ce-intent", "intent_capture"): _run_ce_intent_capture,
    ("ce-intent", "kb_check"): _run_ce_intent_kb_check,
    ("ce-intent", "anchor_locate"): _run_ce_anchor_locate,
    ("ce-intent", "feature_promote"): _run_ce_feature_promote,
    ("ce-intent", "grill_promote"): _run_ce_grill_promote,
    ("ce-intent", "scenario_infer"): _run_ce_scenario_infer,
    ("ce-apply", "apply_gate"): _run_ce_apply_gate,
    ("ce-apply", "change_capture"): _run_ce_apply_capture,
    ("ce-apply", "patch_guard"): _run_ce_patch_guard,
    ("ce-apply", "codemap_refresh"): _run_ce_codemap_refresh,
    ("tg-init", "init_intent"): _run_tg_init_intent,
    ("tg-init", "kb_check"): _run_tg_kb_check,
    ("tg-init", "contract_build"): _run_tg_contract_build,
    ("tg-init", "semantic_bind"): _run_tg_semantic_bind,
    ("tg-init", "integrity_gate"): _run_tg_integrity,
    ("tg-init", "init_audit"): _run_tg_init_audit,
    ("tg-plan", "plan_intent"): _run_tg_plan_intent,
    ("tg-plan", "plan_scope"): _run_tg_plan_scope,
    ("tg-plan", "plan_precheck"): _run_tg_plan_precheck,
    ("tg-plan", "plan_build"): _run_tg_plan_build,
    ("tg-solve", "solve_precheck"): _run_tg_solve_precheck,
    ("tg-solve", "local_capability_bootstrap"): _run_tg_local_capability_bootstrap,
    ("tg-solve", "oracle_probe"): _run_oracle_probe,
    ("tg-solve", "closure_ledger"): _run_closure_ledger,
    ("tg-solve", "closure_search"): _run_closure_search,
    ("tg-solve", "closure_residual"): _run_closure_residual,
    ("tg-solve", "closure_construct"): _run_closure_construct,
    ("tg-solve", "closure_explain"): _run_closure_explain,
    ("tg-solve", "targeted_construct"): _run_tg_targeted_construct,
    ("tg-solve", "harness_run"): _run_tg_harness_run,
    ("tg-solve", "scenario_certify"): _run_tg_scenario_certify,
    ("tg-solve", "lemma_leads"): _run_lemma_leads,
    ("tg-solve", "lemma_evidence"): _run_lemma_evidence,
    ("tg-solve", "lemma_mine"): _run_lemma_mine,
    ("tg-solve", "lemma_verify"): _run_lemma_verify,
    ("tg-solve", "lemma_review"): _run_lemma_review,
    ("tg-solve", "lemma_apply"): _run_lemma_apply,
    ("tg-solve", "lemma_loop"): _run_lemma_loop,
    ("tg-solve", "closure_audit"): _run_closure_audit,
    ("tg-solve", "closure_certify"): _run_closure_certify,
}


# Output contract id → relative paths under .ascendc-pilot (existence + nonempty where applicable)
OUTPUT_CONTRACT_PATHS: dict[str, list[str]] = {
    # Layout artifacts + machine scope receipt (SSOT; composite overlay must match).
    "uo-prepare-v1": [
        "uo/manifest.yaml",
        "uo/operator.yaml",
        "uo/ir/build_variant.yaml",
        "uo/runs/{run_id}/scope/scope_validated.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
    ],
    "uo-extract-v1": [
        "uo/ir/host_extract_receipt.yaml",
        "uo/ir/kernel_ir.yaml",
    ],
    "uo-analyze-v1": [
        "uo/ir/unresolved.yaml",
        "uo/ir/codemap_analyze_receipt.yaml",
    ],
    "uo-commit-v1": ["uo/*.uo"],
    # verify audits the committed .uo; receipts live under uo/checks/
    "uo-verify-v1": ["uo/checks/integrity.yaml", "uo/checks/quality.yaml"],
    "integrity-v1": ["uo/checks/integrity.yaml"],
    "change-detect-v1": ["uo/diff/change_set.yaml"],
    "update-plan-v1": ["uo/summary/update_plan.yaml"],
    "update-apply-v1": [
        "uo/runs/{run_id}/update/receipt.yaml",
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
    ],
    "diff-summary-v1": [
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
        "uo/diff/impact.yaml",
        "uo/diff/unresolved.yaml",
    ],
    # kb-answer: subagent payload under Action lease (never uo/checks/*).
    # UO readiness is enforced by requires_uo_product + intake, not this contract.
    "kb-answer-v1": ["runs/{run_id}/actions/kb_lookup/answer.yaml"],
    "code-review-v1": [
        "ce/review/index.yaml",
        "ce/review/functional_report.yaml",
        "ce/review/bug_report.yaml",
    ],
    "change-capture-v1": ["ce/impact/change_capture.yaml"],
    "uo-freshness-v1": ["ce/impact/freshness.yaml"],
    "impact-slice-v1": ["ce/impact/impact_slice.yaml"],
    "risk-classify-v1": ["ce/impact/risk_classification.yaml"],
    "obligation-ledger-v1": [
        "ce/impact/obligations.yaml",
        "ce/impact/ledger.yaml",
        "ce/impact/change_test_intent.yaml",
        "ce/impact/tg_plan_intent.yaml",
    ],
    "ce-scenario-set-v1": ["ce/scenarios/scenario_set.yaml"],
    "scenario-knobs-staging-v1": [
        "runs/{run_id}/actions/scenario_knobs/parts/**",
        "runs/{run_id}/actions/scenario_knobs/staging.yaml",
    ],
    "scenario-confirm-v1": ["ce/scenarios/confirmation.yaml"],
    "scenario-plan-v1": ["tg/plan/scenario_plan.yaml"],
    "targeted-construct-v1": ["tg/closure/scenarios/**"],
    "harness-run-v1": ["tg/closure/scenarios/harness_results.yaml"],
    "harness-evidence-v1": ["ce/verify/harness_evidence.yaml"],
    "harness-evidence-check-v1": ["ce/verify/harness_evidence_check.yaml"],
    "scenario-coverage-v1": ["tg/closure/scenario_certificate.yaml"],
    "impact-audit-v1": ["ce/impact/audit_report.yaml"],
    "verify-gate-v1": ["ce/verify/gate.yaml"],
    "verify-code-review-v1": ["ce/verify/code_review.yaml"],
    "coverage-bridge-v1": ["ce/verify/tg_handoff.yaml"],
    "residual-analysis-v1": ["ce/verify/residual.yaml", "ce/verify/ledger.yaml"],
    "external-evidence-v1": ["ce/verify/external_evidence.yaml", "ce/verify/ledger.yaml"],
    "exclusion-review-v1": ["ce/verify/exclusion_review.yaml"],
    "ce-certificate-v1": ["ce/verify/certificate.yaml"],
    "intent-capture-v1": ["ce/intent/intent.yaml"],
    "intent-kb-check-v1": ["ce/intent/kb_check.yaml"],
    "intent-grill-v1": ["ce/intent/intent.yaml"],
    "intent-grill-staging-v1": [
        "runs/{run_id}/actions/intent_grill/parts/**",
        "runs/{run_id}/actions/intent_grill/staging.yaml",
    ],
    "intent-grilled-v1": ["ce/intent/grill_confirmation.yaml"],
    "feature-decompose-v1": ["ce/intent/feature_decomposition.yaml"],
    "feature-decompose-staging-v1": [
        "runs/{run_id}/actions/feature_decompose/parts/**",
        "runs/{run_id}/actions/feature_decompose/staging.yaml",
    ],
    "anchor-locate-v1": ["ce/intent/anchors.yaml"],
    "plan-review-v1": ["ce/intent/plan_review.yaml"],
    "intent-confirmed-v1": ["ce/intent/confirmation.yaml", "ce/intent/plan.md"],
    "apply-gate-v1": ["ce/apply/gate.yaml"],
    "apply-patch-v1": ["ce/apply/patch_notes.yaml"],
    "apply-capture-v1": ["ce/apply/change_capture.yaml"],
    "apply-patch-guard-v1": ["ce/apply/patch_report.yaml"],
    "codemap-refresh-v1": ["ce/apply/codemap_refresh.yaml"],
    "apply-report-v1": ["ce/apply/report.yaml"],
    "review-persist-v1": ["ce/review/persist.yaml"],
    "session-handoff-v1": ["ce/session_handoff.md"],
    # tg-init kb_check receipt: proves CodeMap .uo TG views are readable.
    "uo-ready-v1": ["runs/{run_id}/receipts/uo_ready.yaml"],
    "tg-init-intent-v1": ["tg/init/init_intent.yaml"],
    "tilingkey-contract-v1": [
        "tg/contract/tilingkey_contract.yaml",
    ],
    "tilingkey-binding-v1": [
        "tg/realization/binding_inventory.yaml",
        "tg/init/test_repo_inventory.yaml",
        "tg/init/test_repo_contract.yaml",
    ],
    "tilingkey-integrity-v1": [
        "runs/{run_id}/receipts/integrity_gate.yaml",
    ],
    "init-audit-v1": ["tg/init/audit_report.yaml"],
    "init-confirmed-v1": [
        "tg/init/status.yaml",
        "tg/init/kb_fingerprint.yaml",
        "tg/init/confirmation.yaml",
    ],
    "plan-scope-v1": ["tg/plan/levels/*/plan_scope.yaml"],
    "plan-intent-v1": ["tg/plan/plan_intent.yaml"],
    "plan-precheck-v1": [],
    "plan-build-v1": ["tg/plan"],
    "plan-approved-v1": ["tg/plan/levels/*/human_supplement.yaml"],
    # Precondition only; runtime pre_gates own the check. No published artifacts.
    "solve-precheck-v1": ["tg/closure/source_snapshot.yaml"],
    "local-capability-bootstrap-v1": [
        "runs/{run_id}/actions/local_capability_bootstrap/receipt.yaml",
    ],
    "oracle-probe-v1": ["tg/closure/oracle_probe.yaml"],
    "closure-ledger-v1": [
        "tg/closure/R.txt",
        "tg/closure/open.txt",
        "tg/closure/excluded.txt",
    ],
    "closure-search-v1": ["tg/closure/rounds/**"],
    "closure-residual-v1": ["tg/closure/route.yaml"],
    "closure-construct-v1": ["tg/closure/construct/**"],
    "closure-explain-v1": ["tg/closure/construct/explain_receipt.yaml"],
    "lemma-leads-v1": ["tg/closure/lemmas/leads.yaml"],
    "lemma-verify-v1": [
        "runs/{run_id}/actions/lemma_verify/verify.yaml",
        "tg/closure/lemmas/verify.yaml",
    ],
    "lemma-evidence-v1": [
        "tg/closure/lemmas/evidence_receipt.yaml",
        "tg/closure/lemmas/evidence/**",
    ],
    "lemma-mine-staging-v1": [
        "runs/{run_id}/actions/lemma_mine/parts/**",
    ],
    "lemma-mine-v1": [
        "runs/{run_id}/actions/lemma_mine/staging.yaml",
    ],
    "lemma-review-v1": [
        "runs/{run_id}/actions/lemma_review/review.yaml",
    ],
    "lemma-apply-v1": [
        "tg/closure/excluded.txt",
        "tg/closure/excluded_why.csv",
        "tg/closure/open.txt",
        "tg/closure/lemmas/reviews.yaml",
    ],
    "closure-audit-v1": [
        "runs/{run_id}/actions/closure_audit/review.yaml",
    ],
    "closure-certify-v1": [
        "tg/closure/certificate.yaml",
        "tg/closure/audit_report.yaml",
    ],
}

# Contracts that must contain at least one nonempty concrete artifact (not empty dir / empty file)
OUTPUT_CONTRACT_NONEMPTY_GLOBS: dict[str, list[str]] = {
    "change-detect-v1": [
        "uo/diff/change_set.yaml",
    ],
    "update-plan-v1": [
        "uo/summary/update_plan.yaml",
    ],
    "update-apply-v1": [
        "uo/runs/{run_id}/update/receipt.yaml",
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
    ],
    "diff-summary-v1": [
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
        "uo/diff/impact.yaml",
        "uo/diff/unresolved.yaml",
    ],
    "code-review-v1": [
        "ce/review/index.yaml",
        "ce/review/functional_report.yaml",
        "ce/review/bug_report.yaml",
    ],
    "review-persist-v1": [
        "ce/review/persist.yaml",
    ],
    "plan-build-v1": [
        "tg/plan/levels/*/coverage_obligations.yaml",
        "tg/plan/coverage_obligations.yaml",
    ],
    "tilingkey-contract-v1": [
        "tg/contract/tilingkey_contract.yaml",
    ],
    "tilingkey-binding-v1": [
        "tg/realization/binding_inventory.yaml",
        "tg/init/test_repo_inventory.yaml",
        "tg/init/test_repo_contract.yaml",
    ],
    "tilingkey-integrity-v1": [
        "runs/{run_id}/receipts/integrity_gate.yaml",
    ],
}


def invoke_engine(project_root: Path, workflow_id: str, action_id: str, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    from ascendc_pilot.progress import engine_span

    key = (workflow_id, action_id)
    fn = ENGINE_REGISTRY.get(key)
    if fn is None:
        return {"ok": False, "error": f"no deterministic engine for {workflow_id}/{action_id}"}
    payload = dict(ctx or {})
    payload["action_id"] = action_id
    payload["workflow_id"] = workflow_id
    if not str(payload.get("run_id") or "").strip():
        try:
            from ascendc_pilot.state import load_state

            payload["run_id"] = str(load_state(project_root).get("run_id") or "").strip()
        except Exception:  # noqa: BLE001
            pass
    with engine_span(workflow_id, action_id):
        try:
            return fn(project_root, payload)
        except Exception as exc:  # noqa: BLE001
            from ascendc_pilot.local_extension import LocalCapabilityRequired

            if isinstance(exc, LocalCapabilityRequired):
                payload = exc.as_dict()
                payload["reason_code"] = "LOCAL_CAPABILITY_REQUIRED"
                payload["error"] = "LOCAL_CAPABILITY_REQUIRED"
                payload["recovery_action"] = "local_capability_bootstrap"
                return payload
            raise
