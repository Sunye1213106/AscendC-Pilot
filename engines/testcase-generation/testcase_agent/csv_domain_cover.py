"""CSV domain cover points + L1 obligations (full value-domain coverage + shape grids)."""
from __future__ import annotations

import re
from typing import Any

from .atom_bind import csv_var
from .domain_policy import (
    find_head_group_pair,
    head_group_cover_pairs,
    head_group_global_constraint,
    hint_importance_is_low,
    is_varlen_sequence_column,
    key_template_buckets,
    parse_int,
)

# Back-compat alias for older callers / tests.
def gqa_global_constraint(hi_col: str = "N1", lo_col: str = "N2") -> dict[str, Any]:
    return head_group_global_constraint(hi_col, lo_col)

# Columns merged into canonical consumer names during evidence ingest (layout→shape only).
COLUMN_ALIASES: dict[str, str] = {
    "Layout": "Input_Layout",
    "layout": "Input_Layout",
}

MAX_COVER_POINTS = 32
MAX_DISCRETE_EXPAND = 32
RANGE_GRID_STEPS = 6
# Prefer KEY buckets; keep a short mid/high list as fallback only.
RANGE_ANCHORS = (
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    192,
    256,
    512,
    768,
    1024,
    2048,
    4096,
)


def normalize_column_name(column: str) -> str:
    return COLUMN_ALIASES.get(column, column)


def merge_alias_samples(sample_values: dict[str, list[Any]]) -> dict[str, list[Any]]:
    """Merge alias columns (Layout→Input_Layout) into canonical keys."""
    out: dict[str, list[Any]] = {}
    for column, values in sample_values.items():
        canon = normalize_column_name(column)
        bucket = out.setdefault(canon, [])
        for value in values:
            if value not in bucket:
                bucket.append(value)
    return out


def merge_alias_int_ranges(ranges: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for column, rng in ranges.items():
        canon = normalize_column_name(column)
        prev = out.get(canon)
        if prev is None:
            out[canon] = dict(rng)
        else:
            out[canon] = {"min": min(prev["min"], rng["min"]), "max": max(prev["max"], rng["max"])}
    return out


def camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def match_csv_column_for_uo_var(
    var_name: str,
    csv_columns: list[str],
    *,
    semantic_role: str = "",
) -> str | None:
    snake = camel_to_snake(str(var_name or ""))
    bare = snake.replace("_", "")
    col_lower = {c.lower(): c for c in csv_columns}
    role = str(semantic_role or "").lower()
    if snake in col_lower:
        return col_lower[snake]
    matches: list[str] = []
    for col in csv_columns:
        if col.lower().replace("_", "") == bare:
            matches.append(col)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    if role in {"shape", "discrete_knob", "switch"}:
        for col in matches:
            from .domain_policy import is_shape_int_column, is_discrete_int_column, is_switch_int_column

            if role == "shape" and is_shape_int_column(col):
                return col
            if role == "discrete_knob" and is_discrete_int_column(col):
                return col
            if role == "switch" and is_switch_int_column(col):
                return col
    return matches[0]


def extract_uo_domain_entries_by_column(
    files: dict[str, Any],
    csv_columns: list[str],
) -> dict[str, list[Any]]:
    """Map CSV column → discrete values from UO domain_entries (evidence-driven)."""
    out: dict[str, list[Any]] = {}
    for artifact in ("kernel/variables.yaml", "tiling/variables.yaml", "registry/variables.yaml"):
        doc = files.get(artifact) if isinstance(files, dict) else None
        if not isinstance(doc, dict):
            continue
        for section in ("runtime_variables", "variables", "tilingdata_reads"):
            for item in doc.get(section) or []:
                if not isinstance(item, dict):
                    continue
                col = match_csv_column_for_uo_var(str(item.get("name") or item.get("id") or ""), csv_columns)
                if not col:
                    continue
                entries = item.get("domain_entries") or []
                if not isinstance(entries, list):
                    continue
                bucket = out.setdefault(col, [])
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    val = entry.get("value")
                    if val is None:
                        val = entry.get("name")
                    if val is not None and val not in bucket:
                        bucket.append(val)
    return out


def domain_values_list(domain: Any) -> list[Any] | None:
    if isinstance(domain, list) and domain:
        return list(domain)
    if isinstance(domain, dict):
        if domain.get("values") is not None:
            return list(domain.get("values") or [])
        if domain.get("kind") == "range" or (domain.get("min") is not None and domain.get("max") is not None):
            return None  # range — use grid
    return None


def cover_points_for_domain(
    domain: Any,
    *,
    sample_values: list[Any] | None = None,
    column: str = "",
    key_space: dict[str, Any] | None = None,
) -> list[Any]:
    """Cover points for csv_domain_cover obligations. KEY template buckets preferred."""
    samples = list(sample_values or [])
    discrete = domain_values_list(domain)
    if discrete is not None:
        points = list(dict.fromkeys([*samples, *discrete]))
        ints = [parse_int(v) for v in points]
        if all(v is not None for v in ints) and ints:
            return sorted(dict.fromkeys(int(v) for v in ints if v is not None))[:MAX_COVER_POINTS]
        return [str(v) for v in points if str(v) != ""][:MAX_COVER_POINTS]

    if isinstance(domain, dict) and (domain.get("min") is not None or domain.get("max") is not None):
        lo = int(domain.get("min", 1))
        hi = int(domain.get("max", lo))
        if hi < lo:
            lo, hi = hi, lo
        points: list[int] = []
        buckets = [b for b in key_template_buckets(column, key_space) if lo <= b <= hi]
        # Prefer KEY buckets first (half quota), then endpoints / sparse anchors / grid.
        for b in buckets:
            if b not in points:
                points.append(b)
        for endpoint in (lo, hi):
            if endpoint not in points:
                points.append(endpoint)
        for s in samples:
            p = parse_int(s)
            if p is not None and lo <= p <= hi and p not in points:
                points.append(p)
        # Avoid over-weighting arbitrary mid anchors (e.g. 96) when KEY buckets exist.
        anchor_budget = max(2, MAX_COVER_POINTS // 4) if buckets else MAX_COVER_POINTS
        added_anchors = 0
        for anchor in RANGE_ANCHORS:
            if added_anchors >= anchor_budget:
                break
            if lo <= anchor <= hi and anchor not in points:
                points.append(anchor)
                added_anchors += 1
        span = hi - lo
        if span > 0 and len(points) < MAX_COVER_POINTS:
            for i in range(1, RANGE_GRID_STEPS):
                cand = lo + (span * i) // RANGE_GRID_STEPS
                if cand not in points:
                    points.append(cand)
                if len(points) >= MAX_COVER_POINTS:
                    break
        # L0-friendly: ensure at least one non-min when range > min
        if hi > lo and points == [lo]:
            points.append(hi if not buckets else buckets[min(1, len(buckets) - 1)])
        return sorted(dict.fromkeys(points))[:MAX_COVER_POINTS]

    if samples:
        return list(dict.fromkeys(samples))[:MAX_COVER_POINTS]
    return []


def add_csv_domain_cover_obligations(
    out: list[dict[str, Any]],
    realization_map: dict[str, Any],
    *,
    files: dict[str, Any] | None = None,
    consumer_schema: dict[str, Any] | None = None,
) -> None:
    """Emit hard csv_domain_cover for every free CSV solver variable."""
    columns = list((realization_map.get("consumer") or {}).get("columns") or [])
    uo_entries = extract_uo_domain_entries_by_column(files or {}, columns) if files else {}
    sample_by_col: dict[str, list[Any]] = {}
    hints_by_col: dict[str, Any] = {}
    if isinstance(consumer_schema, dict):
        sample_by_col = dict(consumer_schema.get("sample_values") or {})
        hints_doc = consumer_schema.get("domain_hints") or {}
        if isinstance(hints_doc, dict):
            hints_by_col = dict(hints_doc.get("columns") or {})
    # Also load realization/domain_hints via files if stamped on schema path elsewhere — optional.
    key_space = {}
    if isinstance(files, dict):
        key_space = files.get("tiling/key_space.yaml") or files.get("ir/tilingkey_space.yaml") or {}
    emit_skip = {"Testcase_Name", "Enable", "prefix"}
    csv_specs = [s for s in (realization_map.get("csv_variables") or []) if isinstance(s, dict)]
    col_ids = {str(s.get("column") or ""): str(s.get("id") or csv_var(s.get("column"))) for s in csv_specs}
    head_pair = find_head_group_pair(list(col_ids.keys()))
    head_cols = set(head_pair) if head_pair else set()
    domain_by_col = {str(s.get("column") or ""): s.get("domain") for s in csv_specs}

    for spec in csv_specs:
        if spec.get("free") is False:
            continue
        column = str(spec.get("column") or "")
        var_id = str(spec.get("id") or csv_var(column))
        if not column or column.startswith("Actual_") or column in emit_skip:
            continue
        if is_varlen_sequence_column(column) or column.lower().startswith("cu_"):
            continue
        hint = hints_by_col.get(column) if isinstance(hints_by_col.get(column), dict) else {}
        if hint_importance_is_low(hint):
            continue
        # Head-group pair: cover via legal multiples, not independent illegal grids.
        if column in head_cols:
            continue
        domain = spec.get("domain")
        uo_vals = uo_entries.get(column) or uo_entries.get(normalize_column_name(column))
        if uo_vals and isinstance(domain, dict) and domain.get("values") is not None:
            merged = list(dict.fromkeys([*(domain.get("values") or []), *uo_vals]))
            domain = {"values": merged}
        elif uo_vals and isinstance(domain, list):
            domain = list(dict.fromkeys([*domain, *uo_vals]))
        elif uo_vals and isinstance(domain, dict) and domain.get("kind") == "range":
            for v in uo_vals:
                p = parse_int(v)
                if p is not None:
                    hi = int(domain.get("max", p))
                    domain = dict(domain)
                    domain["max"] = max(hi, p)

        sample_vals = list(sample_by_col.get(column) or sample_by_col.get(normalize_column_name(column)) or [])
        points = cover_points_for_domain(
            domain, sample_values=sample_vals, column=column, key_space=key_space if isinstance(key_space, dict) else None
        )
        if not points:
            continue
        for value in points:
            if not _value_fits_domain(value, domain):
                continue
            payload = {
                "column": column,
                "csv_var": var_id,
                "target_value": value,
                "constraints": {"expr": {"op": "eq", "var": var_id, "value": value}},
                "coverage_origin": {"artifact": "consumer_schema", "column": column, "reason": "csv_domain_cover"},
            }
            out.append(_make_csv_cover_obligation(payload, var_id=var_id, value=value))

    if head_pair:
        hi_col, lo_col = head_pair
        hi_id = col_ids[hi_col]
        lo_id = col_ids[lo_col]
        for hi_v, lo_v in head_group_cover_pairs(domain_by_col.get(hi_col), domain_by_col.get(lo_col)):
            payload = {
                "column": hi_col,
                "csv_var": hi_id,
                "target_value": hi_v,
                "constraints": {
                    "expr": {
                        "op": "and",
                        "args": [
                            {"op": "eq", "var": hi_id, "value": hi_v},
                            {"op": "eq", "var": lo_id, "value": lo_v},
                        ],
                    }
                },
                "coverage_origin": {
                    "artifact": "host_tiling_head_group",
                    "column": f"{hi_col}/{lo_col}",
                    "reason": "head_group_multiple",
                },
            }
            out.append(_make_csv_cover_obligation(payload, var_id=hi_id, value=hi_v))


def _make_csv_cover_obligation(payload: dict[str, Any], *, var_id: str, value: Any) -> dict[str, Any]:
    return {
        "id": "",
        "kind": "csv_domain_cover",
        "target_refs": [var_id],
        "source_refs": [],
        "priority": "hard",
        "status": "pending",
        "reachability": "reachable",
        "constraints": payload.get("constraints") or {},
        "realization_hints": {},
        "evidence_refs": [],
        "unresolved_reason": "",
        "target_value": value,
        "field": payload.get("column"),
        "coverage_origin": payload.get("coverage_origin"),
    }


def _value_fits_domain(value: Any, domain: Any) -> bool:
    """Drop sample pollution (e.g. '106x1', stray NONE) that is outside the declared domain."""
    if value is None:
        return False
    if isinstance(value, str) and ("x" in value.lower() or "*" in value):
        # Compound head-group labels must not become scalar CSV covers.
        return False
    if isinstance(domain, list):
        if not domain:
            return True
        if value in domain:
            return True
        try:
            fv = float(value)
            return any(abs(fv - float(v)) < 1e-9 for v in domain)
        except (TypeError, ValueError):
            return str(value) in {str(v) for v in domain}
    if isinstance(domain, dict):
        if "values" in domain:
            return _value_fits_domain(value, list(domain.get("values") or []))
        if domain.get("kind") == "range" or ("min" in domain and "max" in domain):
            try:
                num = float(value)
            except (TypeError, ValueError):
                return False
            lo = domain.get("min")
            hi = domain.get("max")
            if lo is not None and num < float(lo):
                return False
            if hi is not None and num > float(hi):
                return False
            return True
    return True
