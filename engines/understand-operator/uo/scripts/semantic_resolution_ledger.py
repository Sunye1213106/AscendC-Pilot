"""Semantic resolution ledger: patches never mutate derived graphs directly."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import atomic_write_yaml, commit_semantic_artifacts, read_yaml, write_yaml
from uo.scripts.evidence_score import SEMANTIC_VERIFIED, is_verified_confidence
from uo.scripts.semantic_patches import (
    LEDGER_TARGET_TYPE_MISMATCH,
    apply_patch_to_layers,
    verify_patch_against_layers,
)


class LedgerTargetTypeMismatch(Exception):
    """Patch target is a candidate node id, not a graph edge id."""

    code = LEDGER_TARGET_TYPE_MISMATCH


def load_ledger(uo_root: Path) -> dict[str, Any]:
    path = uo_root / "ir" / "semantic_resolution_ledger.yaml"
    data = read_yaml(path) or {}
    if not data:
        data = {"version": 1, "semantic_patches": []}
    data.setdefault("version", 1)
    data.setdefault("semantic_patches", [])
    return data


def save_ledger(uo_root: Path, payload: dict[str, Any]) -> Path:
    path = uo_root / "ir" / "semantic_resolution_ledger.yaml"
    write_yaml(path, payload)
    return path


def append_semantic_patch(uo_root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    doc = load_ledger(uo_root)
    record = dict(entry)
    record.setdefault("applied_at", datetime.now(timezone.utc).isoformat())
    record.setdefault("confidence", SEMANTIC_VERIFIED)
    record.setdefault("verification_source", "llm")
    doc["semantic_patches"].append(record)
    save_ledger(uo_root, doc)
    return record


def _is_candidate_node_id(value: Any) -> bool:
    s = str(value or "").strip()
    return s.startswith("cand_") or s.startswith("cand_EP_")


def _patch_targets(patch: dict[str, Any], *, by_id: dict[str, dict[str, Any]]) -> set[str]:
    edge_id = patch.get("edge_id")
    if edge_id:
        if _is_candidate_node_id(edge_id):
            raise LedgerTargetTypeMismatch(str(edge_id))
        return {str(edge_id)}
    accepted = [str(x) for x in (patch.get("accepted_candidate_ids") or [])]
    targets: set[str] = set()
    for cid in accepted:
        if cid in by_id:
            targets.add(cid)
    return targets


def _upgrade_edge(edge: dict[str, Any], patch: dict[str, Any]) -> None:
    edge["confidence"] = SEMANTIC_VERIFIED
    edge["verification_source"] = "llm"
    edge["ledger_task_id"] = patch.get("task_id")
    ptype = patch.get("patch_type")
    if ptype:
        edge["ledger_patch_type"] = ptype


def apply_ledger_to_entrypoint_graph(
    graph: dict[str, Any],
    ledger: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Deterministically rebuild edge confidence from active ledger patches.

    Kept for unit-test / legacy callers. Full rebuild uses ``apply_ledger_to_layers``.
    """
    if not ledger:
        return graph
    layers = {"entrypoint_graph": dict(graph), "operator_graph": dict(graph)}
    apply_ledger_to_layers(layers, ledger, strict=strict)
    return layers.get("entrypoint_graph") or graph


def apply_ledger_to_layers(
    layers: dict[str, dict[str, Any]],
    ledger: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Apply every active ledger patch onto the correct IR layer."""
    report: dict[str, Any] = {"patches": []}
    if not ledger:
        return report
    for patch in ledger.get("semantic_patches") or []:
        if not isinstance(patch, dict):
            continue
        result = apply_patch_to_layers(layers, patch)
        apply_status = str(result.get("apply_status") or "unconsumed")
        if apply_status == "invalid" and result.get("error") == LEDGER_TARGET_TYPE_MISMATCH and strict:
            raise LedgerTargetTypeMismatch(str(result.get("detail") or patch.get("edge_id") or ""))
        # Intermediate status during apply; final verify overwrites.
        if apply_status not in {"stale", "adjudicated_only"}:
            patch["apply_status"] = "pending" if result.get("ok") else apply_status
        else:
            patch["apply_status"] = apply_status
        if result.get("error"):
            patch["apply_error"] = result.get("error")
        if result.get("detail"):
            patch["apply_detail"] = result.get("detail")
        report["patches"].append(
            {
                "task_id": patch.get("task_id"),
                "patch_type": patch.get("patch_type"),
                "apply_status": patch.get("apply_status"),
                "error": result.get("error"),
            }
        )
    return report


def _verify_all_patches(
    layers: dict[str, dict[str, Any]],
    ledger: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    """Final materialization classification after all layers are patched."""
    materialized = 0
    unconsumed = 0
    report: dict[str, Any] = {"patches": [], "version": 1}
    for patch in ledger.get("semantic_patches") or []:
        if not isinstance(patch, dict):
            continue
        verified = verify_patch_against_layers(layers, patch)
        apply_status = str(verified.get("apply_status") or "unconsumed")
        patch["apply_status"] = apply_status
        if verified.get("error"):
            patch["apply_error"] = verified.get("error")
        if verified.get("detail"):
            patch["apply_detail"] = verified.get("detail")
        entry = {
            "task_id": patch.get("task_id"),
            "patch_type": patch.get("patch_type"),
            "apply_status": apply_status,
            "error": verified.get("error"),
        }
        report["patches"].append(entry)
        if apply_status == "materialized":
            materialized += 1
        elif apply_status in {"unconsumed", "invalid", "target_missing", "target_type_mismatch"}:
            # mark_missing / adjudicated_only / stale do not count as unconsumed blockers
            # for accept patches; mark_missing is tracked separately.
            if str(patch.get("action") or "") != "mark_missing" and str(patch.get("patch_type") or "") != "mark_missing":
                unconsumed += 1
        elif apply_status == "adjudicated_only":
            # mark_missing — not a materialization failure
            pass
    report["materialized_patch_count"] = materialized
    report["unconsumed_patch_count"] = unconsumed
    return report, materialized, unconsumed


# Back-compat alias used by older tests.
def _verify_patch_materialization(
    graph: dict[str, Any],
    ledger: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    layers = {"entrypoint_graph": graph, "operator_graph": graph}
    return _verify_all_patches(layers, ledger)


def rebuild_derived_graphs(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    run_id: str = "",
) -> dict[str, Any]:
    """Rebuild layered graphs from facts + ledger, then verify materialization.

    Correct order:
      1. Build base entrypoint graph from source facts
      2. Build host/kernel/function/tilingkey/bridge base layers
      3. Apply ledger patches by patch_type onto the right layers
      4. Recompute link status / Host+Kernel closure / extraction units
      5. Merge operator graph
      6. Verify ALL patch materialization (single final report)
      7. Update ledger apply_status
      8. Sync llm_tasks from materialization
      9. Atomically write ledger + tasks + apply_report
    """
    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.build_layered_kb import build_layered_kb
    from uo.scripts.evidence_score import require_source_snapshot
    from uo.scripts.llm_tasks import load_llm_tasks, sync_tasks_from_materialization
    from uo.scripts.resolve_entrypoints import (
        _apply_link_status,
        _build_extraction_units,
        _evaluate_closure,
        collect_entrypoint_candidates,
    )

    uo_root = existing_operator_root(repo_root, op_name)
    snap_res = require_source_snapshot(uo_root, run_id=run_id or None)
    if not snap_res.get("ok"):
        return {
            "ok": False,
            "error": snap_res.get("error") or "SOURCE_SNAPSHOT_UNAVAILABLE",
            "detail": snap_res,
        }
    snap = str(snap_res.get("hash") or "")
    stale = invalidate_stale_patches(uo_root, current_source_hash=snap)
    ledger = load_ledger(uo_root)
    current_run_id = str(run_id or "").strip()
    if not current_run_id:
        return {
            "ok": False,
            "error": "LEDGER_RUN_ID_MISSING",
            "message": "rebuild_derived_graphs requires current run_id",
            "stale_patches": stale,
        }

    # Stamp / validate ledger document identity.
    ledger = dict(ledger)
    ledger.setdefault("version", 1)
    identity = ledger.get("artifact_identity") if isinstance(ledger.get("artifact_identity"), dict) else {}
    ledger["artifact_identity"] = {
        **dict(identity),
        "run_id": current_run_id,
        "workflow_id": str(identity.get("workflow_id") or "uo-init"),
    }
    workflow_id = str(ledger["artifact_identity"].get("workflow_id") or "uo-init")

    # Default: only consume current-run semantic_patches (never legacy records[]).
    # Cross-run reuse requires ALL of: allow_cross_run_reuse, same source_snapshot_hash,
    # same workflow_id, and an allowed stable patch_type — then create a derived
    # reference for the current run (do not silently treat old records as current).
    _CROSS_RUN_REUSE_TYPES = frozenset(
        {
            "tilingdata_bridge_resolution",
            "entrypoint_dispatch_resolution",
            "call_edge_resolution",
            "template_instance_resolution",
            "entrypoint_node_resolution",
        }
    )
    filtered: list[dict[str, Any]] = []
    derived_refs: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    for rec in ledger.get("semantic_patches") or []:
        if not isinstance(rec, dict):
            continue
        preserved.append(rec)
        rec_run = str(rec.get("run_id") or "").strip()
        if not rec_run:
            return {
                "ok": False,
                "error": "LEDGER_RUN_ID_MISSING",
                "task_id": rec.get("task_id"),
                "stale_patches": stale,
            }
        if rec_run == current_run_id:
            if not str(rec.get("control_action_id") or "").strip() and not str(rec.get("actor_id") or "").strip():
                return {
                    "ok": False,
                    "error": "LEDGER_CONTROL_OWNER_MISSING",
                    "task_id": rec.get("task_id"),
                    "stale_patches": stale,
                }
            filtered.append(rec)
            continue
        # Cross-run: never consume unless explicit reuse is allowed.
        if not bool(rec.get("allow_cross_run_reuse")):
            continue
        if str(rec.get("source_snapshot_hash") or "") != snap:
            continue
        rec_wf = str(rec.get("workflow_id") or "").strip()
        if not rec_wf or rec_wf != workflow_id:
            continue
        ptype = str(rec.get("patch_type") or "").strip()
        if ptype not in _CROSS_RUN_REUSE_TYPES:
            continue
        # Create a derived reference owned by the current run (do not mutate old record).
        derived = dict(rec)
        derived["run_id"] = current_run_id
        derived["workflow_id"] = workflow_id
        derived["reused_from_run_id"] = rec_run
        derived["reused_from_task_id"] = rec.get("task_id")
        derived["status"] = rec.get("status") or "active"
        derived_refs.append(derived)
        filtered.append(derived)

    # Persist: keep all historical patches + newly derived current-run refs.
    ledger["semantic_patches"] = preserved + derived_refs
    # Working ledger for apply/verify uses only filtered current-run (+ derived) patches.
    working_ledger = dict(ledger)
    working_ledger["semantic_patches"] = filtered

    # 1. Base entrypoint graph from source facts (no ledger yet).
    candidates = collect_entrypoint_candidates(repo_root, op_name, architecture=architecture)
    entrypoint_graph = dict(candidates.get("entrypoint_graph") or {})

    # 2. Build host/kernel/tilingkey/bridge base layers.
    layers_set = {"host", "kernel", "tilingkey", "bridge"}
    try:
        layered = build_layered_kb(
            repo_root,
            op_name,
            architecture=architecture,
            layers=layers_set,
            allow_empty_plan=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300], "stale_patches": stale}

    host = read_yaml(uo_root / "ir" / "host_subgraph.yaml") or {}
    kernel = read_yaml(uo_root / "ir" / "kernel_subgraph.yaml") or {}
    bridge = read_yaml(uo_root / "ir" / "bridge.yaml") or {}
    operator_graph = read_yaml(uo_root / "ir" / "operator_graph.yaml") or (
        layered if isinstance(layered, dict) else {}
    )

    layers: dict[str, dict[str, Any]] = {
        "entrypoint_graph": entrypoint_graph,
        "host_subgraph": host if isinstance(host, dict) else {},
        "kernel_subgraph": kernel if isinstance(kernel, dict) else {},
        "bridge": bridge if isinstance(bridge, dict) else {},
        "operator_graph": operator_graph if isinstance(operator_graph, dict) else {},
    }

    # 3. Apply ledger patches onto corresponding layers (current-run filtered only).
    try:
        apply_ledger_to_layers(layers, working_ledger, strict=True)
    except LedgerTargetTypeMismatch as exc:
        return {
            "ok": False,
            "error": LedgerTargetTypeMismatch.code,
            "detail": str(exc),
            "stale_patches": stale,
        }

    # 4. Recompute link status / closures on entrypoint graph.
    ep = layers["entrypoint_graph"]
    nodes = {n["id"]: dict(n) for n in ep.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    edges = [dict(e) for e in (ep.get("edges") or []) if isinstance(e, dict)]
    _apply_link_status(nodes, edges)
    closure = _evaluate_closure(nodes, edges, architecture)
    extraction_units = _build_extraction_units(nodes, edges, architecture)
    ep["nodes"] = sorted(nodes.values(), key=lambda n: (n.get("role") or "", n.get("id") or ""))
    ep["edges"] = edges
    ep["closure"] = closure
    ep["extraction_units"] = extraction_units
    layers["entrypoint_graph"] = ep

    # 5. Merge ledger-touched edges into operator graph when missing.
    op = layers.get("operator_graph") or {"nodes": [], "edges": []}
    op_nodes = {str(n.get("id")): n for n in (op.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    op_edges = {str(e.get("id")): e for e in (op.get("edges") or []) if isinstance(e, dict) and e.get("id")}
    for n in ep.get("nodes") or []:
        if isinstance(n, dict) and n.get("id") and str(n["id"]) not in op_nodes:
            op_nodes[str(n["id"])] = n
    for e in ep.get("edges") or []:
        if isinstance(e, dict) and e.get("id"):
            op_edges[str(e["id"])] = e
    # Also keep bridge edges.
    for e in (layers.get("bridge") or {}).get("bridge_edges") or []:
        if isinstance(e, dict) and e.get("id"):
            op_edges[str(e["id"])] = e
    op["nodes"] = list(op_nodes.values())
    op["edges"] = list(op_edges.values())
    layers["operator_graph"] = op

    # 6. Final materialization verification (ONLY after all layers ready).
    apply_report, materialized, unconsumed = _verify_all_patches(layers, working_ledger)

    # Merge apply_status updates from working_ledger back into the full persisted ledger.
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in working_ledger.get("semantic_patches") or []:
        if isinstance(rec, dict):
            by_key[(str(rec.get("run_id") or ""), str(rec.get("task_id") or ""))] = rec
    merged_patches: list[dict[str, Any]] = []
    seen_derived: set[tuple[str, str]] = set()
    for rec in ledger.get("semantic_patches") or []:
        if not isinstance(rec, dict):
            continue
        key = (str(rec.get("run_id") or ""), str(rec.get("task_id") or ""))
        updated = by_key.get(key)
        if updated is not None:
            merged_patches.append(updated)
            seen_derived.add(key)
        else:
            merged_patches.append(rec)
    for rec in working_ledger.get("semantic_patches") or []:
        if not isinstance(rec, dict):
            continue
        key = (str(rec.get("run_id") or ""), str(rec.get("task_id") or ""))
        if key not in seen_derived and rec.get("reused_from_run_id"):
            merged_patches.append(rec)
    ledger["semantic_patches"] = merged_patches

    # 8. Sync llm_tasks from materialization results (in-memory).
    tasks_doc = load_llm_tasks(uo_root)
    sync = sync_tasks_from_materialization(
        uo_root, working_ledger, current_run_id=current_run_id, mutate_doc=tasks_doc
    )
    if not sync.get("ok", True):
        return {
            "ok": False,
            "error": sync.get("error") or "LEDGER_RUN_ID_MISSING",
            "detail": sync,
            "stale_patches": stale,
        }

    # 9. Transactional write of ledger + tasks + apply_report, then graph YAMLs.
    try:
        commit_semantic_artifacts(
            uo_root,
            llm_tasks=sync.get("doc") or tasks_doc,
            ledger=ledger,
            apply_report=apply_report,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "SEMANTIC_TX_COMMIT_FAILED",
            "detail": str(exc)[:300],
            "stale_patches": stale,
        }

    # Derived graphs are rebuild outputs (not part of the semantic tx trio, but written after success).
    atomic_write_yaml(uo_root / "ir" / "entrypoint_graph.yaml", ep)
    atomic_write_yaml(uo_root / "ir" / "operator_graph.yaml", op)
    if layers.get("bridge"):
        atomic_write_yaml(uo_root / "ir" / "bridge.yaml", layers["bridge"])

    return {
        "ok": True,
        "stale_patches": stale,
        "source_snapshot_hash": snap,
        "node_count": len(op.get("nodes") or []),
        "edge_count": len(op.get("edges") or []),
        "closure": closure,
        "materialized_patch_count": materialized,
        "unconsumed_patch_count": unconsumed,
        "apply_report": apply_report,
        "tasks_closed": sync.get("closed_count"),
        "tasks_rework": sync.get("rework_count"),
    }


def invalidate_stale_patches(uo_root: Path, *, current_source_hash: str) -> list[str]:
    """Mark ledger patches stale when source snapshot no longer matches."""
    doc = load_ledger(uo_root)
    stale_ids: list[str] = []
    for patch in doc.get("semantic_patches") or []:
        if not isinstance(patch, dict):
            continue
        if patch.get("source_snapshot_hash") and patch["source_snapshot_hash"] != current_source_hash:
            patch["status"] = "stale"
            stale_ids.append(str(patch.get("task_id") or ""))
        else:
            patch.setdefault("status", "active")
    save_ledger(uo_root, doc)
    return stale_ids


def verified_edges_only(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in edges if is_verified_confidence(e.get("confidence"))]
