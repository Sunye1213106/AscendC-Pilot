"""Per-type evidence scoring with independent necessity/severity.

Disposition (auto-accept vs LLM) is driven by score_profile thresholds and
required_evidence. Severity (blocking vs degraded) is driven by main-chain
necessity — never by low score alone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import write_yaml

# Confidence / verification tiers (④)
SOURCE_VERIFIED = "source_verified"
SEMANTIC_VERIFIED = "semantic_verified"
CANDIDATE = "candidate"
REJECTED = "rejected"
# Legacy aliases accepted as verified for closure.
_VERIFIED_ALIASES = frozenset({"verified", SOURCE_VERIFIED, SEMANTIC_VERIFIED})

SCORE_PROFILES: dict[str, dict[str, Any]] = {
    "entrypoint_node": {
        "auto_accept_threshold": 0.80,
        "required_evidence": ["path_or_symbol", "arch_compatible"],
    },
    "registration_edge": {
        "auto_accept_threshold": 0.80,
        "required_evidence": ["macro_text", "file_line"],
    },
    "call_edge": {
        "auto_accept_threshold": 0.85,
        "required_evidence": ["call_or_macro_instantiation"],
    },
    "io_slot_bind": {
        "auto_accept_threshold": 0.75,
        "required_evidence": ["registration", "accessor"],
    },
    "tilingdata_bridge": {
        "auto_accept_threshold": 0.90,
        "required_evidence": ["canonical_type", "field_path", "unit_consistent"],
    },
    "tilingkey_binding": {
        "auto_accept_threshold": 0.85,
        "required_evidence": ["schema_id", "arity_order_name_domain"],
    },
}

MAIN_CHAIN_ROLES = frozenset(
    {
        "public_host_entry",
        "operator_registration",
        "tiling_registry",
        "normal_impl",
        "varlen_impl",
        "empty_impl",
        "template_registration",
        "public_kernel_entry",
        "concrete_kernel_impl",
        "kernel_family",
        "template_dispatcher",
    }
)
MAIN_CHAIN_EDGE_TYPES = frozenset(
    {"registers", "dispatches_to", "selects", "instantiates", "maps_tilingdata", "binds_arg", "derives"}
)


def is_verified_confidence(value: Any) -> bool:
    return str(value or "").strip().casefold() in {v.casefold() for v in _VERIFIED_ALIASES}


def normalize_confidence(value: Any, *, verification_source: str | None = None) -> str:
    text = str(value or "").strip().casefold()
    if text in {SOURCE_VERIFIED, "verified"} and verification_source != "llm":
        return SOURCE_VERIFIED if text != "verified" or verification_source in {None, "source", "script"} else SOURCE_VERIFIED
    if text in {SEMANTIC_VERIFIED} or verification_source == "llm":
        if text in {"verified", SEMANTIC_VERIFIED}:
            return SEMANTIC_VERIFIED
    if text == REJECTED:
        return REJECTED
    if text in {CANDIDATE, "heuristic", "structurally_inferred"}:
        return CANDIDATE if text != "structurally_inferred" else "structurally_inferred"
    if text == "verified":
        return SOURCE_VERIFIED
    return text or CANDIDATE


def score_profile(object_type: str) -> dict[str, Any]:
    return dict(SCORE_PROFILES.get(object_type) or SCORE_PROFILES["call_edge"])


def evaluate_disposition(
    *,
    object_type: str,
    score: float,
    evidence_classes: list[str] | set[str] | None = None,
    conflicts: bool = False,
    necessity: str = "auxiliary",
) -> dict[str, Any]:
    """Return disposition independent of severity.

    necessity: main_chain | auxiliary
    """
    profile = score_profile(object_type)
    threshold = float(profile["auto_accept_threshold"])
    required = list(profile.get("required_evidence") or [])
    present = {str(x) for x in (evidence_classes or [])}
    missing = [r for r in required if r not in present]
    score_f = float(score)
    auto = score_f >= threshold and not missing and not conflicts
    if auto:
        disposition = "auto_accept"
        confidence = SOURCE_VERIFIED
    else:
        disposition = "llm_task"
        confidence = CANDIDATE

    # Severity is independent of score (②).
    if necessity == "main_chain":
        if disposition == "auto_accept":
            severity = "none"
        elif score_f >= 0.50:
            severity = "blocking"
            task_hint = "choose_edge"
        else:
            severity = "blocking"
            task_hint = "mark_missing"
    else:
        if disposition == "auto_accept":
            severity = "none"
            task_hint = None
        elif score_f >= 0.50:
            severity = "degraded"
            task_hint = "choose_edge"
        else:
            severity = "informational"
            task_hint = None
            disposition = "unresolved"

    return {
        "object_type": object_type,
        "score": score_f,
        "auto_accept_threshold": threshold,
        "required_evidence": required,
        "evidence_present": sorted(present),
        "evidence_missing": missing,
        "conflicts": conflicts,
        "disposition": disposition,
        "confidence": confidence,
        "necessity": necessity,
        "severity": severity,
        "task_hint": locals().get("task_hint"),
    }


def score_entrypoint_node(node: dict[str, Any], *, architecture: str = "arch35") -> dict[str, Any]:
    raw_conf = node.get("confidence")
    score: float
    if isinstance(raw_conf, (int, float)):
        score = float(raw_conf)
    elif isinstance(raw_conf, str) and raw_conf.strip():
        try:
            score = float(raw_conf)
        except ValueError:
            conf = normalize_confidence(raw_conf)
            score = 0.95 if is_verified_confidence(conf) else 0.55
    else:
        # Macro / verified status without numeric confidence must not score as 0.0.
        status = str(node.get("status") or "").casefold()
        if node.get("macro") or status in {"verified", "source_verified", "semantic_verified"}:
            score = 0.95
        else:
            score = 0.0
    evidence: list[str] = []
    loc = node.get("locator") or {}
    if loc.get("file_path") or node.get("symbol_ref"):
        evidence.append("path_or_symbol")
    arch = str(node.get("architecture") or "neutral")
    if arch in {architecture, "neutral"}:
        evidence.append("arch_compatible")
    if node.get("macro"):
        evidence.append("macro_text")
        evidence.append("file_line")
    role = str(node.get("role") or "")
    necessity = "main_chain" if role in MAIN_CHAIN_ROLES else "auxiliary"
    result = evaluate_disposition(
        object_type="entrypoint_node",
        score=score,
        evidence_classes=evidence,
        conflicts=bool(node.get("conflicts")),
        necessity=necessity,
    )
    # Contract-backed macros with locator are source-verified — never LLM mark_missing.
    if node.get("macro") and (loc.get("file_path") or node.get("symbol_ref")) and not node.get("conflicts"):
        result["disposition"] = "auto_accept"
        result["confidence"] = SOURCE_VERIFIED
        result["severity"] = "none"
        result["task_hint"] = None
        result["score"] = max(float(result.get("score") or 0.0), 0.95)
    result["target_id"] = node.get("id")
    result["role"] = role
    loc = node.get("locator") or {}
    if loc.get("file_path") or node.get("signature_snippet"):
        result["candidates"] = [
            {
                "id": f"cand_{node.get('id')}",
                "file_path": loc.get("file_path") or "",
                "symbol_ref": (node.get("symbol_ref") or {}).get("qualified_name")
                or node.get("name")
                or "",
                "snippet": node.get("signature_snippet") or loc.get("text") or "",
                "start_line": loc.get("start_line"),
                "score": score,
            }
        ]
    result["locator"] = loc
    result["file_path"] = loc.get("file_path")
    result["signature_snippet"] = node.get("signature_snippet")
    return result


def score_edge(edge: dict[str, Any], *, object_type: str | None = None) -> dict[str, Any]:
    etype = str(edge.get("type") or "")
    ot = object_type or ("registration_edge" if etype == "registers" else "call_edge")
    conf = normalize_confidence(edge.get("confidence"), verification_source=edge.get("verification_source"))
    if is_verified_confidence(conf):
        score = 0.95
    else:
        score = float(edge.get("score") or 0.45)
    evidence: list[str] = []
    evs = edge.get("evidence") or []
    for ev in evs:
        if not isinstance(ev, dict):
            continue
        if ev.get("macro"):
            evidence.append("macro_text")
            evidence.append("call_or_macro_instantiation")
        if ev.get("file_path") and (ev.get("line") or ev.get("start_line")):
            evidence.append("file_line")
        if ev.get("reason") in {"callsite", "macro_instantiation", "fluent_tiling"}:
            evidence.append("call_or_macro_instantiation")
    if ot == "registration_edge" and "macro_text" in evidence and "file_line" in evidence:
        pass
    necessity = "main_chain" if etype in MAIN_CHAIN_EDGE_TYPES else "auxiliary"
    # Heuristic-only edges stay candidate regardless of numeric score.
    conflicts = bool(edge.get("conflicts"))
    if conf == CANDIDATE and "call_or_macro_instantiation" not in evidence and ot == "call_edge":
        score = min(score, 0.55)
    result = evaluate_disposition(
        object_type=ot,
        score=score,
        evidence_classes=evidence,
        conflicts=conflicts,
        necessity=necessity,
    )
    # Preserve explicit source_verified from macros even if profile would LLM.
    if conf == SOURCE_VERIFIED and "macro_text" in evidence:
        result["disposition"] = "auto_accept"
        result["confidence"] = SOURCE_VERIFIED
        result["severity"] = "none"
        result["task_hint"] = None
    result["target_id"] = edge.get("id")
    result["edge_type"] = etype
    result["verification_source"] = edge.get("verification_source") or (
        "source" if result["confidence"] == SOURCE_VERIFIED else None
    )
    # Ground LLM tasks with real evidence windows when disposition needs review.
    candidates: list[dict[str, Any]] = []
    for i, ev in enumerate(evs):
        if not isinstance(ev, dict):
            continue
        fp = ev.get("file_path")
        if not fp:
            continue
        snippet = str(ev.get("snippet") or ev.get("macro") or ev.get("text") or "")[:200]
        candidates.append(
            {
                "id": f"{edge.get('id') or 'edge'}_ev{i}",
                "file_path": fp,
                "symbol_ref": edge.get("target") or edge.get("source") or edge.get("id"),
                "snippet": snippet,
                "line": ev.get("line") or ev.get("start_line"),
                "score": float(ev.get("score") or score),
            }
        )
    if candidates:
        result["candidates"] = candidates
        result["file_path"] = candidates[0].get("file_path")
        result["signature_snippet"] = candidates[0].get("snippet")
    return result


def score_io_slot(slot: dict[str, Any]) -> dict[str, Any]:
    evidence: list[str] = []
    if slot.get("evidence") or slot.get("name"):
        evidence.append("registration")
    if slot.get("host_accessors"):
        evidence.append("accessor")
    status = str(slot.get("binding_status") or "")
    if status == "verified" and "registration" in evidence and "accessor" in evidence:
        score = 0.9
    elif "registration" in evidence and "accessor" in evidence:
        score = 0.8
    elif "registration" in evidence or "accessor" in evidence:
        score = 0.55
    else:
        score = 0.3
    necessity = "main_chain" if slot.get("main_chain") or slot.get("slot") == 0 else "auxiliary"
    result = evaluate_disposition(
        object_type="io_slot_bind",
        score=score,
        evidence_classes=evidence,
        necessity=necessity,
    )
    result["target_id"] = slot.get("name") or f"slot[{slot.get('slot')}]"
    candidates: list[dict[str, Any]] = []
    for i, acc in enumerate(slot.get("host_accessors") or []):
        if not isinstance(acc, dict):
            continue
        fp = acc.get("file_path")
        if not fp:
            continue
        candidates.append(
            {
                "id": f"acc_{slot.get('name') or slot.get('slot')}_{i}",
                "file_path": fp,
                "symbol_ref": slot.get("name") or acc.get("api"),
                "snippet": str(acc.get("snippet") or acc.get("api") or "")[:120],
                "line": acc.get("line"),
                "score": score,
            }
        )
    for i, ev in enumerate(slot.get("evidence") or []):
        if not isinstance(ev, dict):
            continue
        fp = ev.get("file_path")
        if not fp:
            continue
        candidates.append(
            {
                "id": f"slot_ev_{slot.get('name') or slot.get('slot')}_{i}",
                "file_path": fp,
                "symbol_ref": slot.get("name"),
                "snippet": str(ev.get("snippet") or ev.get("text") or "")[:120],
                "line": ev.get("line") or ev.get("start_line"),
                "score": score,
            }
        )
    if candidates:
        result["candidates"] = candidates
        result["file_path"] = candidates[0].get("file_path")
        result["signature_snippet"] = candidates[0].get("snippet")
    return result


def score_tilingdata_bridge(bridge: dict[str, Any]) -> dict[str, Any]:
    evidence: list[str] = []
    if bridge.get("owning_type") or bridge.get("canonical_type"):
        evidence.append("canonical_type")
    if bridge.get("field_path"):
        evidence.append("field_path")
    if bridge.get("unit_id") or bridge.get("extraction_unit"):
        evidence.append("unit_consistent")
    conf = normalize_confidence(bridge.get("confidence"))
    score = 0.95 if is_verified_confidence(conf) else float(bridge.get("score") or 0.5)
    identity_complete = len(evidence) >= 3
    if not identity_complete:
        score = min(score, 0.6)
    # Incomplete / leaf-only fields must not mass-emit blocking choose_edge tasks.
    # Only explicit main_chain + required incomplete bridges stay blocking enrichment.
    explicit_required = bridge.get("required")
    explicit_main = bool(bridge.get("main_chain") or bridge.get("necessity") == "main_chain")
    if not identity_complete:
        necessity = "main_chain" if (explicit_required is True and explicit_main) else "auxiliary"
    elif explicit_required is False:
        necessity = "auxiliary"
    else:
        necessity = "main_chain"
    result = evaluate_disposition(
        object_type="tilingdata_bridge",
        score=score,
        evidence_classes=evidence,
        conflicts=bool(bridge.get("ambiguous")),
        necessity=necessity,
    )
    if not identity_complete and result.get("disposition") == "llm_task":
        result["task_hint"] = "evidence_enrichment"
        result["severity"] = "blocking" if necessity == "main_chain" else "degraded"
    if result.get("task_hint") == "choose_edge" and not identity_complete:
        result["task_hint"] = "evidence_enrichment"
        result["severity"] = "blocking" if necessity == "main_chain" else "degraded"

    result["target_id"] = bridge.get("id") or bridge.get("field_path")
    result["owning_type"] = bridge.get("owning_type")
    result["canonical_type"] = bridge.get("canonical_type")
    result["field_path"] = bridge.get("field_path")
    result["unit_id"] = bridge.get("unit_id")
    result["extraction_unit"] = bridge.get("extraction_unit")
    candidates: list[dict[str, Any]] = []
    for key, sym in (
        ("host_writer", bridge.get("host_writer")),
        ("kernel_reader", bridge.get("kernel_reader")),
    ):
        if not sym:
            continue
        loc = bridge.get(f"{key}_locator") or bridge.get("locator") or {}
        fp = loc.get("file_path") or bridge.get("file_path") or ""
        snippet = loc.get("snippet") or bridge.get("snippet") or ""
        start_line = loc.get("start_line") or bridge.get("start_line")
        for ev in bridge.get("evidence") or []:
            if isinstance(ev, dict) and ev.get("file_path"):
                fp = fp or str(ev.get("file_path"))
                start_line = start_line or ev.get("line") or ev.get("start_line")
                snippet = snippet or str(ev.get("snippet") or ev.get("text") or "")[:120]
        if fp or snippet:
            candidates.append(
                {
                    "id": f"cand_{sym}",
                    "file_path": fp,
                    "symbol_ref": str(sym),
                    "snippet": snippet,
                    "start_line": start_line,
                    "score": result.get("score"),
                    "role": key,
                }
            )
    if candidates:
        result["candidates"] = candidates
    elif result.get("task_hint") == "choose_edge":
        result["task_hint"] = "evidence_enrichment"
        result["severity"] = "blocking" if necessity == "main_chain" else "degraded"
    return result


def score_tilingkey_binding(binding: dict[str, Any]) -> dict[str, Any]:
    evidence: list[str] = []
    if binding.get("schema_id"):
        evidence.append("schema_id")
    aligned = bool(binding.get("arity_aligned") and binding.get("order_aligned") and binding.get("name_aligned"))
    if aligned or binding.get("fully_aligned"):
        evidence.append("arity_order_name_domain")
    conf = normalize_confidence(binding.get("confidence"))
    score = 0.95 if is_verified_confidence(conf) and aligned else float(binding.get("score") or (0.8 if aligned else 0.4))
    result = evaluate_disposition(
        object_type="tilingkey_binding",
        score=score,
        evidence_classes=evidence,
        conflicts=bool(binding.get("conflicts")),
        necessity="main_chain" if binding.get("input_derivable") else "auxiliary",
    )
    result["target_id"] = binding.get("id") or binding.get("key_name")
    return result


def multi_schema_needs_llm(
    *,
    schema_count: int,
    isolated: bool,
    binding_ambiguous: bool,
    registration_conflict: bool,
    shared_candidate_conflict: bool,
) -> bool:
    """⑨ multi-schema alone does not trigger LLM — only binding ambiguity."""
    if schema_count <= 1:
        return False
    if isolated and not binding_ambiguous and not registration_conflict and not shared_candidate_conflict:
        return False
    return binding_ambiguous or registration_conflict or shared_candidate_conflict


def detect_score_pre(uo_root: Path, *, architecture: str = "arch35", run_id: str = "") -> dict[str, Any]:
    """Checkpoint extract.pre_semantic — entrypoint / registration / boundary only."""
    from uo.scripts._ir_io import read_yaml
    from uo.scripts.llm_tasks import upsert_tasks_from_score_items

    ep = read_yaml(uo_root / "ir" / "entrypoint_graph.yaml") or {}
    boundary = read_yaml(uo_root / "ir" / "operator_boundary.yaml") or {}
    items: list[dict[str, Any]] = []
    for node in ep.get("nodes") or []:
        if isinstance(node, dict):
            items.append(score_entrypoint_node(node, architecture=architecture))
    for edge in ep.get("edges") or []:
        if isinstance(edge, dict):
            ot = "registration_edge" if edge.get("type") == "registers" else "call_edge"
            items.append(score_edge(edge, object_type=ot))
    for slot in (boundary.get("inputs") or []) + (boundary.get("attributes") or []):
        if isinstance(slot, dict):
            items.append(score_io_slot(slot))
    # Boundary extractor may emit grounded io_slot_bind hints when script binding is incomplete.
    for hint in boundary.get("llm_task_hints") or []:
        if not isinstance(hint, dict):
            continue
        hint_item = {
            "object_type": str(hint.get("type") or "io_slot_bind"),
            "disposition": "llm_task",
            "severity": str(hint.get("severity") or "blocking"),
            "task_hint": str(hint.get("type") or "io_slot_bind"),
            "target_id": hint.get("target"),
            "file_path": hint.get("file_path"),
            "signature_snippet": hint.get("snippet"),
            "candidates": list(hint.get("candidates") or []),
            "reason": hint.get("reason"),
            "score": 0.4,
            "confidence": "candidate",
        }
        if not hint_item["candidates"] and hint.get("file_path"):
            hint_item["candidates"] = [
                {
                    "id": f"hint_{hint.get('target')}_{hint.get('line')}",
                    "file_path": hint.get("file_path"),
                    "symbol_ref": hint.get("target"),
                    "snippet": hint.get("snippet") or "",
                    "line": hint.get("line"),
                    "score": 0.4,
                }
            ]
        items.append(hint_item)

    report = {
        "version": 1,
        "checkpoint": "extract.pre_semantic",
        "architecture": architecture,
        "items": items,
        "stats": _stats(items),
    }
    write_yaml(uo_root / "ir" / "score_report_pre.yaml", report)
    write_yaml(uo_root / "ir" / "score_report.yaml", report)  # latest partial
    snap = require_source_snapshot(uo_root, run_id=run_id or None)
    if not snap.get("ok"):
        return {
            "ok": False,
            "error": snap.get("error") or "SOURCE_SNAPSHOT_UNAVAILABLE",
            "detail": snap,
            "checkpoint": "extract.pre_semantic",
            "report": report,
        }
    tasks = upsert_tasks_from_score_items(
        uo_root,
        items,
        checkpoint="extract.pre_semantic",
        run_id=run_id,
        source_snapshot_hash=str(snap.get("hash") or ""),
        workflow_id=str(snap.get("workflow_id") or "uo-init"),
        score_phase="pre_semantic",
        eligible_for_adjudication=False,
    )
    return {"ok": True, "checkpoint": "extract.pre_semantic", "report": report, "tasks": tasks}


def detect_score_post(uo_root: Path, *, architecture: str = "arch35", run_id: str = "") -> dict[str, Any]:
    """Checkpoint extract.post_semantic — re-score entrypoints (post-macro) + bridge/key."""
    from uo.scripts._ir_io import read_yaml
    from uo.scripts.llm_tasks import (
        close_tasks_resolved_by_score,
        load_llm_tasks,
        save_llm_tasks,
        upsert_tasks_from_score_items,
    )
    from uo.scripts.semantic_task_triage import apply_triage_to_tasks, write_semantic_task_triage

    prereq = post_semantic_prerequisites(uo_root)
    if not prereq.get("ok"):
        return {
            "ok": False,
            "error": "POST_SEMANTIC_PREREQUISITE_MISSING",
            "missing": prereq.get("missing") or [],
            "checkpoint": "extract.post_semantic",
        }

    # Canonical post-semantic score: re-evaluate entrypoint graph AFTER macro materialization.
    ep = read_yaml(uo_root / "ir" / "entrypoint_graph.yaml") or {}
    boundary = read_yaml(uo_root / "ir" / "operator_boundary.yaml") or {}
    bridge = read_yaml(uo_root / "ir" / "bridge.yaml") or {}
    tilingkey = read_yaml(uo_root / "ir" / "tilingkey_space.yaml") or {}
    items: list[dict[str, Any]] = []
    for node in ep.get("nodes") or []:
        if isinstance(node, dict):
            items.append(score_entrypoint_node(node, architecture=architecture))
    for edge in ep.get("edges") or []:
        if isinstance(edge, dict):
            ot = "registration_edge" if edge.get("type") == "registers" else "call_edge"
            items.append(score_edge(edge, object_type=ot))
    for slot in (boundary.get("inputs") or []) + (boundary.get("attributes") or []):
        if isinstance(slot, dict):
            items.append(score_io_slot(slot))
    for b in bridge.get("tilingdata_bridges") or bridge.get("bridge_edges") or []:
        if isinstance(b, dict) and (b.get("type") in {None, "maps_tilingdata"} or "field_path" in b):
            items.append(score_tilingdata_bridge(b))
    for dim in tilingkey.get("dimensions") or tilingkey.get("bindings") or []:
        if isinstance(dim, dict):
            items.append(score_tilingkey_binding(dim))

    report = {
        "version": 1,
        "checkpoint": "extract.post_semantic",
        "architecture": architecture,
        "items": items,
        "post_items": items,
        "stats": _stats(items),
    }
    write_yaml(uo_root / "ir" / "score_report_post.yaml", report)
    write_yaml(uo_root / "ir" / "score_report.yaml", report)
    snap = require_source_snapshot(uo_root, run_id=run_id or None)
    if not snap.get("ok"):
        return {
            "ok": False,
            "error": snap.get("error") or "SOURCE_SNAPSHOT_UNAVAILABLE",
            "detail": snap,
            "checkpoint": "extract.post_semantic",
            "report": report,
        }

    # Close provisional pre tasks whose targets auto-accepted after macro materialization.
    closed = close_tasks_resolved_by_score(
        uo_root,
        items,
        current_run_id=str(run_id),
        reason="post_semantic_auto_accept",
    )

    llm_items = [i for i in items if i.get("disposition") == "llm_task"]
    tasks = upsert_tasks_from_score_items(
        uo_root,
        llm_items,
        checkpoint="extract.post_semantic",
        run_id=run_id,
        source_snapshot_hash=str(snap.get("hash") or ""),
        workflow_id=str(snap.get("workflow_id") or "uo-init"),
        score_phase="post_semantic",
        eligible_for_adjudication=None,  # set by triage
    )

    # Triage → annotate routes / phase blocking; write semantic_task_triage.yaml
    doc = load_llm_tasks(uo_root)
    run_tasks = [
        t
        for t in (doc.get("tasks") or [])
        if isinstance(t, dict) and str(t.get("run_id") or "") == str(run_id)
    ]
    apply_triage_to_tasks(run_tasks, uo_root=uo_root)
    save_llm_tasks(uo_root, doc)
    triage = write_semantic_task_triage(uo_root, tasks=run_tasks, run_id=str(run_id))

    return {
        "ok": True,
        "checkpoint": "extract.post_semantic",
        "report": report,
        "tasks": tasks,
        "closed_pre_tasks": closed,
        "triage": triage.get("stats"),
    }


def post_semantic_prerequisites(uo_root: Path) -> dict[str, Any]:
    """Shared Engine/Gate contract for detect_score_post.

    Requires extract_plan.yaml + host_subgraph.yaml + kernel_subgraph.yaml.
    Kernel is required by this contract (not optional) so Engine and Gate agree.
    """
    required = {
        "extract_plan.yaml": uo_root / "ir" / "extract_plan.yaml",
        "host_subgraph.yaml": uo_root / "ir" / "host_subgraph.yaml",
        "kernel_subgraph.yaml": uo_root / "ir" / "kernel_subgraph.yaml",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        return {
            "ok": False,
            "error": "POST_SEMANTIC_PREREQUISITE_MISSING",
            "missing": missing,
        }
    return {"ok": True, "missing": []}


def _stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(items),
        "auto_accept": sum(1 for i in items if i.get("disposition") == "auto_accept"),
        "llm_task": sum(1 for i in items if i.get("disposition") == "llm_task"),
        "blocking": sum(1 for i in items if i.get("severity") == "blocking"),
        "degraded": sum(1 for i in items if i.get("severity") == "degraded"),
        "informational": sum(1 for i in items if i.get("severity") == "informational"),
    }


def _resolve_current_run_id(uo_root: Path, run_id: str | None = None) -> str:
    if run_id and str(run_id).strip():
        return str(run_id).strip()
    from uo.scripts._ir_io import read_yaml

    manifest = read_yaml(uo_root / "manifest.yaml") or {}
    for key in ("current_run_id", "current_run"):
        val = str(manifest.get(key) or "").strip()
        if val:
            return val
    return ""


def _source_snapshot_result(uo_root: Path, run_id: str | None = None) -> dict[str, Any]:
    """Structured current-run source snapshot. Callers must check ``ok`` first."""
    from uo.scripts._ir_io import read_yaml

    rid = _resolve_current_run_id(uo_root, run_id)
    if not rid:
        return {"ok": False, "error": "SOURCE_SNAPSHOT_RUN_MISSING"}

    scope_path = uo_root / "runs" / rid / "scope" / "scope_confirmed.yaml"
    if not scope_path.is_file():
        return {
            "ok": False,
            "error": "SOURCE_SNAPSHOT_SCOPE_MISSING",
            "run_id": rid,
            "path": scope_path.as_posix(),
        }

    confirmed = read_yaml(scope_path) or {}
    if not isinstance(confirmed, dict):
        return {"ok": False, "error": "SOURCE_SNAPSHOT_SCOPE_INVALID", "run_id": rid}

    scope_run = str(confirmed.get("run_id") or (confirmed.get("artifact_identity") or {}).get("run_id") or "").strip()
    if scope_run and scope_run != rid:
        return {
            "ok": False,
            "error": "SOURCE_SNAPSHOT_SCOPE_RUN_MISMATCH",
            "run_id": rid,
            "scope_run_id": scope_run,
        }
    scope_wf = str(
        confirmed.get("workflow_id")
        or (confirmed.get("artifact_identity") or {}).get("workflow_id")
        or ""
    ).strip()
    scope_action = str(
        confirmed.get("action_id")
        or (confirmed.get("artifact_identity") or {}).get("action_id")
        or ""
    ).strip()
    if scope_action and scope_action != "scope_confirmation":
        return {
            "ok": False,
            "error": "SOURCE_SNAPSHOT_SCOPE_ACTION_MISMATCH",
            "expected": "scope_confirmation",
            "actual": scope_action,
        }

    paths: list[str] = []
    for item in confirmed.get("confirmed_source_files") or confirmed.get("confirmed_file_list") or []:
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]).replace("\\", "/"))
        elif isinstance(item, str):
            paths.append(item.replace("\\", "/"))
    paths = sorted(set(paths))

    # Resolve repo root for content hashing.
    repo_root: Path | None = None
    try:
        from uo._operator.run_context import source_root_for_operator

        operator_root = uo_root
        parent_uo = uo_root.parent if uo_root.name != "uo" else uo_root
        try:
            repo_root = source_root_for_operator(
                operator_root,
                parent_uo if (parent_uo / "manifest.yaml").is_file() else uo_root,
                rid,
            )
        except Exception:  # noqa: BLE001
            repo_root = None
    except Exception:  # noqa: BLE001
        repo_root = None
    if repo_root is None:
        for candidate in [uo_root, *uo_root.parents]:
            if (candidate / ".ascendc-pilot").is_dir() or (candidate / ".git").is_dir():
                repo_root = candidate
                break
    if repo_root is None:
        repo_root = uo_root.parent if uo_root.name == "uo" else uo_root

    file_hashes: dict[str, str] = {}
    for rel in paths:
        resolved: Path | None = None
        try:
            from uo.scripts.source_path import resolve_repo_source_path

            for root_try in (repo_root, uo_root, uo_root.parent, *list(uo_root.parents)[:3]):
                try:
                    hit = resolve_repo_source_path(root_try, rel)
                except Exception:  # noqa: BLE001
                    hit = None
                if hit is not None and Path(hit).is_file():
                    resolved = Path(hit)
                    break
                cand = Path(root_try) / rel
                if cand.is_file():
                    resolved = cand
                    break
        except Exception:  # noqa: BLE001
            resolved = None
        if resolved is None:
            for root_try in (repo_root, uo_root.parent, uo_root):
                cand = Path(root_try) / rel
                if cand.is_file():
                    resolved = cand
                    break
        if resolved is not None and resolved.is_file():
            file_hashes[rel] = hashlib.sha256(resolved.read_bytes()).hexdigest()[:16]
        else:
            file_hashes[rel] = "MISSING"

    material = {
        "run_id": rid,
        "workflow_id": scope_wf
        or str((read_yaml(uo_root / "manifest.yaml") or {}).get("workflow_id") or ""),
        "architecture": str(confirmed.get("architecture") or ""),
        "confirmed_source_files": paths,
        "file_content_hashes": file_hashes,
    }
    blob = json.dumps(material, sort_keys=True)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return {
        "ok": True,
        "hash": digest,
        "run_id": rid,
        "workflow_id": material["workflow_id"],
        "architecture": material["architecture"],
        "material": material,
    }


def _source_snapshot_hash(uo_root: Path, run_id: str | None = None) -> str:
    """Compatibility wrapper. Prefer ``_source_snapshot_result`` and check ``ok``.

    Returns the digest on success. On failure returns empty string — callers that
    still use this helper must treat empty / missing as fail-closed.
    """
    result = _source_snapshot_result(uo_root, run_id=run_id)
    if not result.get("ok"):
        return ""
    return str(result.get("hash") or "")


def require_source_snapshot(uo_root: Path, run_id: str | None = None) -> dict[str, Any]:
    """Fail-closed snapshot accessor used by score / tasks / ledger / rebuild."""
    result = _source_snapshot_result(uo_root, run_id=run_id)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": str(result.get("error") or "SOURCE_SNAPSHOT_UNAVAILABLE"),
            "detail": result,
        }
    return result
