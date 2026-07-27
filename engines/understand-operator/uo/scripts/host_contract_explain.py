"""CLI / 查询：explain HostValue / TilingField / KeyDimension。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml


def _load_graphs(uo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    hcg = read_yaml(uo_root / "ir" / "host_configuration_graph.yaml") or {}
    tcg = read_yaml(uo_root / "ir" / "tiling_contract_graph.yaml") or {}
    return hcg, tcg


def _index(entities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in entities if isinstance(e, dict) and e.get("id")}


def explain_host_value(uo_root: Path, value_id: str) -> dict[str, Any]:
    hcg, tcg = _load_graphs(uo_root)
    entities = _index(list(hcg.get("entities") or []) + list(tcg.get("entities") or []))
    ent = entities.get(value_id)
    if not ent:
        # try qualified_name match
        for e in entities.values():
            if e.get("qualified_name") == value_id or e.get("identity_key") == value_id:
                ent = e
                value_id = e["id"]
                break
    if not ent:
        return {"ok": False, "error": f"未找到 HostValue: {value_id}"}
    edges = list(hcg.get("edges") or []) + list(tcg.get("edges") or [])
    deps = []
    for edge in edges:
        if value_id in (edge.get("target_ids") or []) or value_id in (edge.get("source_ids") or []):
            deps.append(edge)
    roots = [
        e
        for e in entities.values()
        if e.get("root_class") == "ConfigurationRoot" or e.get("kind", "").endswith("Root")
    ]
    return {
        "ok": True,
        "value_id": value_id,
        "entity": ent,
        "expression_ir": ent.get("expression_ir"),
        "definition_site": ent.get("definition_site"),
        "guard_context": ent.get("guard_context"),
        "binding_time": ent.get("binding_time"),
        "related_edges": deps,
        "configuration_roots": [
            {"id": r["id"], "kind": r["kind"], "name": r.get("qualified_name")} for r in roots
        ][:20],
        "evidence_refs": ent.get("evidence_refs") or [],
    }


def explain_tiling_field(uo_root: Path, field_id: str) -> dict[str, Any]:
    hcg, tcg = _load_graphs(uo_root)
    entities = _index(list(hcg.get("entities") or []) + list(tcg.get("entities") or []))
    field = entities.get(field_id)
    if not field:
        for e in entities.values():
            if e.get("kind") in {"TilingField", "NestedTilingField", "FieldWrite"} and (
                e.get("field_path") == field_id
                or e.get("qualified_name") == field_id
                or e.get("identity_key") == field_id
            ):
                field = e
                field_id = e["id"]
                break
    if not field:
        return {"ok": False, "error": f"未找到 TilingField: {field_id}"}

    edges = list(tcg.get("edges") or [])
    writes = []
    for e in entities.values():
        if e.get("kind") != "FieldWrite":
            continue
        if e.get("field_path") == field.get("field_path") or field_id in str(e.get("id")):
            writes.append(e)
        for edge in edges:
            if edge.get("type") == "WRITES_FIELD" and field_id in (edge.get("target_ids") or []):
                if e["id"] in (edge.get("source_ids") or []):
                    writes.append(e)

    # unique writes
    seen = set()
    uniq_writes = []
    for w in writes:
        if w["id"] not in seen:
            seen.add(w["id"])
            uniq_writes.append(w)

    input_roots = []
    derivation = []
    for w in uniq_writes:
        for edge in edges + list(hcg.get("edges") or []):
            if w["id"] in (edge.get("target_ids") or []):
                for sid in edge.get("source_ids") or []:
                    src = entities.get(sid)
                    if src:
                        derivation.append({"from": src, "edge": edge, "to_write": w["id"]})
                        if str(src.get("kind", "")).endswith("Root"):
                            input_roots.append(src)

    return {
        "ok": True,
        "field_id": field_id,
        "field": field,
        "input_roots": input_roots,
        "host_derivation_path": derivation,
        "writer_functions": list({w.get("writer_function") for w in uniq_writes if w.get("writer_function")}),
        "schema_variant": field.get("tiling_schema_variant_id")
        or field.get("schema_variant")
        or (uniq_writes[0].get("schema_variant") if uniq_writes else None),
        "field_path": field.get("field_path") or field.get("qualified_name"),
        "guard_conditions": [w.get("guard_context") for w in uniq_writes],
        "field_writes": uniq_writes,
        "source_evidence": field.get("evidence_refs") or [],
    }


def explain_key_dimension(uo_root: Path, dimension_id: str) -> dict[str, Any]:
    hcg, tcg = _load_graphs(uo_root)
    entities = _index(list(hcg.get("entities") or []) + list(tcg.get("entities") or []))
    dim = entities.get(dimension_id)
    if not dim:
        for e in entities.values():
            if e.get("kind") == "KeyDimension" and (
                e.get("qualified_name") == dimension_id
                or e.get("dimension_name") == dimension_id
                or e.get("identity_key") == dimension_id
            ):
                dim = e
                dimension_id = e["id"]
                break
    if not dim:
        # fallback declared_key_space
        for d in (tcg.get("declared_key_space") or {}).get("dimensions") or []:
            if d.get("dimension_name") == dimension_id or str(d.get("ordinal")) == dimension_id:
                dim = d
                break
    if not dim:
        return {"ok": False, "error": f"未找到 KeyDimension: {dimension_id}"}

    sels = [
        e
        for e in entities.values()
        if e.get("kind") == "KeyDimensionSelection"
        and (
            e.get("mapped_dimension") == dim.get("dimension_name")
            or e.get("mapped_dimension") == dim.get("qualified_name")
            or e.get("mapped_ordinal") == dim.get("ordinal")
        )
    ]
    patterns = [e for e in entities.values() if e.get("kind") == "RegisteredTemplatePattern"]
    derivation = []
    for sel in sels:
        for edge in list(tcg.get("edges") or []) + list(hcg.get("edges") or []):
            if sel["id"] in (edge.get("target_ids") or []):
                for sid in edge.get("source_ids") or []:
                    src = entities.get(sid)
                    if src:
                        derivation.append({"from": src, "edge": edge, "selection": sel["id"]})

    return {
        "ok": True,
        "dimension_id": dimension_id if isinstance(dimension_id, str) else dim.get("id"),
        "dimension": dim,
        "input_roots": [
            d["from"]
            for d in derivation
            if str(d["from"].get("kind", "")).endswith("Root")
        ],
        "host_derivation_path": derivation,
        "argument_expressions": [
            s.get("argument_expression") or s.get("argument_expression_ir") for s in sels
        ],
        "argument_positions": [s.get("argument_position") for s in sels],
        "dimension_domain": dim.get("legal_domain"),
        "bit_width": dim.get("bit_width"),
        "legal_template_patterns": [
            {
                "id": p["id"],
                "name": p.get("qualified_name"),
                "source": p.get("source"),
                "template_arguments": p.get("template_arguments"),
            }
            for p in patterns
        ],
        "source_evidence": dim.get("evidence_refs") or dim.get("declaration_evidence"),
        "note_zh": "legal_template_patterns 来自 RegisteredTemplatePattern，非 domain 笛卡尔积",
    }
