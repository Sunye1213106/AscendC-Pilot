"""Evidence-driven binding_lexicon key_derivations (no per-op hard tables)."""
from __future__ import annotations

from typing import Any

from .atom_bind import csv_var
from .binding_lexicon import empty_lexicon, is_locked_derivation, merge_lexicons, normalize_lexicon
from .csv_domain_cover import (
    camel_to_snake,
    extract_uo_domain_entries_by_column,
    match_csv_column_for_uo_var,
    normalize_column_name,
)
from .domain_policy import (
    is_layout_column,
    is_primary_layout_column,
    is_switch_domain,
    is_tensor_placeholder_domain,
    layout_columns_by_priority,
    parse_int,
)
from .io import read_yaml


def load_lexicon_seed(path: Any) -> dict[str, Any]:
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return empty_lexicon(source="seed_missing")
    doc = read_yaml(p)
    return normalize_lexicon(doc if isinstance(doc, dict) else {})


def propose_key_derivations_from_evidence(
    *,
    lexicon: dict[str, Any],
    csv_columns: list[str],
    sample_values: dict[str, list[Any]],
    snapshot_files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Propose KEY/KVAR←CSV derivations from naming + UO domain_entries."""
    base = normalize_lexicon(lexicon)
    columns = [str(c) for c in csv_columns if str(c)]
    col_set = {c: c for c in columns}
    col_lower = {c.lower(): c for c in columns}
    locked = {
        str(item.get("id") or "")
        for item in base.get("key_derivations") or []
        if isinstance(item, dict) and is_locked_derivation(item)
    }
    existing = {
        str(item.get("id") or "")
        for item in base.get("key_derivations") or []
        if isinstance(item, dict) and item.get("id")
    }
    proposals: list[dict[str, Any]] = []

    contract = (snapshot_files or {}).get("contracts/testcase.yaml")
    optional_inputs_lower: set[str] = set()
    if isinstance(contract, dict):
        for item in ((contract.get("interface") or {}).get("optional_inputs") or []):
            if isinstance(item, dict) and item.get("name"):
                optional_inputs_lower.add(str(item["name"]).lower())

    uo_entries_by_col = extract_uo_domain_entries_by_column(snapshot_files or {}, columns)

    for item in _propose_from_uo_determinants(snapshot_files or {}, columns, existing | locked):
        proposals.append(item)
        existing.add(str(item.get("id") or ""))

    for token, spec in (base.get("key_tokens") or {}).items():
        if not isinstance(spec, dict):
            continue
        var_id = str(spec.get("var") or "")
        if not var_id or var_id in existing or var_id in locked:
            continue
        true_value = int(spec.get("true_value", 1))
        bare = _token_bare(str(token))
        if not bare:
            continue

        presence = _propose_presence_predicate(
            var_id,
            bare,
            columns,
            col_lower,
            sample_values,
            uo_entries_by_col,
            true_value,
            token=str(token),
        )
        if presence is not None:
            proposals.append(presence)
            existing.add(var_id)
            continue

        col = col_lower.get(bare.lower()) or col_lower.get(f"is_{bare.lower()}")
        if col and not _is_tensor_column(col, sample_values, uo_entries_by_col):
            # Optional tensor blob columns (q/k/v/pse/...) must not be used for IS* presence flags.
            if bare.lower() in optional_inputs_lower and col.lower() == bare.lower():
                continue
            if is_switch_domain(sample_values.get(col)) or parse_int((sample_values.get(col) or [None])[0]) in (0, 1):
                proposals.append(
                    _flag_derivation(var_id, col, true_value, rationale=f"{col} == {true_value} (token {token})")
                )
                existing.add(var_id)
                continue

        layout_hit = _match_layout_enum(bare, columns, sample_values)
        if layout_hit is not None:
            col_name, label = layout_hit
            proposals.append(
                _enum_derivation(
                    var_id,
                    col_name,
                    label,
                    true_value,
                    rationale=f"{col_name} == {label} (token {token})",
                )
            )
            existing.add(var_id)
            continue

        if bare.upper() in {"ATTENMASK", "ATTEN_MASK", "ATTENTIONMASK"}:
            for candidate in ("Atten_mask_shape", "atten_mask_shape", "AttenMaskShape"):
                if candidate in col_set or candidate.lower() in col_lower:
                    real = col_set.get(candidate) or col_lower[candidate.lower()]
                    proposals.append(
                        {
                            "id": var_id,
                            "type": "int",
                            "domain": [0, 1],
                            "expr": {
                                "op": "if_then_else",
                                "condition": {"op": "ne", "var": csv_var(real), "value": "NONE"},
                                "then": true_value,
                                "else": 0 if true_value != 0 else 1,
                            },
                            "rationale": f"{real} != NONE (token {token})",
                            "source_refs": [{"path": "evidence_key_derivation", "token": token}],
                        }
                    )
                    existing.add(var_id)
                    break

    for item in _propose_domain_entry_maps(snapshot_files or {}, columns, existing | locked):
        proposals.append(item)
        existing.add(str(item.get("id") or ""))

    if not proposals:
        return base
    patched = dict(base)
    patched["key_derivations"] = list(base.get("key_derivations") or []) + proposals
    patched["source"] = str(base.get("source") or "") + "+evidence_derivations"
    patched.setdefault("warnings", [])
    patched["warnings"] = list(patched["warnings"]) + [
        f"evidence_key_derivation: proposed {len(proposals)} key_derivations from CSV/UO evidence"
    ]
    return normalize_lexicon(patched)


def _propose_from_uo_determinants(
    files: dict[str, Any],
    csv_columns: list[str],
    existing: set[str],
) -> list[dict[str, Any]]:
    contract = files.get("contracts/testcase.yaml")
    if not isinstance(contract, dict):
        return []
    determinants = contract.get("key_determinants") or {}
    if not isinstance(determinants, dict):
        return []
    col_lower = {c.lower(): c for c in csv_columns}
    out: list[dict[str, Any]] = []
    for key_id, spec in determinants.items():
        if not isinstance(spec, dict):
            continue
        var_id = f"VAR_{key_id}" if not str(key_id).startswith("VAR_") else str(key_id)
        if var_id in existing:
            continue
        preds = spec.get("csv_determinants") or []
        if not isinstance(preds, list) or not preds:
            continue
        expr = _expr_from_csv_determinants(preds, col_lower)
        if expr is None:
            continue
        out.append(
            {
                "id": var_id,
                "type": "int",
                "domain": [0, 1],
                "expr": expr,
                "rationale": f"{var_id} from UO key_determinants",
                "source_refs": [{"path": "contracts/testcase.yaml", "key": key_id}],
                "locked": True,
            }
        )
    return out


def _expr_from_csv_determinants(preds: list[dict[str, Any]], col_lower: dict[str, str]) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    combine = "and"
    for pred in preds:
        if not isinstance(pred, dict):
            continue
        if pred.get("combine") in {"and", "or"} and not pred.get("column"):
            combine = str(pred.get("combine"))
            continue
        column = str(pred.get("column") or "")
        real = col_lower.get(column.lower()) or column
        op = str(pred.get("op") or "eq")
        value = pred.get("value")
        if op == "eq":
            clauses.append({"op": "eq", "var": csv_var(real), "value": value})
        elif op == "ne":
            clauses.append({"op": "ne", "var": csv_var(real), "value": value})
        elif op == "present":
            clauses.append({"op": "ne", "var": csv_var(real), "value": "_"})
            clauses.append({"op": "ne", "var": csv_var(real), "value": "NONE"})
    if not clauses:
        return None
    if len(clauses) == 1:
        condition = clauses[0]
    else:
        condition = {"op": combine, "args": clauses}
    return {
        "op": "if_then_else",
        "condition": condition,
        "then": 1,
        "else": 0,
    }


def _is_tensor_column(
    column: str,
    sample_values: dict[str, list[Any]],
    uo_entries_by_col: dict[str, list[Any]] | None,
) -> bool:
    samples = list(sample_values.get(column) or [])
    uo_vals = []
    if isinstance(uo_entries_by_col, dict):
        uo_vals = uo_entries_by_col.get(column) or uo_entries_by_col.get(normalize_column_name(column)) or []
    # Only classify as tensor placeholder when both evidence sources look like placeholders.
    return is_tensor_placeholder_domain(samples) and is_tensor_placeholder_domain(uo_vals)


def _propose_presence_predicate(
    var_id: str,
    bare: str,
    columns: list[str],
    col_lower: dict[str, str],
    sample_values: dict[str, list[Any]],
    uo_entries_by_col: dict[str, list[Any]] | None,
    true_value: int,
    *,
    token: str,
) -> dict[str, Any] | None:
    """IS* optional/presence flags bind to *_shape / *_type, not tensor placeholder columns."""
    stem = bare.lower().replace("_", "")
    shape_col = _find_affixed_column(stem, "shape", columns, col_lower)
    type_col = _find_affixed_column(stem, "type", columns, col_lower)
    clauses: list[dict[str, Any]] = []
    # Prefer shape/type columns by naming even when current samples are placeholders —
    # domain_hints / UO entries will expand the enum later.
    if shape_col:
        clauses.append({"op": "ne", "var": csv_var(shape_col), "value": "NONE"})
        clauses.append({"op": "ne", "var": csv_var(shape_col), "value": "_"})
    if type_col:
        clauses.append({"op": "ne", "var": csv_var(type_col), "value": 0})
    if not clauses:
        return None
    condition: dict[str, Any]
    if len(clauses) == 1:
        condition = clauses[0]
    else:
        condition = {"op": "or", "args": clauses}
    return {
        "id": var_id,
        "type": "int",
        "domain": [0, 1],
        "expr": {
            "op": "if_then_else",
            "condition": condition,
            "then": 1 if true_value != 0 else 0,
            "else": 0 if true_value != 0 else 1,
        },
        "rationale": f"presence via shape/type columns for token {token}",
        "source_refs": [{"path": "evidence_key_derivation", "token": token, "kind": "presence_predicate"}],
    }


def _find_affixed_column(stem: str, suffix: str, columns: list[str], col_lower: dict[str, str]) -> str | None:
    candidates = [
        f"{stem}_{suffix}",
        f"{stem.upper()}_{suffix}",
        f"{stem}_{suffix.upper()}",
    ]
    for cand in candidates:
        if cand.lower() in col_lower:
            return col_lower[cand.lower()]
    for col in columns:
        lower = col.lower()
        if lower.endswith(f"_{suffix}") and stem in lower.replace("_", ""):
            return col
    return None


def _propose_domain_entry_maps(
    files: dict[str, Any],
    csv_columns: list[str],
    existing: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    uo_meta = _uo_variable_meta_by_id(files)
    for artifact in ("kernel/variables.yaml", "tiling/variables.yaml"):
        doc = files.get(artifact)
        if not isinstance(doc, dict):
            continue
        for section in ("runtime_variables", "variables", "tilingdata_reads"):
            for item in doc.get(section) or []:
                if not isinstance(item, dict):
                    continue
                entries = item.get("domain_entries")
                if not isinstance(entries, list) or not entries:
                    continue
                name = str(item.get("name") or "")
                var_raw = str(item.get("id") or "")
                col = item.get("csv_column") or match_csv_column_for_uo_var(
                    name or var_raw,
                    csv_columns,
                    semantic_role=str(item.get("semantic_role") or uo_meta.get(var_raw, {}).get("semantic_role") or ""),
                )
                if not col:
                    continue
                if var_raw.upper().startswith(("KVAR_", "KEY_", "TDF_")):
                    var_id = var_raw if var_raw.startswith("VAR_") else f"VAR_{var_raw}"
                elif name:
                    snake = camel_to_snake(name).upper().replace("_", "")
                    var_id = f"VAR_KVAR_{snake}"
                else:
                    continue
                if var_id in existing:
                    continue
                pairs: list[tuple[Any, Any]] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    csv_val = entry.get("csv_value", entry.get("value"))
                    kvar_label = entry.get("name")
                    if csv_val is None:
                        continue
                    if kvar_label is not None and parse_int(kvar_label) is None:
                        mapped: Any = kvar_label
                    else:
                        mapped = csv_val
                    pairs.append((csv_val, mapped))
                if not pairs:
                    continue
                domain_vals = [p[1] for p in pairs]
                out.append(
                    {
                        "id": var_id,
                        "type": "int" if all(parse_int(v) is not None for v in domain_vals) else "enum",
                        "domain": list(domain_vals),
                        "expr": _map_chain_expr(csv_var(col), pairs),
                        "rationale": f"{var_id} ← map({col}) via UO domain_entries",
                        "source_refs": [{"path": artifact, "name": name, "column": col}],
                    }
                )
                existing.add(var_id)
    return out


def _uo_variable_meta_by_id(files: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    doc = files.get("kernel/variables.yaml")
    if not isinstance(doc, dict):
        return out
    for section in ("runtime_variables", "variables", "tilingdata_reads"):
        for item in doc.get(section) or []:
            if isinstance(item, dict) and item.get("id"):
                out[str(item["id"])] = item
    return out


def _map_chain_expr(csv_var_id: str, pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    if not pairs:
        return 0
    expr: Any = pairs[-1][1]
    for csv_val, mapped in reversed(pairs[:-1]):
        expr = {
            "op": "if_then_else",
            "condition": {"op": "eq", "var": csv_var_id, "value": csv_val},
            "then": mapped,
            "else": expr,
        }
    if len(pairs) == 1:
        csv_val, mapped = pairs[0]
        expr = {
            "op": "if_then_else",
            "condition": {"op": "eq", "var": csv_var_id, "value": csv_val},
            "then": mapped,
            "else": mapped,
        }
    return expr


def merge_lexicon_layers(*docs: dict[str, Any] | None) -> dict[str, Any]:
    return normalize_lexicon(merge_lexicons(*docs))


def _token_bare(token: str) -> str:
    t = token.upper().replace("-", "_")
    if t.startswith("IS_"):
        return t[3:]
    if t.startswith("IS") and len(t) > 2 and t[2:3] != "_":
        return t[2:]
    return t


def _match_layout_enum(
    bare: str,
    columns: list[str],
    sample_values: dict[str, list[Any]],
) -> tuple[str, str] | None:
    bare_u = bare.upper().replace("_", "")
    for col in layout_columns_by_priority(columns):
        if not is_layout_column(col):
            continue
        values = list(sample_values.get(col) or [])
        if not values and bare_u in {"TND", "BNSD", "BSND", "BSH", "SBH"}:
            if is_primary_layout_column(col):
                return col, bare_u
            continue
        for value in values:
            label = str(value)
            if not label:
                continue
            if label.upper().replace("_", "") == bare_u or label.upper() == bare.upper():
                if is_primary_layout_column(col):
                    return col, label
    for col in layout_columns_by_priority(columns):
        if not is_layout_column(col) or is_primary_layout_column(col):
            continue
        values = list(sample_values.get(col) or [])
        for value in values:
            label = str(value)
            if label and (label.upper().replace("_", "") == bare_u or label.upper() == bare.upper()):
                return col, label
    return None


def _flag_derivation(var_id: str, column: str, true_value: int, *, rationale: str) -> dict[str, Any]:
    return {
        "id": var_id,
        "type": "int",
        "domain": [0, 1],
        "expr": {
            "op": "if_then_else",
            "condition": {"op": "eq", "var": csv_var(column), "value": true_value},
            "then": true_value if true_value in (0, 1) else 1,
            "else": 0 if true_value != 0 else 1,
        },
        "rationale": rationale,
        "source_refs": [{"path": "evidence_key_derivation", "column": column}],
    }


def _enum_derivation(
    var_id: str,
    column: str,
    label: str,
    true_value: int,
    *,
    rationale: str,
) -> dict[str, Any]:
    return {
        "id": var_id,
        "type": "int",
        "domain": [0, 1],
        "expr": {
            "op": "if_then_else",
            "condition": {"op": "eq", "var": csv_var(column), "value": label},
            "then": 1 if true_value != 0 else 0,
            "else": 0 if true_value != 0 else 1,
        },
        "rationale": rationale,
        "source_refs": [{"path": "evidence_key_derivation", "column": column, "value": label}],
    }
