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
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_changes", "error": str(exc)[:300]}
    if not op_name:
        return {"ok": False, "engine": "detect_changes", "error": "op_name required"}
    try:
        from uo_init.update import detect_kb_changes

        payload = detect_kb_changes(project_root, op_name, write=True, architecture=arch)
        out = uo / "diff" / "change_set.yaml"
        return {
            "ok": out.is_file(),
            "engine": "detect_changes",
            "artifact": out.as_posix() if out.is_file() else "",
            "scoped_change_count": payload.get("scoped_change_count"),
            "detection": payload.get("detection"),
            "worktree_dirty": payload.get("worktree_dirty"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_changes", "error": str(exc)[:300]}


def _run_plan_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_update", "error": str(exc)[:300]}
    if not op_name:
        return {"ok": False, "engine": "plan_update", "error": "op_name required"}
    try:
        from uo_init.update import detect_kb_changes, load_change_set_if_fresh, plan_kb_update

        change_set = load_change_set_if_fresh(uo, repo_root=project_root)
        reused = change_set is not None
        if change_set is None:
            change_set = detect_kb_changes(project_root, op_name, write=True, architecture=arch)
        plan_kb_update(project_root, op_name, change_set=change_set, write=True, architecture=arch)
        out = uo / "summary" / "update_plan.yaml"
        return {
            "ok": out.is_file(),
            "engine": "plan_update",
            "artifact": out.as_posix() if out.is_file() else "",
            "change_set_reused": reused,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_update", "error": str(exc)[:300]}


def _cann_not_ready(engine: str, ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fail closed with a user-facing CANN hint before clang work."""
    try:
        from uo_init.pilot_engines import _cann_env_block
    except Exception:  # noqa: BLE001
        return None
    return _cann_env_block(engine, ctx)


def _rebuild_failure_from_update(result: dict[str, Any] | None) -> dict[str, Any]:
    """Copy nested prepare_layout / clang errors out of update_operator status=fail."""
    from ascendc_pilot.actions.failure_text import preferred_failure_text

    payload = result if isinstance(result, dict) else {}
    for row in payload.get("action_results") or []:
        if not isinstance(row, dict) or row.get("ok"):
            continue
        inner = row.get("result") if isinstance(row.get("result"), dict) else {}
        merged = {**inner, "error": inner.get("error") or row.get("error")}
        return {
            "ok": False,
            "failed_rebuild_action": row.get("action"),
            "error": str(inner.get("error") or row.get("error") or "rebuild_action_failed"),
            "message_zh": preferred_failure_text(merged, fallback=str(row.get("error") or "")),
            "issues": list(inner.get("issues") or []),
        }
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    msg = str(receipt.get("message") or "")
    return {
        "ok": False,
        "error": msg or "APPLY_UPDATE_FAILED",
        "message_zh": msg,
        "issues": [],
    }


def _run_apply_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    blocked = _cann_not_ready("apply_update", ctx)
    if blocked is not None:
        return blocked
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_update", "error": str(exc)[:800]}
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
        payload = {
            "ok": eng_ok and (diff_ok or status == "blocked"),
            "engine": "apply_update",
            "receipt_present": receipt_ok,
            "diff_present": diff_ok,
            "publish_deferred": bool((result or {}).get("publish_deferred")),
            "run_id": (result.get("run_id") if isinstance(result, dict) else None) or run_id,
            "result_keys": list(result.keys())[:12] if isinstance(result, dict) else [],
            "status": status,
        }
        if not payload["ok"]:
            nested = _rebuild_failure_from_update(result if isinstance(result, dict) else {})
            payload["error"] = nested.get("error") or "APPLY_UPDATE_FAILED"
            payload["message_zh"] = nested.get("message_zh") or nested.get("error")
            payload["issues"] = nested.get("issues") or []
            payload["failed_rebuild_action"] = nested.get("failed_rebuild_action") or ""
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_update", "error": str(exc)[:800]}


def _run_diff_summary(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Emit canonical diff/ product from existing change_set/update_plan when fresh."""
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "diff_summary", "error": str(exc)[:300]}
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
            change_set = detect_kb_changes(project_root, op_name, write=True, architecture=arch)
        if plan is None:
            plan = plan_kb_update(
                project_root, op_name, change_set=change_set, write=True, architecture=arch
            )
        product = export_diff_product(
            project_root,
            op_name,
            change_set=change_set,
            update_plan=plan,
            write=True,
            architecture=arch,
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
        "mode": str(tg_ctx.get("mode") or ""),
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
    run_ctx = _load_yaml(_tg(project_root, arch=arch_hint) / "init.yaml") or {}
    if not isinstance(run_ctx, dict):
        run_ctx = {}
    init_intent = run_ctx
    plan_md = _tg(project_root, arch=arch_hint) / "plan.md"
    plan_intent: dict[str, Any] = {}
    if plan_md.is_file():
        try:
            from testcase_agent.products import parse_plan_fence

            plan_intent = parse_plan_fence(plan_md.read_text(encoding="utf-8"))
        except Exception:
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
        default="",
    )
    return {
        "op_name": op_name,
        "architecture": architecture,
        "level": level,
        "focus": focus,
        "test_script_root": test_script_root,
        "mode": mode,
    }



def _uo_op_ctx(project_root: Path, ctx: dict[str, Any]) -> tuple[Path, str, str]:
    architecture = str(ctx.get("architecture") or "").strip()
    if not architecture:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    uo = _uo(project_root, arch=architecture)
    op_name = str(ctx.get("op_name") or "").strip()
    if not op_name:
        try:
            from ascendc_pilot.uo_artifacts import read_yaml

            man = read_yaml(uo / "manifest.yaml") or {}
            op_name = str(man.get("op_name") or "").strip()
        except Exception:  # noqa: BLE001
            op_name = ""
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
    ("tg-init", "kb_check"): _run_tg_kb_check,
}

from ascendc_pilot.actions.tg_product import install as _install_tg_product

_install_tg_product(ENGINE_REGISTRY)



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
    "harness-evidence-v1": ["ce/verify/harness_evidence.yaml"],
    "harness-evidence-check-v1": ["ce/verify/harness_evidence_check.yaml"],
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
    "tg-init-v1": ["tg/init.yaml"],
    "tg-init-validate-v1": ["runs/{run_id}/receipts/validate_init.yaml"],
    "tg-init-confirmed-v1": ["tg/init.yaml"],
    "tg-repo-scan-v1": ["runs/{run_id}/receipts/repo_scan.yaml"],
    "tg-bind-staging-v1": [
        "runs/{run_id}/actions/bind_init/parts/**",
        "runs/{run_id}/actions/bind_init/staging.yaml",
    ],
    "plan-precheck-v1": [],
    "tg-plan-v1": ["tg/plan.md"],
    "tg-plan-staging-v1": [
        "runs/{run_id}/actions/plan_fuse/parts/**",
        "runs/{run_id}/actions/plan_fuse/staging.md",
        "runs/{run_id}/actions/plan_fuse/staging.yaml",
    ],
    "tg-plan-validate-v1": ["runs/{run_id}/receipts/plan_validate.yaml"],
    "tg-plan-approved-v1": ["tg/plan.md"],
    "solve-precheck-v1": [],
    "tg-cases-v1": ["tg/cases.csv", "tg/cases.xls", "tg/cases.xlsx"],
    "tg-construct-staging-v1": [
        "runs/{run_id}/actions/construct_cases/parts/**",
        "runs/{run_id}/actions/construct_cases/staging.yaml",
    ],
    "tg-replay-v1": ["runs/{run_id}/receipts/replay_round.yaml"],
    "tg-worklog-v1": ["tg/worklog.md"],
    "tg-analyze-staging-v1": [
        "runs/{run_id}/actions/analyze_round/parts/**",
        "runs/{run_id}/actions/analyze_round/staging.md",
        "runs/{run_id}/actions/analyze_round/staging.yaml",
    ],
    "tg-certify-v1": ["runs/{run_id}/receipts/solve_certify.yaml"],

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
