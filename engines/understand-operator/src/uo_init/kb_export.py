# -*- coding: utf-8 -*-
"""Export the new UO graph as authoritative, reviewable YAML layers.

The SQLite database is deliberately absent from this module.  YAML is the
single source of truth; :mod:`uo_init.kb_index` derives the disposable query
index from ``ir/operator_graph.yaml``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import yaml

from uo_init.kb_model import Blocker, Domain, Edge, Evidence, KnowledgeBase, Node

FORMAT_VERSION = 1


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _view(
    *,
    status: str = "extracted",
    nodes: Iterable[dict[str, Any]] = (),
    edges: Iterable[dict[str, Any]] = (),
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": FORMAT_VERSION,
        "status": status,
        "nodes": list(nodes),
        "edges": list(edges),
    }
    out.update(extra)
    return out


def graph_payload(kb: KnowledgeBase) -> dict[str, Any]:
    """Return the complete canonical graph in stable order."""
    return {
        "version": FORMAT_VERSION,
        "status": "extracted",
        "op_name": kb.op_name,
        "architecture": kb.architecture,
        "fingerprint": kb.fingerprint(),
        "nodes": [node.to_dict() for node in kb.iter_nodes()],
        "edges": [edge.to_dict() for edge in kb.iter_edges()],
        "evidence": [
            kb.evidence[key].to_dict() for key in sorted(kb.evidence)
        ],
        "domains": {
            key: kb.domains[key].to_dict() for key in sorted(kb.domains)
        },
        "blockers": [
            kb.blockers[key].to_dict() for key in sorted(kb.blockers)
        ],
        "notes": dict(sorted(kb.notes.items())),
    }


def _select_nodes(payload: dict[str, Any], *kinds: str) -> list[dict[str, Any]]:
    wanted = set(kinds)
    return [row for row in payload["nodes"] if row.get("kind") in wanted]


def _select_edges(payload: dict[str, Any], *kinds: str) -> list[dict[str, Any]]:
    wanted = set(kinds)
    return [row for row in payload["edges"] if row.get("kind") in wanted]


def _quality(kb: KnowledgeBase, payload: dict[str, Any]) -> dict[str, Any]:
    metrics = kb.notes.get("quality")
    if not isinstance(metrics, dict):
        metrics = {}
    extracted = sum(1 for row in payload["nodes"] if row.get("status") == "extracted")
    unresolved = sum(1 for row in payload["nodes"] if row.get("status") == "unresolved")
    return {
        "version": FORMAT_VERSION,
        "status": "extracted" if not kb.blockers else "partial",
        "graph_fingerprint": payload["fingerprint"],
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["edges"]),
        "evidence_count": len(payload["evidence"]),
        "extracted_node_count": extracted,
        "unresolved_node_count": unresolved,
        "blocker_count": len(kb.blockers),
        "source_closure": float(metrics.get("source_closure", 0.0)),
        "input_controllability": float(
            metrics.get("input_controllability", 0.0)
        ),
        "predicate_normalization": float(
            metrics.get("predicate_normalization", 0.0)
        ),
        "details": metrics,
    }


def export_kb(kb: KnowledgeBase, uo_root: str | Path) -> dict[str, Any]:
    """Write every new-contract YAML artifact and return an export receipt.

    Existing old-format files are neither read nor translated.  Re-running
    with the same graph produces the same YAML bytes and artifact hashes.
    """
    root = Path(uo_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    payload = graph_payload(kb)

    interface = _select_nodes(
        payload, "Input", "OptionalInput", "Output", "Attribute"
    )
    variables = _select_nodes(payload, "Variable")
    keys = _select_nodes(payload, "TilingKeyDim")
    families = _select_nodes(payload, "Family")
    host_branches = _select_nodes(payload, "HostBranch")
    kernel_branches = _select_nodes(payload, "KernelBranch")
    predicates = _select_nodes(payload, "Predicate")
    bindings = _select_nodes(payload, "TemplateBinding")
    paths = _select_nodes(payload, "KernelPath")
    data_fields = _select_nodes(payload, "TilingDataField")

    mat = kb.notes.get("tiling_materialize") if isinstance(kb.notes.get("tiling_materialize"), dict) else {}
    mat_ok = bool(mat.get("ok"))
    dimensions = list(mat.get("dimensions") or [])
    template_blocks = list(mat.get("template_blocks") or [])
    legal_keys = list(mat.get("legal_keys") or [])
    key_field_obligations = dict(mat.get("key_field_obligations") or {})
    input_realization = dict(mat.get("input_realization") or {})
    relations = list(mat.get("relations") or [])
    field_order = list(mat.get("field_order") or [d.get("name") for d in dimensions])
    summary = dict(mat.get("summary") or {})

    # TG-facing branch list (new contract): input_controllable predicates + KBR.
    branch_rows: list[dict[str, Any]] = []
    for row in kernel_branches:
        branch_rows.append(
            {
                "id": row.get("id"),
                "name": row.get("name") or row.get("id"),
                "condition": (row.get("condition") or (row.get("data") or {}).get("condition") or ""),
                "side": "kernel",
                "runtime": True,
                "input_controllable": True,
                "variants": [True, False],
            }
        )
    controllable_preds = [
        row
        for row in predicates
        if row.get("input_controllable") is True
        or (row.get("data") or {}).get("input_controllable") is True
    ]
    # Prefer flattened fields from to_dict().
    for row in predicates:
        ic = row.get("input_controllable")
        if ic is None:
            continue
        if not ic:
            continue
        bid = str(row.get("branch_id") or row.get("id"))
        if any(b.get("id") == bid for b in branch_rows):
            continue
        branch_rows.append(
            {
                "id": bid,
                "name": bid,
                "condition": "",
                "side": row.get("side") or "host",
                "runtime": True,
                "input_controllable": True,
                "predicate_id": row.get("id"),
                "target_value": row.get("target_value"),
                "variants": [True, False],
            }
        )

    key_space_status = "extracted" if dimensions else "not_extracted"
    exhaustive_status = "extracted" if template_blocks else "not_extracted"
    coverage_status = "extracted" if key_field_obligations else "not_extracted"
    variables_status = "extracted" if (variables or dimensions) else "not_extracted"

    artifacts: dict[str, Any] = {
        "operator.yaml": {
            "version": FORMAT_VERSION,
            "status": "extracted",
            "op_name": kb.op_name,
            "architecture": kb.architecture,
            "interface": interface,
        },
        "quality.yaml": _quality(kb, payload),
        "ir/operator_graph.yaml": payload,
        "ir/unresolved.yaml": {
            "version": FORMAT_VERSION,
            "status": "unresolved" if kb.blockers else "closed",
            "blocker_count": len(kb.blockers),
            "blockers": payload["blockers"],
        },
        "ir/host_ir.yaml": _view(nodes=host_branches),
        "ir/input_derivable.yaml": {
            "version": FORMAT_VERSION,
            "status": variables_status,
            "nodes": variables,
            "edges": _select_edges(payload, "derives_from", "controls"),
            "keys": {
                str(d.get("name")): {
                    "id": d.get("id"),
                    # Per-dimension, from the derivation. Reading the realization
                    # *mode* instead marked all 19 dimensions derivable whenever
                    # any binding existed, including the ones that close onto
                    # host state a generator cannot set.
                    "input_derivable": bool(d.get("input_derivable")),
                    "input_closure": d.get("input_closure") or "",
                    "completeness": d.get("completeness") or "closed",
                }
                for d in dimensions
            },
        },
        "tiling/variables.yaml": {
            "version": FORMAT_VERSION,
            "status": variables_status,
            "nodes": variables,
            "domains": payload["domains"],
            "variables": {
                vid: {
                    "id": vid,
                    **(payload["domains"].get(vid) or {}),
                }
                for vid in sorted(payload["domains"])
            },
        },
        "tiling/key_space.yaml": {
            "version": FORMAT_VERSION,
            "status": key_space_status,
            "nodes": keys,
            "fields": {str(d["name"]): d for d in dimensions if d.get("name")},
            "dimensions": dimensions,
            "field_order": field_order,
        },
        "tiling/exhaustive_key_space.yaml": {
            "version": FORMAT_VERSION,
            "status": exhaustive_status,
            "op_name": kb.op_name,
            "enumeration_source": "args_sel_cartesian",
            "nodes": keys,
            "field_order": field_order,
            "dimensions": dimensions,
            "template_blocks": template_blocks,
            "args_sel_count": int(mat.get("args_sel_count") or len(template_blocks)),
            "legal_key_count": len(legal_keys),
            "legal_key_index": "tiling/legal_key_index.jsonl",
            "summary": summary
            or {
                "template_block_count": len(template_blocks),
                "expanded_key_count": sum(int(b.get("product_count") or 0) for b in template_blocks),
                "ktpl_instance_count": len(template_blocks),
                "key_dimension_count": len(dimensions),
            },
        },
        "tiling/constraints.yaml": {
            "version": FORMAT_VERSION,
            "status": "extracted" if predicates else "not_extracted",
            "nodes": predicates,
            "relations": relations,
            "input_realization": input_realization,
            "input_realization_mode": mat.get("input_realization_mode") or (
                "tpl_identity" if input_realization else ""
            ),
            "tiling_key_pruning": {},
            "tiling_key_merging": {},
        },
        "tiling/families.yaml": _view(
            status="extracted" if families else "partial",
            nodes=families
            or [
                {
                    "id": "FAM_DEFAULT",
                    "kind": "Family",
                    "name": "default",
                    "status": "extracted",
                }
            ],
        ),
        "tiling/coverage_model.yaml": {
            "version": FORMAT_VERSION,
            "status": coverage_status,
            "op_name": kb.op_name,
            "coverage_policy": "clang_layered_kb",
            "key_fields": field_order,
            "family_obligations": list(mat.get("family_obligations") or [{"id": "COV_FAM_DEFAULT", "family_id": "FAM_DEFAULT"}]),
            "key_field_obligations": key_field_obligations,
            "key_relation_obligations": [],
            "quality": _quality(kb, payload),
        },
        "tiling/key_reachability.yaml": {
            "version": FORMAT_VERSION,
            "status": "extracted" if legal_keys else "not_extracted",
            "legal_key_count": len(legal_keys),
            "status_counts": dict(mat.get("key_status_counts") or {}),
            # Which dimensions the solver could actually use, and which
            # variables it had to isolate. Without this the counts below cannot
            # be read: `unknown` means something different when 10 of 19
            # dimensions never entered the conjunction.
            "solver": dict(mat.get("reachability") or {}),
            "keys": legal_keys,
        },
        "tiling/data_model.yaml": _view(
            status="extracted" if data_fields else "not_extracted",
            nodes=data_fields,
        ),
        "kernel/branches.yaml": {
            "version": FORMAT_VERSION,
            "status": "extracted" if (kernel_branches or controllable_preds) else "not_extracted",
            "nodes": kernel_branches,
            "branches": branch_rows,
            "predicates": [
                row for row in predicates if row.get("side") == "kernel"
            ],
        },
        "kernel/paths.yaml": _view(nodes=paths),
        "kernel/compile_model.yaml": _view(
            status="extracted" if bindings else "not_extracted",
            nodes=bindings,
        ),
        "kernel/variables.yaml": _view(
            nodes=variables, domains=payload["domains"]
        ),
        "kernel/pipeline.yaml": _view(status="not_extracted"),
        "kernel/resources.yaml": _view(status="not_extracted"),
        "cross_layer/tiling_to_kernel.yaml": {
            "version": FORMAT_VERSION,
            "status": "extracted" if (mat.get("bind_edges") or bindings) else "not_extracted",
            "edges": _select_edges(payload, "encodes", "binds", "selects", "implements"),
            "binds": list(mat.get("bind_edges") or []),
            "template_blocks": template_blocks,
        },
        "cross_layer/impact_graph.yaml": _view(edges=payload["edges"]),
        "cross_layer/variable_lineage.yaml": _view(
            status="extracted" if variables else "not_extracted",
            edges=_select_edges(payload, "derives_from", "controls", "reads", "writes"),
        ),
        "flow/golden_model.yaml": _view(status="not_extracted"),
        "flow/numerical_model.yaml": _view(status="not_extracted"),
    }
    manifest = {
        "version": FORMAT_VERSION,
        "status": "extracted",
        "authority": "yaml",
        "derived_index": "indexes/kb_graph.sqlite",
        "op_name": kb.op_name,
        "architecture": kb.architecture,
        "graph_fingerprint": payload["fingerprint"],
        "schema": "kb_schema-v1",
        "legal_key_count": len(legal_keys),
        "template_block_count": len(template_blocks),
    }
    artifacts["manifest.yaml"] = manifest

    for rel_path, content in sorted(artifacts.items()):
        _dump(root / rel_path, content)

    if legal_keys:
        from uo_init.materialize_tiling import write_legal_key_index

        write_legal_key_index(root, legal_keys)

    hashes = {
        rel_path: {
            "sha256": _sha256(root / rel_path),
            "status": "extracted",
        }
        for rel_path in sorted(artifacts)
    }
    if (root / "tiling" / "legal_key_index.jsonl").is_file():
        hashes["tiling/legal_key_index.jsonl"] = {
            "sha256": _sha256(root / "tiling" / "legal_key_index.jsonl"),
            "status": "extracted",
        }
    # Flat `hashes` map is what TG validate_intake / understand intake consume.
    hash_payload = {
        "version": FORMAT_VERSION,
        "status": "extracted",
        "artifacts": hashes,
        "hashes": {rel: meta["sha256"] for rel, meta in hashes.items()},
    }
    _dump(root / "checks" / "artifact_hashes.yaml", hash_payload)
    return {
        "ok": True,
        "uo_root": root.as_posix(),
        "graph_fingerprint": payload["fingerprint"],
        "artifact_count": len(artifacts) + 1,
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["edges"]),
        "blocker_count": len(kb.blockers),
        "legal_key_count": len(legal_keys),
        "template_block_count": len(template_blocks),
        "materialize_ok": mat_ok,
    }



def load_graph(uo_root: str | Path) -> dict[str, Any]:
    """Load the sole canonical YAML graph used by the index builder."""
    path = Path(uo_root) / "ir" / "operator_graph.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"authoritative graph missing: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict) or payload.get("version") != FORMAT_VERSION:
        raise ValueError(f"unsupported operator graph: {path}")
    for key in ("nodes", "edges", "evidence", "domains"):
        if key not in payload:
            raise ValueError(f"operator graph missing {key}: {path}")
    return payload


def knowledge_base_from_payload(payload: dict[str, Any]) -> KnowledgeBase:
    """Rehydrate a graph between deterministic Pilot actions."""
    kb = KnowledgeBase(
        op_name=str(payload.get("op_name") or ""),
        architecture=str(payload.get("architecture") or ""),
    )
    evidence = {
        str(row["id"]): Evidence(
            id=str(row["id"]),
            file=str(row.get("file") or ""),
            line_start=int(row.get("line_start") or 0),
            line_end=int(row.get("line_end") or row.get("line_start") or 0),
            snippet=str(row.get("snippet") or ""),
            source_hash=str(row.get("source_hash") or ""),
        )
        for row in payload.get("evidence") or []
    }
    node_keys = {
        "id", "kind", "name", "layer", "status", "confidence", "evidence_refs"
    }
    for row in payload.get("nodes") or []:
        kb.add_node(
            Node(
                id=str(row["id"]),
                kind=str(row["kind"]),
                name=str(row.get("name") or ""),
                layer=str(row.get("layer") or ""),
                status=str(row.get("status") or "unresolved"),
                confidence=float(row.get("confidence", 0.0)),
                data={key: value for key, value in row.items() if key not in node_keys},
                evidence=[
                    evidence[ref]
                    for ref in row.get("evidence_refs") or []
                    if ref in evidence
                ],
            )
        )
    edge_keys = {"id", "kind", "src", "dst", "status", "confidence"}
    for row in payload.get("edges") or []:
        kb.add_edge(
            Edge(
                id=str(row["id"]),
                kind=str(row["kind"]),
                src=str(row["src"]),
                dst=str(row["dst"]),
                status=str(row.get("status") or "unresolved"),
                confidence=float(row.get("confidence", 0.0)),
                data={key: value for key, value in row.items() if key not in edge_keys},
            )
        )
    for var_id, row in (payload.get("domains") or {}).items():
        kb.add_domain(
            Domain(
                var_id=str(var_id),
                value_type=str(row.get("type") or "int"),
                lo=row.get("lo"),
                hi=row.get("hi"),
                values=list(row.get("domain") or []),
                completeness=str(row.get("completeness") or "open"),
                source=str(row.get("source") or ""),
            )
        )
    for row in payload.get("blockers") or []:
        kb.add_blocker(
            Blocker(
                id=str(row["id"]),
                text=str(row.get("text") or ""),
                reason_code=str(row.get("reason_code") or "UNKNOWN"),
                affected_nodes=list(row.get("affected_nodes") or []),
                evidence=[
                    evidence[ref]
                    for ref in row.get("evidence_refs") or []
                    if ref in evidence
                ],
                hint=str(row.get("hint") or ""),
            )
        )
    kb.notes.update(payload.get("notes") or {})
    return kb


def load_kb(uo_root: str | Path) -> KnowledgeBase:
    return knowledge_base_from_payload(load_graph(uo_root))
