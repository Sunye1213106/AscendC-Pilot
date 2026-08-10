# -*- coding: utf-8 -*-
"""Assemble the UO knowledge-base product and export it as one binary库.

SQLite (``indexes/kb_graph.sqlite``) is the on-disk authority and the only
product written by default. Layered YAML is an opt-in human/debug export
(``UO_KB_YAML=1``); reconstruct any single view on demand with
:mod:`uo_init.dump` instead of keeping 27MB of duplicated text on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

from uo_init.kb_model import Blocker, Domain, Edge, Evidence, KnowledgeBase, Node

FORMAT_VERSION = 1


def yaml_export_enabled() -> bool:
    """Whether layered YAML files should be written beside the DB product.

    Default off: the DB is the authority, and a second copy on disk is a second
    thing that can disagree with it. ``UO_KB_YAML=1`` opts a run back in for
    hand review; ``uo dump <view>`` is the reviewable path that does not.
    """
    raw = str(os.environ.get("UO_KB_YAML", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


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


def _tilingdata_view(
    kb: KnowledgeBase,
    payload: dict[str, Any],
    data_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """Prefer the structured view built at materialize time; fall back to nodes."""
    cached = kb.notes.get("tiling_data_view")
    if isinstance(cached, dict) and cached.get("structs") is not None:
        out = dict(cached)
        out["graph_fingerprint"] = payload.get("fingerprint") or ""
        out["status"] = "extracted" if out.get("structs") else "not_extracted"
        return out
    # Rebuild a minimal projection from TDF nodes alone.
    by_struct: dict[str, list[dict[str, Any]]] = {}
    for row in data_fields:
        data = row.get("data") or row
        st = str(data.get("struct") or "Unknown")
        by_struct.setdefault(st, []).append(
            {
                "id": row.get("id"),
                "name": row.get("name") or data.get("name"),
                "type": data.get("ctype") or "",
                "default": data.get("default"),
                "writers": list(data.get("writers") or []),
                "readers": list(data.get("readers") or []),
                "closure": {
                    "writer_count": data.get("writer_count") or 0,
                    "reader_count": data.get("reader_count") or 0,
                    "status": "open",
                    "defect": data.get("defect"),
                },
            }
        )
    constants = [
        {
            "name": row.get("name"),
            "value": (row.get("data") or row).get("value"),
            "kind": (row.get("data") or row).get("origin") or "named_constant",
        }
        for row in payload.get("nodes") or []
        if row.get("kind") == "Variable"
        and ((row.get("data") or {}).get("value_type") == "named_constant")
    ]
    return {
        "schema": "uo-view-tilingdata/v1",
        "version": FORMAT_VERSION,
        "status": "extracted" if by_struct else "not_extracted",
        "graph_fingerprint": payload.get("fingerprint") or "",
        "structs": [
            {"name": name, "form": "", "source": {}, "fields": fields}
            for name, fields in sorted(by_struct.items())
        ],
        "constants": constants[:500],
        "defects": dict((kb.notes.get("tiling_data_ir") or {}).get("defects") or {}),
        "notes": list((kb.notes.get("tiling_data_ir") or {}).get("notes") or []),
    }


def _call_graph_view(kb: KnowledgeBase, payload: dict[str, Any]) -> dict[str, Any]:
    cg = kb.notes.get("call_graph") if isinstance(kb.notes.get("call_graph"), dict) else {}
    edges = list(cg.get("edges") or [])
    return {
        "schema": "uo-view-call-graph/v1",
        "version": FORMAT_VERSION,
        "status": "extracted" if edges else "not_extracted",
        "graph_fingerprint": payload.get("fingerprint") or "",
        "count": int(cg.get("count") or len(edges)),
        "setter_count": int(cg.get("setter_count") or 0),
        "getter_count": int(cg.get("getter_count") or 0),
        "edges": edges,
    }


def _kernel_view(
    payload: dict[str, Any], kernel_branches: list[dict[str, Any]]
) -> dict[str, Any]:
    """The kernel domain in the shape a closure ledger reads.

    Rows are the pre-instantiation `if constexpr` branches, because only those
    still name the dimension that decides them — once instantiated the guard has
    folded and nothing is left saying which dimension chose the surviving arm.
    A folded branch minted at the same source location is static witness that
    the branch survives some real instantiation, so it is attached to the row
    rather than listed as a second, unrelated branch.

    `D` is therefore `(branch, dtype_variant)` pairs and reachability is a
    downstream consequence of key reachability, reached through `dimensions`.
    """
    loc: dict[str, tuple[str, int]] = {}
    for row in payload.get("evidence") or []:
        loc[str(row.get("id"))] = (
            str(row.get("file") or ""),
            int(row.get("line_start") or 0),
        )

    def _where(row: dict[str, Any]) -> tuple[str, int]:
        for ref in row.get("evidence_refs") or []:
            hit = loc.get(str(ref))
            if hit:
                return hit
        return ("", 0)

    constexpr = [r for r in kernel_branches if r.get("stage") == "constexpr"]
    folded = [r for r in kernel_branches if r.get("stage") != "constexpr"]
    folded_at: dict[tuple[str, int], list[str]] = {}
    for row in folded:
        folded_at.setdefault(_where(row), []).append(str(row.get("id")))

    constexpr_at = {_where(row) for row in constexpr}
    rows: list[dict[str, Any]] = []
    for row in constexpr:
        file, line = _where(row)
        witness = sorted(folded_at.get((file, line)) or [])
        rows.append(
            {
                "id": row.get("id"),
                "condition": row.get("condition") or "",
                "source": {"file": file, "line": line, "function": row.get("function") or ""},
                "dimensions": list(row.get("dimensions") or []),
                "derived": list(row.get("derived") or []),
                "symbols": list(row.get("symbols") or []),
                "dtype_variants": list(row.get("dtype_variants") or []),
                "closure": {
                    # A folded twin proves the branch compiles in at least one
                    # sampled instance. That is real evidence and it costs no
                    # hardware, but it is not per-key coverage, so it lands in
                    # its own field rather than in `witness_keys`.
                    "status": "witnessed_folded" if witness else "open",
                    "folded_witness": witness,
                    "witness_keys": [],
                    "excluded_by": None,
                },
            }
        )

    ir_notes = payload.get("notes") or {}
    ir_notes = ir_notes.get("kernel_ir") if isinstance(ir_notes.get("kernel_ir"), dict) else {}
    return {
        "schema": "uo-view-kernel/v1",
        "version": FORMAT_VERSION,
        "status": "extracted" if rows else "not_extracted",
        "graph_fingerprint": payload["fingerprint"],
        "dtype_variants": list(ir_notes.get("variants") or []),
        "branches": rows,
        # Folded branches with no `if constexpr` at that location: runtime ifs,
        # or constexpr the uninstantiated parse could not reach. Listed so the
        # two passes disagreeing stays visible instead of being averaged away.
        "folded_only": sorted(
            str(r.get("id")) for r in folded if _where(r) not in constexpr_at
        ),
        "by_dimension": dict(ir_notes.get("by_dimension") or {}),
        "silent_dimensions": list(ir_notes.get("silent_dimensions") or []),
        "unmapped_symbols": list(ir_notes.get("unmapped_symbols") or []),
        "notes": list(ir_notes.get("notes") or []),
    }


def assemble_artifacts(kb: KnowledgeBase) -> dict[str, Any]:
    """Build every layered view in memory (no I/O).

    Returns a dict with ``graph``, ``artifacts``, ``legal_keys``,
    ``host_derivation``, ``materialize_ok``, and count fields used by export.
    """
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
            "solver": dict(mat.get("reachability") or {}),
            "keys": legal_keys,
        },
        "tiling/data_model.yaml": _view(
            status="extracted" if data_fields else "not_extracted",
            nodes=data_fields,
            summary=dict(kb.notes.get("tiling_data_ir") or {}),
        ),
        "views/tilingdata.yaml": _tilingdata_view(kb, payload, data_fields),
        "kernel/branches.yaml": {
            "version": FORMAT_VERSION,
            "status": "extracted" if (kernel_branches or controllable_preds) else "not_extracted",
            "nodes": kernel_branches,
            "branches": branch_rows,
            "predicates": [
                row for row in predicates if row.get("side") == "kernel"
            ],
        },
        "views/kernel.yaml": _kernel_view(payload, kernel_branches),
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
            "status": (
                "extracted"
                if (
                    mat.get("bind_edges")
                    or bindings
                    or data_fields
                    or _select_edges(payload, "writes", "reads")
                )
                else "not_extracted"
            ),
            "edges": _select_edges(
                payload,
                "encodes",
                "binds",
                "selects",
                "implements",
                "writes",
                "reads",
            ),
            "binds": list(mat.get("bind_edges") or []),
            "writes": _select_edges(payload, "writes"),
            "reads": _select_edges(payload, "reads"),
            "template_blocks": template_blocks,
            "tiling_data": dict(kb.notes.get("tiling_data_ir") or {}),
        },
        "views/call_graph.yaml": _call_graph_view(kb, payload),
        # Lazy projections: authority is the edge table / operator_graph.
        # dump_view materializes full edge lists on demand.
        "cross_layer/impact_graph.yaml": {
            "version": FORMAT_VERSION,
            "status": "lazy",
            "schema": "uo-view-impact-lazy/v1",
            "projection": "all_edges",
            "edge_count": len(payload.get("edges") or []),
            "fingerprint": payload.get("fingerprint") or "",
        },
        "cross_layer/variable_lineage.yaml": {
            "version": FORMAT_VERSION,
            "status": "lazy" if variables else "not_extracted",
            "schema": "uo-view-lineage-lazy/v1",
            "projection": "edge_kinds",
            "kinds": ["derives_from", "controls", "reads", "writes"],
            "fingerprint": payload.get("fingerprint") or "",
        },
        "flow/golden_model.yaml": _view(status="not_extracted"),
        "flow/numerical_model.yaml": _view(status="not_extracted"),
    }
    manifest = {
        "version": FORMAT_VERSION,
        "status": "extracted",
        "authority": "db",
        "product": "indexes/kb_graph.sqlite",
        "derived_index": "indexes/kb_graph.sqlite",
        "yaml_export": yaml_export_enabled(),
        "op_name": kb.op_name,
        "architecture": kb.architecture,
        "graph_fingerprint": payload["fingerprint"],
        "schema": "kb_schema-v1",
        "legal_key_count": len(legal_keys),
        "template_block_count": len(template_blocks),
    }
    artifacts["manifest.yaml"] = manifest

    host_derivation = None
    for key in ("host_derivation", "host_derivation_dict"):
        raw = kb.notes.get(key)
        if isinstance(raw, dict) and raw:
            host_derivation = raw
            break
        to_dict = getattr(raw, "to_dict", None)
        if callable(to_dict):
            host_derivation = to_dict()
            break

    return {
        "graph": payload,
        "artifacts": artifacts,
        "legal_keys": legal_keys,
        "host_derivation": host_derivation,
        "materialize_ok": mat_ok,
        "node_count": len(payload["nodes"]),
        "edge_count": len(payload["edges"]),
        "blocker_count": len(kb.blockers),
        "legal_key_count": len(legal_keys),
        "template_block_count": len(template_blocks),
        "graph_fingerprint": payload["fingerprint"],
    }


def canonical_json_bytes(payload: Any) -> bytes:
    """Stable JSON bytes shared by content hashes and ``view_blob`` storage."""
    from uo_init.kb_index import canonical_json_bytes as _bytes

    return _bytes(payload)


def _content_sha256(payload: Any) -> str:
    """SHA-256 of canonical JSON (not YAML). Prefer :func:`_sha256_bytes`."""
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def export_kb(kb: KnowledgeBase, uo_root: str | Path) -> dict[str, Any]:
    """Write the SQLite KB product and optionally YAML layers; return a receipt.

    Primary write is always ``indexes/kb_graph.sqlite`` (all layers as blobs).
    YAML write is gated by :func:`yaml_export_enabled` (``UO_KB_YAML``, default off).

    Each artifact is serialized to canonical JSON **once**; the same bytes feed
    both the content hash and ``view_blob.data``.
    """
    root = Path(uo_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    assembled = assemble_artifacts(kb)
    artifacts: dict[str, Any] = assembled["artifacts"]
    legal_keys: list[dict[str, Any]] = list(assembled["legal_keys"] or [])
    payload = assembled["graph"]

    # Serialize-once: payload → JSON bytes → hash + DB blob.
    view_json: dict[str, str] = {}
    hashes: dict[str, dict[str, Any]] = {}
    for rel_path, content in sorted(artifacts.items()):
        raw = canonical_json_bytes(content)
        view_json[rel_path] = raw.decode("utf-8")
        hashes[rel_path] = {
            "sha256": _sha256_bytes(raw),
            "status": "extracted",
        }
    if legal_keys:
        legal_raw = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in legal_keys
        ).encode("utf-8")
        hashes["tiling/legal_key_index.jsonl"] = {
            "sha256": _sha256_bytes(legal_raw),
            "status": "extracted",
        }
    # Hash document excludes its own entry to avoid self-referential hashing.
    hash_doc = {
        "version": FORMAT_VERSION,
        "status": "extracted",
        "encoding": "canonical_json",
        "artifacts": dict(hashes),
        "hashes": {rel: meta["sha256"] for rel, meta in hashes.items()},
    }
    hash_raw = canonical_json_bytes(hash_doc)
    view_json["checks/artifact_hashes.yaml"] = hash_raw.decode("utf-8")
    hashes["checks/artifact_hashes.yaml"] = {
        "sha256": _sha256_bytes(hash_raw),
        "status": "extracted",
    }
    artifacts["checks/artifact_hashes.yaml"] = hash_doc

    from uo_init.host_codemap import default_codemap_completeness
    from uo_init.kb_index import write_kb_database

    completeness = kb.notes.get("codemap_completeness")
    if not isinstance(completeness, dict):
        profile = str(
            (kb.notes.get("init_profile") or os.environ.get("UO_INIT_PROFILE") or "fast")
        )
        closure = str(
            (kb.notes.get("closure_mode") or os.environ.get("UO_CLOSURE_MODE") or "keypath")
        )
        completeness = default_codemap_completeness(
            init_profile=profile, closure_mode=closure
        )
    completeness_raw = canonical_json_bytes(completeness)
    view_json["codemap/completeness.yaml"] = completeness_raw.decode("utf-8")
    artifacts["codemap/completeness.yaml"] = completeness
    hashes["codemap/completeness.yaml"] = {
        "sha256": _sha256_bytes(completeness_raw),
        "status": "extracted",
    }

    db_receipt = write_kb_database(
        root,
        payload,
        views=artifacts,
        view_json=view_json,
        artifact_hashes=hashes,
        legal_keys=legal_keys,
        host_derivation=assembled.get("host_derivation"),
        key_reachability=artifacts.get("tiling/key_reachability.yaml"),
        meta={
            "authority": "db",
            "yaml_export": yaml_export_enabled(),
            "integrity_status": "unknown",
            "hash_encoding": "canonical_json",
            "codemap_completeness": completeness,
        },
    )

    wrote_yaml = False
    if yaml_export_enabled():
        wrote_yaml = True
        for rel_path, content in sorted(artifacts.items()):
            _dump(root / rel_path, content)
        if legal_keys:
            from uo_init.materialize_tiling import write_legal_key_index

            write_legal_key_index(root, legal_keys)

    return {
        "ok": True,
        "uo_root": root.as_posix(),
        "graph_fingerprint": assembled["graph_fingerprint"],
        "artifact_count": len(artifacts),
        "node_count": assembled["node_count"],
        "edge_count": assembled["edge_count"],
        "blocker_count": assembled["blocker_count"],
        "legal_key_count": assembled["legal_key_count"],
        "template_block_count": assembled["template_block_count"],
        "materialize_ok": assembled["materialize_ok"],
        "authority": "db",
        "database": db_receipt.get("database"),
        "yaml_export": wrote_yaml,
        "hash_encoding": "canonical_json",
    }



def load_graph(uo_root: str | Path) -> dict[str, Any]:
    """Load the canonical operator graph: the DB first, YAML only as a fallback.

    Reading YAML first would make a stale hand-edited export outrank the
    product every action writes — the same inversion ``authority: db`` in the
    meta table exists to state.
    """
    root = Path(uo_root)
    path = root / "ir" / "operator_graph.yaml"
    db = root / "indexes" / "kb_graph.sqlite"
    payload: Any = None
    source: Any = db
    if db.is_file():
        from uo_init.kb_index import load_view_blob

        payload = load_view_blob(db, "ir/operator_graph.yaml")
    if not isinstance(payload, dict):
        if not path.is_file():
            raise FileNotFoundError(
                f"authoritative graph missing: no DB blob at {db} and no {path}"
            )
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        source = path
    if not isinstance(payload, dict) or payload.get("version") != FORMAT_VERSION:
        raise ValueError(f"unsupported operator graph: {source}")
    for key in ("nodes", "edges", "evidence", "domains"):
        if key not in payload:
            raise ValueError(f"operator graph missing {key}: {source}")
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
