"""Typed semantic patch schemas, validators, and layer materializers.

Patches are validated at Apply time, stored verbatim in the ledger, then
materialized onto the appropriate IR layer during deterministic rebuild.
"""

from __future__ import annotations

from typing import Any, Callable

from uo.scripts.evidence_score import SEMANTIC_VERIFIED, is_verified_confidence
from uo.scripts.semantic_identity import mint_edge_id

# Stable error codes (hard contract).
SEMANTIC_TARGET_NOT_FOUND = "SEMANTIC_TARGET_NOT_FOUND"
SEMANTIC_TARGET_TYPE_MISMATCH = "SEMANTIC_TARGET_TYPE_MISMATCH"
SEMANTIC_PATCH_UNCONSUMED = "SEMANTIC_PATCH_UNCONSUMED"
SEMANTIC_PATCH_AMBIGUOUS = "SEMANTIC_PATCH_AMBIGUOUS"
SEMANTIC_PATCH_INVALID = "SEMANTIC_PATCH_INVALID"
LEDGER_TARGET_TYPE_MISMATCH = "LEDGER_TARGET_TYPE_MISMATCH"

TYPED_PATCH_TYPES = frozenset(
    {
        "entrypoint_node_resolution",
        "entrypoint_dispatch_resolution",
        "call_edge_resolution",
        "tilingdata_bridge_resolution",
        "template_instance_resolution",
        "edge_resolution",  # legacy edge upgrade
        "mark_missing",
    }
)

# Payload fields that must survive commit into the ledger.
TYPED_PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "entrypoint_node_resolution": ("node_id", "candidate_id"),
    "entrypoint_dispatch_resolution": ("source_node_id", "target_node_id", "relation"),
    "call_edge_resolution": ("caller_function_id", "callee_function_id", "callsite"),
    "tilingdata_bridge_resolution": (
        "host_field_id",
        "kernel_field_id",
        "owning_type",
        "field_path",
        "unit_id",
        "relation",
    ),
    "template_instance_resolution": (
        "tilingkey_value_id",
        "template_instance_id",
        "kernel_entry_id",
    ),
}


def _is_candidate_node_id(value: Any) -> bool:
    s = str(value or "").strip()
    return s.startswith("cand_") or s.startswith("cand_EP_")


def _nonempty(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    return bool(str(value or "").strip())


def extract_typed_payload(patch: dict[str, Any], patch_type: str) -> dict[str, Any]:
    """Pull typed fields from patch (and nested payload) without dropping keys."""
    nested = patch.get("payload") if isinstance(patch.get("payload"), dict) else {}
    fields = TYPED_PAYLOAD_FIELDS.get(patch_type) or ()
    out: dict[str, Any] = {}
    for key in fields:
        if key in patch and patch[key] is not None:
            out[key] = patch[key]
        elif key in nested and nested[key] is not None:
            out[key] = nested[key]
    # Preserve free-form evidence / relation defaults.
    if "relation" in fields and "relation" not in out:
        rel = patch.get("relation") or nested.get("relation")
        if rel:
            out["relation"] = rel
    return out


def validate_typed_patch(patch: dict[str, Any], *, patch_type: str) -> dict[str, Any]:
    """Validate typed payload schema. Returns {ok, error?, code?, payload?}."""
    ptype = str(patch_type or patch.get("patch_type") or "").strip()
    if ptype and ptype not in TYPED_PATCH_TYPES:
        return {
            "ok": False,
            "error": SEMANTIC_PATCH_INVALID,
            "code": SEMANTIC_PATCH_INVALID,
            "detail": f"unknown patch_type {ptype!r}",
        }
    if ptype in {"", "mark_missing", "edge_resolution"}:
        # Legacy / mark_missing handled by llm_tasks validators.
        return {"ok": True, "payload": extract_typed_payload(patch, ptype or "edge_resolution")}

    payload = extract_typed_payload(patch, ptype)
    required = TYPED_PAYLOAD_FIELDS.get(ptype) or ()

    if ptype == "entrypoint_node_resolution":
        node_id = payload.get("node_id") or patch.get("edge_id")
        cand = payload.get("candidate_id")
        if not _nonempty(node_id) and not _nonempty(cand):
            return {
                "ok": False,
                "error": SEMANTIC_PATCH_INVALID,
                "code": SEMANTIC_PATCH_INVALID,
                "detail": "entrypoint_node_resolution requires node_id or candidate_id",
            }
        if node_id:
            payload["node_id"] = str(node_id)
        if cand:
            payload["candidate_id"] = str(cand)
        # Candidate ids may identify nodes; never treat them as edge ids downstream.
        return {"ok": True, "payload": payload}

    if ptype == "entrypoint_dispatch_resolution":
        src = payload.get("source_node_id")
        tgt = payload.get("target_node_id")
        if not _nonempty(src) or not _nonempty(tgt):
            return {
                "ok": False,
                "error": SEMANTIC_PATCH_INVALID,
                "code": SEMANTIC_PATCH_INVALID,
                "detail": "entrypoint_dispatch_resolution requires source_node_id and target_node_id",
            }
        if _is_candidate_node_id(src) or _is_candidate_node_id(tgt):
            # Allowed only as references to candidate window identities that map to graph nodes.
            pass
        payload["source_node_id"] = str(src)
        payload["target_node_id"] = str(tgt)
        payload.setdefault("relation", "dispatches_to")
        return {"ok": True, "payload": payload}

    if ptype == "call_edge_resolution":
        caller = payload.get("caller_function_id")
        callee = payload.get("callee_function_id")
        callsite = payload.get("callsite") if isinstance(payload.get("callsite"), dict) else {}
        if not _nonempty(caller) or not _nonempty(callee):
            return {
                "ok": False,
                "error": SEMANTIC_PATCH_INVALID,
                "code": SEMANTIC_PATCH_INVALID,
                "detail": "call_edge_resolution requires caller_function_id and callee_function_id",
            }
        if not _nonempty(callsite.get("file_path")) or not callsite.get("line"):
            return {
                "ok": False,
                "error": SEMANTIC_PATCH_INVALID,
                "code": SEMANTIC_PATCH_INVALID,
                "detail": "call_edge_resolution requires callsite.file_path and callsite.line",
            }
        payload["caller_function_id"] = str(caller)
        payload["callee_function_id"] = str(callee)
        payload["callsite"] = {
            "file_path": str(callsite.get("file_path")),
            "line": int(callsite.get("line") or 0),
            **({k: v for k, v in callsite.items() if k not in {"file_path", "line"}}),
        }
        return {"ok": True, "payload": payload}

    if ptype == "tilingdata_bridge_resolution":
        host = payload.get("host_field_id")
        kern = payload.get("kernel_field_id")
        if not _nonempty(host) or not _nonempty(kern):
            return {
                "ok": False,
                "error": SEMANTIC_PATCH_INVALID,
                "code": SEMANTIC_PATCH_INVALID,
                "detail": "tilingdata_bridge_resolution requires host_field_id and kernel_field_id",
            }
        if not (
            _nonempty(payload.get("owning_type"))
            and _nonempty(payload.get("field_path"))
            and _nonempty(payload.get("unit_id"))
        ):
            return {
                "ok": False,
                "error": SEMANTIC_PATCH_INVALID,
                "code": SEMANTIC_PATCH_INVALID,
                "detail": "tilingdata_bridge_resolution requires owning_type, field_path, unit_id",
            }
        payload["host_field_id"] = str(host)
        payload["kernel_field_id"] = str(kern)
        payload.setdefault("relation", "maps_tilingdata")
        return {"ok": True, "payload": payload}

    if ptype == "template_instance_resolution":
        for key in ("tilingkey_value_id", "template_instance_id", "kernel_entry_id"):
            if not _nonempty(payload.get(key)):
                return {
                    "ok": False,
                    "error": SEMANTIC_PATCH_INVALID,
                    "code": SEMANTIC_PATCH_INVALID,
                    "detail": f"template_instance_resolution requires {key}",
                }
            payload[key] = str(payload[key])
        return {"ok": True, "payload": payload}

    # Fallback: ensure required keys present when declared.
    missing = [k for k in required if not _nonempty(payload.get(k))]
    if missing:
        return {
            "ok": False,
            "error": SEMANTIC_PATCH_INVALID,
            "code": SEMANTIC_PATCH_INVALID,
            "detail": f"missing fields: {missing}",
        }
    return {"ok": True, "payload": payload}


def _upgrade_confidence(obj: dict[str, Any], patch: dict[str, Any]) -> None:
    obj["confidence"] = SEMANTIC_VERIFIED
    obj["verification_source"] = "llm"
    obj["ledger_task_id"] = patch.get("task_id")
    if patch.get("patch_type"):
        obj["ledger_patch_type"] = patch.get("patch_type")


def _ensure_edge(
    edges: list[dict[str, Any]],
    *,
    edge_type: str,
    source: str,
    target: str,
    patch: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    eid = mint_edge_id(edge_type, source, target)
    by_id = {str(e.get("id")): e for e in edges if isinstance(e, dict) and e.get("id")}
    if eid in by_id:
        edge = by_id[eid]
        _upgrade_confidence(edge, patch)
        if evidence:
            existing = list(edge.get("evidence") or [])
            edge["evidence"] = existing + evidence
        if extra:
            edge.update(extra)
        return edge
    edge = {
        "id": eid,
        "type": edge_type,
        "source": source,
        "target": target,
        "evidence": evidence or [],
        "confidence": SEMANTIC_VERIFIED,
        "verification_source": "llm",
        "ledger_task_id": patch.get("task_id"),
        "ledger_patch_type": patch.get("patch_type"),
        "target_status": "resolved",
    }
    if extra:
        edge.update(extra)
    edges.append(edge)
    return edge


def _node_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(n.get("id")): n
        for n in (graph.get("nodes") or [])
        if isinstance(n, dict) and n.get("id")
    }


def _edge_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(e.get("id")): e
        for e in (graph.get("edges") or [])
        if isinstance(e, dict) and e.get("id")
    }


def materialize_entrypoint_node_resolution(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    graph = layers.get("entrypoint_graph") or layers.get("operator_graph") or {}
    nodes = _node_index(graph)
    payload = extract_typed_payload(patch, "entrypoint_node_resolution")
    node_id = str(payload.get("node_id") or "")
    cand = str(payload.get("candidate_id") or "")
    target = None
    if node_id and node_id in nodes:
        target = nodes[node_id]
    elif cand and cand in nodes:
        target = nodes[cand]
    elif cand:
        # Resolve candidate window id → node by symbol match in accepted ids.
        for nid, node in nodes.items():
            if nid == cand or str(node.get("candidate_id") or "") == cand:
                target = node
                break
    if target is None:
        return {
            "ok": False,
            "apply_status": "target_missing",
            "error": SEMANTIC_TARGET_NOT_FOUND,
            "detail": f"node not found: node_id={node_id!r} candidate_id={cand!r}",
        }
    target["status"] = "verified"
    _upgrade_confidence(target, patch)
    return {"ok": True, "apply_status": "materialized", "node_id": target.get("id")}


def materialize_entrypoint_dispatch_resolution(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    graph = layers.get("entrypoint_graph") or layers.get("operator_graph") or {}
    nodes = _node_index(graph)
    edges = list(graph.get("edges") or [])
    payload = extract_typed_payload(patch, "entrypoint_dispatch_resolution")
    src = str(payload.get("source_node_id") or "")
    tgt = str(payload.get("target_node_id") or "")
    relation = str(payload.get("relation") or "dispatches_to")
    if src not in nodes:
        return {
            "ok": False,
            "apply_status": "target_missing",
            "error": SEMANTIC_TARGET_NOT_FOUND,
            "detail": f"source_node_id not found: {src}",
        }
    if tgt not in nodes:
        return {
            "ok": False,
            "apply_status": "target_missing",
            "error": SEMANTIC_TARGET_NOT_FOUND,
            "detail": f"target_node_id not found: {tgt}",
        }
    evidence = []
    for item in patch.get("evidence") or []:
        if isinstance(item, dict):
            evidence.append(item)
        else:
            evidence.append({"reason": str(item)})
    edge = _ensure_edge(
        edges,
        edge_type=relation,
        source=src,
        target=tgt,
        patch=patch,
        evidence=evidence or [{"reason": "ledger_entrypoint_dispatch"}],
    )
    graph["edges"] = edges
    layers["entrypoint_graph"] = graph
    return {"ok": True, "apply_status": "materialized", "edge_id": edge.get("id")}


def materialize_call_edge_resolution(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    # Prefer host/kernel function graphs; fall back to operator/entrypoint.
    graph = (
        layers.get("host_subgraph")
        or layers.get("kernel_subgraph")
        or layers.get("operator_graph")
        or layers.get("entrypoint_graph")
        or {}
    )
    # Also try to find nodes across merged operator graph.
    op = layers.get("operator_graph") or {}
    nodes = {**_node_index(graph), **_node_index(op), **_node_index(layers.get("entrypoint_graph") or {})}
    target_graph = layers.get("operator_graph") or layers.get("entrypoint_graph") or graph
    edges = list(target_graph.get("edges") or [])
    payload = extract_typed_payload(patch, "call_edge_resolution")
    caller = str(payload.get("caller_function_id") or "")
    callee = str(payload.get("callee_function_id") or "")
    callsite = payload.get("callsite") if isinstance(payload.get("callsite"), dict) else {}
    if caller not in nodes:
        return {
            "ok": False,
            "apply_status": "target_missing",
            "error": SEMANTIC_TARGET_NOT_FOUND,
            "detail": f"caller_function_id not found: {caller}",
        }
    if callee not in nodes:
        return {
            "ok": False,
            "apply_status": "target_missing",
            "error": SEMANTIC_TARGET_NOT_FOUND,
            "detail": f"callee_function_id not found: {callee}",
        }
    edge = _ensure_edge(
        edges,
        edge_type="calls",
        source=caller,
        target=callee,
        patch=patch,
        evidence=[
            {
                "file_path": callsite.get("file_path"),
                "line": callsite.get("line"),
                "reason": "ledger_call_edge",
            }
        ],
        extra={"callsite": callsite},
    )
    target_graph["edges"] = edges
    if "operator_graph" in layers or target_graph is layers.get("operator_graph"):
        layers["operator_graph"] = target_graph
    elif "entrypoint_graph" in layers:
        layers["entrypoint_graph"] = target_graph
    return {"ok": True, "apply_status": "materialized", "edge_id": edge.get("id")}


def materialize_tilingdata_bridge_resolution(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    payload = extract_typed_payload(patch, "tilingdata_bridge_resolution")
    host_id = str(payload.get("host_field_id") or "")
    kern_id = str(payload.get("kernel_field_id") or "")
    relation = str(payload.get("relation") or "maps_tilingdata")

    op = layers.setdefault("operator_graph", {"nodes": [], "edges": []})
    bridge = layers.setdefault("bridge", {"tilingdata_bridges": [], "bridge_edges": []})
    nodes = _node_index(op)
    # Ensure HostField / KernelField nodes exist when referenced as stable identities.
    for nid, role in ((host_id, "HostField"), (kern_id, "KernelField")):
        if nid and nid not in nodes:
            # Fail closed: do not invent nodes from short names without identity.
            if _is_candidate_node_id(nid) or "/" not in nid and not nid.startswith(("HF_", "KF_", "EP_", "NODE_")):
                # Still allow stable semantic ids that already look minted.
                if not (nid.startswith(("HF_", "KF_", "HOST_", "KERN_", "TD_", "EP_"))):
                    return {
                        "ok": False,
                        "apply_status": "target_missing",
                        "error": SEMANTIC_TARGET_NOT_FOUND,
                        "detail": f"field identity not found and cannot invent: {nid}",
                    }
            node = {
                "id": nid,
                "role": role,
                "kind": role,
                "confidence": SEMANTIC_VERIFIED,
                "verification_source": "llm",
                "ledger_task_id": patch.get("task_id"),
                "owning_type": payload.get("owning_type"),
                "field_path": payload.get("field_path"),
                "unit_id": payload.get("unit_id"),
            }
            op.setdefault("nodes", []).append(node)
            nodes[nid] = node
        elif nid in nodes:
            _upgrade_confidence(nodes[nid], patch)

    edges = list(op.get("edges") or [])
    edge = _ensure_edge(
        edges,
        edge_type=relation,
        source=host_id,
        target=kern_id,
        patch=patch,
        evidence=[
            {
                "reason": "ledger_tilingdata_bridge",
                "owning_type": payload.get("owning_type"),
                "field_path": payload.get("field_path"),
                "unit_id": payload.get("unit_id"),
            }
        ],
        extra={
            "owning_type": payload.get("owning_type"),
            "field_path": payload.get("field_path"),
            "unit_id": payload.get("unit_id"),
            "host_field_id": host_id,
            "kernel_field_id": kern_id,
        },
    )
    op["edges"] = edges
    layers["operator_graph"] = op

    # Mirror into bridge IR.
    bridge_edges = list(bridge.get("bridge_edges") or [])
    if not any(str(e.get("id")) == edge["id"] for e in bridge_edges if isinstance(e, dict)):
        bridge_edges.append(dict(edge))
    bridge["bridge_edges"] = bridge_edges
    bridges = list(bridge.get("tilingdata_bridges") or [])
    if not any(
        str(b.get("host_field_id")) == host_id and str(b.get("kernel_field_id")) == kern_id
        for b in bridges
        if isinstance(b, dict)
    ):
        bridges.append(
            {
                "host_field_id": host_id,
                "kernel_field_id": kern_id,
                "owning_type": payload.get("owning_type"),
                "field_path": payload.get("field_path"),
                "unit_id": payload.get("unit_id"),
                "relation": relation,
                "confidence": SEMANTIC_VERIFIED,
                "verification_source": "llm",
                "ledger_task_id": patch.get("task_id"),
            }
        )
    bridge["tilingdata_bridges"] = bridges
    layers["bridge"] = bridge
    return {"ok": True, "apply_status": "materialized", "edge_id": edge.get("id")}


def materialize_template_instance_resolution(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    payload = extract_typed_payload(patch, "template_instance_resolution")
    tk = str(payload.get("tilingkey_value_id") or "")
    tpl = str(payload.get("template_instance_id") or "")
    kern = str(payload.get("kernel_entry_id") or "")

    op = layers.setdefault("operator_graph", {"nodes": [], "edges": []})
    ep = layers.setdefault("entrypoint_graph", {"nodes": [], "edges": []})
    nodes = {**_node_index(ep), **_node_index(op)}

    missing = [x for x in (tk, tpl, kern) if x not in nodes]
    if missing:
        # Allow confirming edges only when all identities already exist.
        return {
            "ok": False,
            "apply_status": "target_missing",
            "error": SEMANTIC_TARGET_NOT_FOUND,
            "detail": f"template identities not found: {missing}",
        }

    # Materialize onto both entrypoint and operator graphs.
    created: list[str] = []
    for graph in (ep, op):
        edges = list(graph.get("edges") or [])
        e1 = _ensure_edge(
            edges,
            edge_type="selects",
            source=tk,
            target=tpl,
            patch=patch,
            evidence=[{"reason": "ledger_template_selects"}],
        )
        e2 = _ensure_edge(
            edges,
            edge_type="implements",
            source=tpl,
            target=kern,
            patch=patch,
            evidence=[{"reason": "ledger_template_implements"}],
        )
        graph["edges"] = edges
        created.extend([str(e1.get("id")), str(e2.get("id"))])
    layers["entrypoint_graph"] = ep
    layers["operator_graph"] = op
    return {"ok": True, "apply_status": "materialized", "edge_ids": created}


def materialize_edge_resolution(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Legacy: upgrade an existing edge by edge_id."""
    edge_id = str(patch.get("edge_id") or "")
    if _is_candidate_node_id(edge_id):
        return {
            "ok": False,
            "apply_status": "invalid",
            "error": LEDGER_TARGET_TYPE_MISMATCH,
            "detail": f"candidate node id used as edge_id: {edge_id}",
        }
    if not edge_id:
        accepted = [str(x) for x in (patch.get("accepted_candidate_ids") or [])]
        for cid in accepted:
            if not _is_candidate_node_id(cid):
                edge_id = cid
                break
    if not edge_id:
        return {
            "ok": False,
            "apply_status": "unconsumed",
            "error": SEMANTIC_PATCH_UNCONSUMED,
            "detail": "no edge_id for edge_resolution",
        }

    for key in ("entrypoint_graph", "operator_graph", "host_subgraph", "kernel_subgraph", "bridge"):
        graph = layers.get(key)
        if not isinstance(graph, dict):
            continue
        edges = _edge_index(graph)
        if edge_id in edges:
            _upgrade_confidence(edges[edge_id], patch)
            return {"ok": True, "apply_status": "materialized", "edge_id": edge_id, "layer": key}
    return {
        "ok": False,
        "apply_status": "unconsumed",
        "error": SEMANTIC_PATCH_UNCONSUMED,
        "detail": f"edge_id not found in any layer: {edge_id}",
    }


MATERIALIZERS: dict[str, Callable[[dict[str, dict[str, Any]], dict[str, Any]], dict[str, Any]]] = {
    "entrypoint_node_resolution": materialize_entrypoint_node_resolution,
    "entrypoint_dispatch_resolution": materialize_entrypoint_dispatch_resolution,
    "call_edge_resolution": materialize_call_edge_resolution,
    "tilingdata_bridge_resolution": materialize_tilingdata_bridge_resolution,
    "template_instance_resolution": materialize_template_instance_resolution,
    "edge_resolution": materialize_edge_resolution,
}


def apply_patch_to_layers(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Route one active ledger patch to its typed materializer."""
    if not isinstance(patch, dict):
        return {"ok": False, "apply_status": "invalid", "error": SEMANTIC_PATCH_INVALID}
    if patch.get("status") == "stale":
        return {"ok": True, "apply_status": "stale"}
    action = str(patch.get("action") or "")
    if action == "mark_missing":
        # mark_missing never materializes; stays adjudicated/blocking.
        return {"ok": True, "apply_status": "adjudicated_only", "error": None}
    ptype = str(patch.get("patch_type") or "edge_resolution")
    if ptype == "mark_missing":
        return {"ok": True, "apply_status": "adjudicated_only"}
    fn = MATERIALIZERS.get(ptype) or materialize_edge_resolution
    try:
        result = fn(layers, patch)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "apply_status": "invalid",
            "error": SEMANTIC_PATCH_INVALID,
            "detail": str(exc)[:300],
        }
    return result


def verify_patch_against_layers(
    layers: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Final verification after all layers have been patched."""
    if not isinstance(patch, dict):
        return {"apply_status": "invalid", "error": SEMANTIC_PATCH_INVALID}
    if patch.get("status") == "stale":
        return {"apply_status": "stale"}
    action = str(patch.get("action") or "")
    if action == "mark_missing" or str(patch.get("patch_type") or "") == "mark_missing":
        return {"apply_status": "adjudicated_only"}

    ptype = str(patch.get("patch_type") or "edge_resolution")
    payload = extract_typed_payload(patch, ptype)

    def _edges() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for g in layers.values():
            if isinstance(g, dict):
                out.extend([e for e in (g.get("edges") or []) if isinstance(e, dict)])
        return out

    def _nodes() -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for g in layers.values():
            if isinstance(g, dict):
                out.update(_node_index(g))
        return out

    edges = _edges()
    nodes = _nodes()

    if ptype == "entrypoint_node_resolution":
        nid = str(payload.get("node_id") or payload.get("candidate_id") or "")
        node = nodes.get(nid)
        if node and is_verified_confidence(node.get("confidence")):
            return {"apply_status": "materialized"}
        return {"apply_status": "unconsumed", "error": SEMANTIC_PATCH_UNCONSUMED}

    if ptype == "entrypoint_dispatch_resolution":
        src = str(payload.get("source_node_id") or "")
        tgt = str(payload.get("target_node_id") or "")
        rel = str(payload.get("relation") or "dispatches_to")
        for e in edges:
            if (
                e.get("type") == rel
                and str(e.get("source")) == src
                and str(e.get("target")) == tgt
                and is_verified_confidence(e.get("confidence"))
            ):
                return {"apply_status": "materialized", "edge_id": e.get("id")}
        return {"apply_status": "unconsumed", "error": SEMANTIC_PATCH_UNCONSUMED}

    if ptype == "call_edge_resolution":
        caller = str(payload.get("caller_function_id") or "")
        callee = str(payload.get("callee_function_id") or "")
        for e in edges:
            if (
                e.get("type") == "calls"
                and str(e.get("source")) == caller
                and str(e.get("target")) == callee
                and is_verified_confidence(e.get("confidence"))
            ):
                return {"apply_status": "materialized", "edge_id": e.get("id")}
        return {"apply_status": "unconsumed", "error": SEMANTIC_PATCH_UNCONSUMED}

    if ptype == "tilingdata_bridge_resolution":
        host = str(payload.get("host_field_id") or "")
        kern = str(payload.get("kernel_field_id") or "")
        for e in edges:
            if (
                e.get("type") in {"maps_tilingdata", payload.get("relation")}
                and str(e.get("source")) == host
                and str(e.get("target")) == kern
                and is_verified_confidence(e.get("confidence"))
            ):
                return {"apply_status": "materialized", "edge_id": e.get("id")}
        return {"apply_status": "unconsumed", "error": SEMANTIC_PATCH_UNCONSUMED}

    if ptype == "template_instance_resolution":
        tk = str(payload.get("tilingkey_value_id") or "")
        tpl = str(payload.get("template_instance_id") or "")
        kern = str(payload.get("kernel_entry_id") or "")
        has_select = any(
            e.get("type") == "selects"
            and str(e.get("source")) == tk
            and str(e.get("target")) == tpl
            and is_verified_confidence(e.get("confidence"))
            for e in edges
        )
        has_impl = any(
            e.get("type") == "implements"
            and str(e.get("source")) == tpl
            and str(e.get("target")) == kern
            and is_verified_confidence(e.get("confidence"))
            for e in edges
        )
        if has_select and has_impl:
            return {"apply_status": "materialized"}
        return {"apply_status": "unconsumed", "error": SEMANTIC_PATCH_UNCONSUMED}

    # Legacy edge_resolution
    edge_id = str(patch.get("edge_id") or "")
    if _is_candidate_node_id(edge_id):
        return {"apply_status": "invalid", "error": LEDGER_TARGET_TYPE_MISMATCH}
    by_id = {str(e.get("id")): e for e in edges if e.get("id")}
    edge = by_id.get(edge_id)
    if edge and is_verified_confidence(edge.get("confidence")):
        return {"apply_status": "materialized", "edge_id": edge_id}
    if not edge_id:
        return {"apply_status": "unconsumed", "error": SEMANTIC_PATCH_UNCONSUMED}
    if edge_id not in by_id:
        return {"apply_status": "target_missing", "error": SEMANTIC_TARGET_NOT_FOUND}
    return {"apply_status": "unconsumed", "error": SEMANTIC_PATCH_UNCONSUMED}
