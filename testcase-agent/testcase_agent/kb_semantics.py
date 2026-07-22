"""Assemble TG-side semantic views from UO KB layers (no UO contracts/**)."""

from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _iter_fields(key_space: dict[str, Any]) -> list[dict[str, Any]]:
    fields = key_space.get("fields") or key_space.get("dimensions") or []
    if isinstance(fields, dict):
        out: list[dict[str, Any]] = []
        for key, item in fields.items():
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("id", str(key))
                out.append(row)
            else:
                out.append({"id": str(key), "value": item})
        return out
    if isinstance(fields, list):
        return [item for item in fields if isinstance(item, dict)]
    return []


def assemble_key_determinants(snapshot_files: dict[str, Any] | None) -> dict[str, Any]:
    """Build key_determinants from tiling/key_space + ir/input_derivable (+ optional cards)."""
    files = snapshot_files if isinstance(snapshot_files, dict) else {}
    key_space = _as_dict(files.get("tiling/key_space.yaml"))
    id_doc = _as_dict(files.get("ir/input_derivable.yaml"))
    by_key = id_doc.get("keys") if isinstance(id_doc.get("keys"), dict) else {}

    # Prefer overlay already stamped into key_space fields during UO export.
    determinants: dict[str, Any] = {}
    for field in _iter_fields(key_space):
        key_id = str(field.get("id") or "")
        if not key_id:
            continue
        entry = by_key.get(key_id) if isinstance(by_key.get(key_id), dict) else {}
        has_signal = (
            field.get("csv_determinants")
            or field.get("role")
            or field.get("needs_binding")
            or "input_derivable" in field
            or entry
        )
        if not has_signal:
            continue
        det: dict[str, Any] = {
            "role": field.get("role") or entry.get("role"),
            "semantic_role": field.get("semantic_role") or field.get("role") or entry.get("role"),
            "csv_determinants": list(field.get("csv_determinants") or entry.get("csv_determinants") or []),
            "primary_layout_field": field.get("primary_layout_field") or entry.get("primary_layout_field"),
            "needs_binding": bool(field.get("needs_binding", entry.get("needs_binding", False))),
        }
        idv = field["input_derivable"] if "input_derivable" in field else entry.get("input_derivable")
        if idv is not None or entry:
            det["input_derivable"] = idv
            det["not_input_derivable"] = bool(
                field.get("not_input_derivable", entry.get("not_input_derivable"))
            )
            det["host_parent"] = field.get("host_parent", entry.get("host_parent"))
            det["host_parent_evidence"] = (
                field.get("host_parent_evidence") or entry.get("host_parent_evidence") or ""
            )
            det["derivation_roots"] = list(
                field.get("derivation_roots") or entry.get("derivation_roots") or []
            )[:16]
            gap = field.get("gap_ref") or entry.get("gap_ref")
            if gap:
                det["gap_ref"] = gap
            if idv is True:
                det["needs_binding"] = True
            elif idv is False or det.get("not_input_derivable"):
                det["needs_binding"] = False
            elif idv == "unsolved":
                det["needs_binding"] = True
        determinants[key_id] = det

    # Keys classified in input_derivable but missing from key_space fields.
    for key_id, entry in by_key.items():
        if not isinstance(entry, dict) or str(key_id) in determinants:
            continue
        idv = entry.get("input_derivable")
        determinants[str(key_id)] = {
            "role": entry.get("role"),
            "semantic_role": entry.get("role"),
            "csv_determinants": list(entry.get("csv_determinants") or []),
            "primary_layout_field": entry.get("primary_layout_field"),
            "needs_binding": bool(
                entry.get("needs_binding", idv is True or idv == "unsolved")
            ),
            "input_derivable": idv,
            "not_input_derivable": bool(entry.get("not_input_derivable")),
            "host_parent": entry.get("host_parent"),
            "host_parent_evidence": entry.get("host_parent_evidence") or "",
            "derivation_roots": list(entry.get("derivation_roots") or [])[:16],
        }
        if entry.get("gap_ref"):
            determinants[str(key_id)]["gap_ref"] = entry.get("gap_ref")

    # Cards may carry role hints when key_space is thin.
    for rel, card in files.items():
        if not (isinstance(rel, str) and rel.startswith("tiling/key_cards/") and isinstance(card, dict)):
            continue
        key_id = str(card.get("id") or "")
        if not key_id or key_id in determinants:
            continue
        if card.get("role") or card.get("csv_determinants") or "input_derivable" in card:
            determinants[key_id] = {
                "role": card.get("role"),
                "semantic_role": card.get("semantic_role") or card.get("role"),
                "csv_determinants": list(card.get("csv_determinants") or []),
                "primary_layout_field": card.get("primary_layout_field"),
                "needs_binding": bool(card.get("needs_binding", not (card.get("csv_determinants") or []))),
                **(
                    {
                        "input_derivable": card.get("input_derivable"),
                        "not_input_derivable": bool(card.get("not_input_derivable")),
                        "host_parent": card.get("host_parent"),
                        "host_parent_evidence": card.get("host_parent_evidence") or "",
                        "derivation_roots": list(card.get("derivation_roots") or [])[:16],
                    }
                    if "input_derivable" in card
                    else {}
                ),
            }
    return determinants


def assemble_optional_inputs(snapshot_files: dict[str, Any] | None) -> list[dict[str, Any]]:
    files = snapshot_files if isinstance(snapshot_files, dict) else {}
    graph = _as_dict(files.get("ir/operator_graph.yaml"))
    nodes = graph.get("nodes") or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("node_type") or "")
        nid = str(node.get("id") or "")
        name = str(node.get("name") or nid)
        if ntype == "OptionalInputPresence" or nid.startswith("VAR_OPTIONAL_"):
            opt_id = nid if nid.startswith("VAR_OPTIONAL_") else f"VAR_OPTIONAL_{name}"
            if opt_id in seen:
                continue
            seen.add(opt_id)
            out.append(
                {
                    "id": opt_id,
                    "name": name,
                    "role": "optional_presence",
                    "semantic_role": "optional_presence",
                }
            )
    return out


def assemble_golden_contract(snapshot_files: dict[str, Any] | None) -> dict[str, Any]:
    files = snapshot_files if isinstance(snapshot_files, dict) else {}
    golden = _as_dict(files.get("flow/golden_model.yaml"))
    gen = (golden.get("golden_generation_contract") or [None])[0]
    if isinstance(gen, dict):
        return {
            "inputs": list(gen.get("pipeline", {}).get("inputs") or []),
            "outputs": list(gen.get("outputs") or []),
            "generation_policy": ["reference"] if gen.get("function") else [],
            "tolerance_policy": ["fp16"],
            "function": gen.get("function"),
            "file_path": gen.get("file_path"),
            "signature": gen.get("signature"),
            "start_line": gen.get("start_line"),
            "end_line": gen.get("end_line"),
            "pipeline": gen.get("pipeline") or {},
            "helpers": gen.get("helpers") or [],
        }
    return {
        "inputs": [],
        "outputs": [],
        "generation_policy": [],
        "tolerance_policy": [],
    }
