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
    score = float(node.get("confidence") or 0.0)
    if score > 1.0:
        # Already a string tier — treat verified as high.
        conf = normalize_confidence(node.get("confidence") or node.get("status"))
        score = 0.9 if is_verified_confidence(conf) else 0.55
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
    tasks = upsert_tasks_from_score_items(
        uo_root,
        items,
        checkpoint="extract.pre_semantic",
        run_id=run_id,
        source_snapshot_hash=_source_snapshot_hash(uo_root),
    )
    return {"ok": True, "checkpoint": "extract.pre_semantic", "report": report, "tasks": tasks}


def detect_score_post(uo_root: Path, *, architecture: str = "arch35", run_id: str = "") -> dict[str, Any]:
    """Checkpoint extract.post_semantic — bridge / tilingkey / provenance."""
    from uo.scripts._ir_io import read_yaml
    from uo.scripts.llm_tasks import upsert_tasks_from_score_items

    # Hard dependency: host/kernel or tilingkey must exist (①).
    host = uo_root / "ir" / "host_subgraph.yaml"
    kernel = uo_root / "ir" / "kernel_subgraph.yaml"
    plan = uo_root / "ir" / "extract_plan.yaml"
    if not host.is_file() and not kernel.is_file() and not plan.is_file():
        return {
            "ok": False,
            "error": "extract.post_semantic requires host/kernel/extract_plan artifacts",
            "checkpoint": "extract.post_semantic",
        }

    bridge = read_yaml(uo_root / "ir" / "bridge.yaml") or {}
    tilingkey = read_yaml(uo_root / "ir" / "tilingkey_space.yaml") or {}
    items: list[dict[str, Any]] = []
    for b in bridge.get("tilingdata_bridges") or bridge.get("bridge_edges") or []:
        if isinstance(b, dict) and (b.get("type") in {None, "maps_tilingdata"} or "field_path" in b):
            items.append(score_tilingdata_bridge(b))
    for dim in tilingkey.get("dimensions") or tilingkey.get("bindings") or []:
        if isinstance(dim, dict):
            items.append(score_tilingkey_binding(dim))

    # Merge with pre report if present.
    pre = read_yaml(uo_root / "ir" / "score_report_pre.yaml") or {}
    all_items = list(pre.get("items") or []) + items
    report = {
        "version": 1,
        "checkpoint": "extract.post_semantic",
        "architecture": architecture,
        "items": all_items,
        "post_items": items,
        "stats": _stats(all_items),
    }
    write_yaml(uo_root / "ir" / "score_report_post.yaml", report)
    write_yaml(uo_root / "ir" / "score_report.yaml", report)
    tasks = upsert_tasks_from_score_items(
        uo_root,
        items,
        checkpoint="extract.post_semantic",
        run_id=run_id,
        source_snapshot_hash=_source_snapshot_hash(uo_root),
    )
    return {"ok": True, "checkpoint": "extract.post_semantic", "report": report, "tasks": tasks}


def _stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(items),
        "auto_accept": sum(1 for i in items if i.get("disposition") == "auto_accept"),
        "llm_task": sum(1 for i in items if i.get("disposition") == "llm_task"),
        "blocking": sum(1 for i in items if i.get("severity") == "blocking"),
        "degraded": sum(1 for i in items if i.get("severity") == "degraded"),
        "informational": sum(1 for i in items if i.get("severity") == "informational"),
    }


def _source_snapshot_hash(uo_root: Path) -> str:
    scope = uo_root / "runs"
    paths: list[str] = []
    # Prefer confirmed scope list.
    from uo.scripts._ir_io import read_yaml

    for run_dir in sorted(p for p in scope.glob("*") if p.is_dir())[-3:]:
        confirmed = read_yaml(run_dir / "scope" / "scope_confirmed.yaml") or {}
        for item in confirmed.get("confirmed_source_files") or confirmed.get("confirmed_file_list") or []:
            if isinstance(item, dict) and item.get("path"):
                paths.append(str(item["path"]))
            elif isinstance(item, str):
                paths.append(item)
    blob = json.dumps(sorted(set(paths)), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
