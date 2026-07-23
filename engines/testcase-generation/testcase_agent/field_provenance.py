"""Operator-agnostic CSV field provenance (evidence chain; no invented links)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_field_provenance(
    *,
    schema: dict[str, Any] | None,
    realization_map: dict[str, Any] | None = None,
    uo_summary: dict[str, Any] | None = None,
    lexicon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify CSV fields and attach only evidenced chain links.

    Chain stages (when proven):
      op_input_or_attr → host_expr → tiling → kernel_var → branch → obligation → csv_field

    Missing evidence → ``unresolved`` entries; never fabricate.
    """
    schema = schema if isinstance(schema, dict) else {}
    realization_map = realization_map if isinstance(realization_map, dict) else {}
    lexicon = lexicon if isinstance(lexicon, dict) else {}
    uo_summary = uo_summary if isinstance(uo_summary, dict) else {}

    columns = list(schema.get("columns") or [])
    col_meta = schema.get("column_meta") or schema.get("fields") or {}
    if not isinstance(col_meta, dict):
        col_meta = {}

    try:
        from .domain_policy import (
            is_discrete_int_column,
            is_shape_int_column,
            is_switch_int_column,
        )
    except Exception:  # noqa: BLE001
        is_shape_int_column = lambda _c: False  # type: ignore[misc,assignment]
        is_discrete_int_column = lambda _c: False  # type: ignore[misc,assignment]
        is_switch_int_column = lambda _c: False  # type: ignore[misc,assignment]

    aliases = dict(lexicon.get("csv_field_aliases") or {})
    derivations = list(lexicon.get("key_derivations") or [])
    deriv_by_key = {
        str(d.get("key_id") or ""): d
        for d in derivations
        if isinstance(d, dict) and d.get("key_id")
    }

    # Optional UO input/attr names (evidence only when present)
    uo_inputs = _as_name_set(uo_summary.get("inputs") or uo_summary.get("input_tensors"))
    uo_attrs = _as_name_set(uo_summary.get("attrs") or uo_summary.get("attributes"))

    rmap_fields = realization_map.get("fields") or realization_map.get("csv_fields") or {}
    if not isinstance(rmap_fields, dict):
        rmap_fields = {}

    fields_out: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for col in columns:
        name = str(col)
        meta = col_meta.get(name) if isinstance(col_meta.get(name), dict) else {}
        role = str(meta.get("role") or meta.get("kind") or "").lower()
        if not role:
            if is_shape_int_column(name):
                role = "shape"
            elif is_switch_int_column(name):
                role = "optional_presence"
            elif is_discrete_int_column(name):
                role = "attribute_or_control"
            elif name.lower().endswith(("_dtype", "_type")):
                role = "dtype"
            else:
                role = "unknown"

        chain: list[dict[str, Any]] = [{"stage": "csv_field", "id": name, "role": role}]
        evidence: list[dict[str, Any]] = []
        gaps: list[str] = []

        alias = aliases.get(name)
        if alias:
            chain.append({"stage": "lexicon_alias", "id": str(alias)})
            evidence.append({"kind": "lexicon.csv_field_aliases", "value": str(alias)})

        # Realization map link (only if explicitly present)
        rrow = rmap_fields.get(name) if isinstance(rmap_fields.get(name), dict) else None
        if rrow:
            for key in ("key_id", "var_id", "host_expr", "tiling_field", "kernel_var", "branch_id"):
                if rrow.get(key):
                    chain.append({"stage": key, "id": str(rrow.get(key))})
                    evidence.append({"kind": f"realization_map.{key}", "value": str(rrow.get(key))})
            if rrow.get("evidence"):
                evidence.append({"kind": "realization_map.evidence", "value": rrow.get("evidence")})

        # Lexicon derivation by matching key or column name
        matched_deriv = None
        for d in derivations:
            if not isinstance(d, dict):
                continue
            if str(d.get("csv_field") or "") == name or str(d.get("key_id") or "") == str(alias or ""):
                matched_deriv = d
                break
            if name in str(d.get("expr") or "") and d.get("evidence"):
                matched_deriv = d
                break
        if matched_deriv:
            if matched_deriv.get("key_id"):
                chain.append({"stage": "key_id", "id": str(matched_deriv.get("key_id"))})
            if matched_deriv.get("expr"):
                chain.append({"stage": "host_or_key_expr", "expr": str(matched_deriv.get("expr"))})
            if matched_deriv.get("evidence"):
                evidence.append({"kind": "lexicon.key_derivations.evidence", "value": matched_deriv.get("evidence")})

        # UO name overlap (weak evidence; mark as candidate only)
        stem = name.split("_")[0]
        if name in uo_inputs or stem in uo_inputs:
            chain.append({"stage": "op_input_candidate", "id": name if name in uo_inputs else stem})
            evidence.append({"kind": "uo.inputs.name_overlap", "confidence": "low"})
        elif name in uo_attrs or stem in uo_attrs:
            chain.append({"stage": "op_attr_candidate", "id": name if name in uo_attrs else stem})
            evidence.append({"kind": "uo.attrs.name_overlap", "confidence": "low"})

        # Required stages for a closed chain
        stages = {str(x.get("stage")) for x in chain}
        if role in {"shape", "dtype", "optional_presence", "attribute_or_control"} and "key_id" not in stages and "host_or_key_expr" not in stages:
            gaps.append("missing_host_or_key_link")
        if role == "unknown":
            gaps.append("unclassified_csv_role")
        if not evidence:
            gaps.append("no_source_evidence")

        row = {
            "csv_field": name,
            "role": role,
            "chain": chain,
            "evidence": evidence,
            "closed": not gaps and role != "unknown",
            "unresolved": gaps,
        }
        fields_out.append(row)
        if gaps:
            unresolved.append({"csv_field": name, "gaps": gaps, "role": role})

    return {
        "version": 1,
        "source": "field_provenance",
        "policy": "evidence_only_no_invention",
        "fields": fields_out,
        "unresolved": unresolved,
        "stats": {
            "fields": len(fields_out),
            "closed": sum(1 for f in fields_out if f.get("closed")),
            "open": len(unresolved),
        },
    }


def write_field_provenance(out_root: Path, doc: dict[str, Any]) -> Path:
    from .io import write_yaml

    path = Path(out_root) / "realization" / "field_provenance.yaml"
    write_yaml(path, doc)
    return path


def _as_name_set(rows: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(rows, dict):
        rows = list(rows.keys()) + list(rows.values())
    if not isinstance(rows, list):
        return out
    for row in rows:
        if isinstance(row, str):
            out.add(row)
        elif isinstance(row, dict):
            for k in ("name", "id", "tensor", "attr"):
                if row.get(k):
                    out.add(str(row[k]))
    return out
