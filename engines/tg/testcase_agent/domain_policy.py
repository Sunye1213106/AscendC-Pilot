"""Generalized CSV domain policy: shape ints as ranges; discrete from UO/LLM/human.

No per-operator hard tables — column-name patterns, UO domain_entries, safe caps,
and optional domain_hints (LLM estimate / human confirm).
"""
from __future__ import annotations

import re
from typing import Any

# Shape / counter columns → SMT range (generalizable; not pinned to sample uniques).
SHAPE_COLUMN_RE = re.compile(
    r"^(B|N\d*|S\d*|D(_V)?|Pre_Tockens|Next_Tockens|seed|offset)$",
    re.IGNORECASE,
)
# Binary / small switch knobs — keep discrete {0,1}.
SWITCH_COLUMN_RE = re.compile(
    r"^(rope|is_sink|inner_drop|eod|same_as_input)$",
    re.IGNORECASE,
)
# Discrete int knobs (sparse_mode, etc.) — per-value cover, not wide range.
DISCRETE_INT_COLUMN_RE = re.compile(
    r"^(sparse_mode|PSE_type|inner_drop|pre_tockens|next_tockens)$",
    re.IGNORECASE,
)
LAYOUT_COLUMN_RE = re.compile(r"layout", re.IGNORECASE)
PRIMARY_LAYOUT_COLUMN_RE = re.compile(r"^(input_)?layout$", re.IGNORECASE)
SECONDARY_LAYOUT_PREFIX_RE = re.compile(r"(mask|pse|atten)", re.IGNORECASE)
DTYPE_COLUMN_RE = re.compile(r"dtype", re.IGNORECASE)
# Probability columns: keep_prob vs drop-rate (possibility) differ on allowing 0.
KEEP_PROB_COLUMN_RE = re.compile(r"keep_prob", re.IGNORECASE)
DROP_RATE_COLUMN_RE = re.compile(
    r"(drop_out_possibility|dropout|drop_prob|(?<![a-z])possibility)",
    re.IGNORECASE,
)
# Broad matcher used by schema inference (either keep or drop semantics).
PROBABILITY_COLUMN_RE = re.compile(
    r"(keep_prob|drop_out_possibility|dropout|drop_prob|possibility)",
    re.IGNORECASE,
)
TENSOR_PLACEHOLDER_SENTINELS = frozenset({"_", "NONE", ""})
# Never emit underscore as a CSV cell value for optional/enum fields.
FORBIDDEN_CELL_SENTINELS = frozenset({"_"})
OPTIONAL_ABSENT = "NONE"

# Safe upper bounds when evidence is thin (still finite for Z3).
SAFE_CAPS: dict[str, int] = {
    "B": 64,
    "N": 128,
    "N1": 128,
    "N2": 128,
    "S": 4096,
    "S1": 4096,
    "S2": 4096,
    "D": 1024,
    "D_V": 1024,
    "Pre_Tockens": 65536,
    "Next_Tockens": 65536,
    "seed": 2**31 - 1,
    "offset": 2**31 - 1,
}

KEY_TEMPLATE_HINTS: dict[str, tuple[str, ...]] = {
    "S1": ("S1TemplateNum", "S1TEMPLATENUM"),
    "S2": ("S2TemplateNum", "S2TEMPLATENUM"),
    "D": ("DTemplateNum", "DTEMPLATENUM"),
    "D_V": ("DTemplateNum", "DTEMPLATENUM"),
}

MAX_UNIQUE_PER_COLUMN = 512
MAX_UNIQUE_DISPLAY = 64

LAYOUT_EVIDENCE_LABELS = frozenset(
    {"TND", "BNSD", "BSND", "BSH", "SBH", "ND", "NZ", "NCHW", "NHWC", "BNGSD", "BSNGD", "SBNGD"}
)
DTYPE_EVIDENCE_LABELS = frozenset({"fp16", "bf16", "fp32", "fp8_e4m3fn", "fp8_e5m2", "int8", "hf32"})


def is_shape_int_column(column: str) -> bool:
    return bool(SHAPE_COLUMN_RE.fullmatch(column.strip()))


def is_discrete_int_column(column: str) -> bool:
    return bool(DISCRETE_INT_COLUMN_RE.fullmatch(column.strip()))


def is_switch_int_column(column: str) -> bool:
    return bool(SWITCH_COLUMN_RE.fullmatch(column.strip()))


def is_layout_column(column: str) -> bool:
    return bool(LAYOUT_COLUMN_RE.search(column))


def is_primary_layout_column(column: str) -> bool:
    norm = str(column or "").strip().lower().replace("-", "_")
    if norm in {"layout", "input_layout"}:
        return True
    bare = norm.replace("_", "")
    return bare in {"layout", "inputlayout"}


def is_secondary_layout_column(column: str) -> bool:
    if not is_layout_column(column):
        return False
    if is_primary_layout_column(column):
        return False
    return bool(SECONDARY_LAYOUT_PREFIX_RE.search(column))


def normalize_layout_column_name(column: str) -> str:
    name = str(column or "").strip()
    if name.lower() in {"layout", "input_layout"}:
        return "Input_Layout"
    return name


def layout_columns_by_priority(columns: list[str]) -> list[str]:
    """Primary input layout first; secondary mask/pse layouts last."""
    layout_cols = [c for c in columns if is_layout_column(c)]

    def _rank(col: str) -> tuple[int, str]:
        if is_primary_layout_column(col):
            return (0, col.lower())
        if is_secondary_layout_column(col):
            return (2, col.lower())
        return (1, col.lower())

    return sorted(layout_cols, key=_rank)


def is_tensor_placeholder_domain(samples: list[Any] | None) -> bool:
    if not samples:
        return True
    clean = {str(v).strip().upper() for v in samples if str(v).strip() != ""}
    if not clean:
        return True
    return clean <= {s.upper() for s in TENSOR_PLACEHOLDER_SENTINELS}


def is_switch_domain(samples: list[Any] | None) -> bool:
    ints = [parse_int(v) for v in samples or []]
    if not ints or not all(v is not None for v in ints):
        return False
    return set(ints) <= {0, 1}


def classify_column_role(
    column: str,
    *,
    samples: list[Any] | None = None,
    uo_values: list[Any] | None = None,
    optional_names: set[str] | None = None,
) -> str | None:
    """Return semantic column role for schema/solver policy (generic, not per-op)."""
    col = str(column or "")
    lower = col.lower()
    if is_shape_int_column(col):
        return "shape"
    if is_probability_column(col):
        return "probability"
    if is_discrete_int_column(col):
        return "discrete_knob"
    if is_switch_int_column(col) or is_switch_domain(samples):
        return "switch"
    if is_primary_layout_column(col):
        return "layout_primary"
    if is_layout_column(col):
        return "layout_secondary"
    if is_dtype_column(col):
        return "dtype"
    if optional_names and lower in {n.lower() for n in optional_names}:
        if is_tensor_placeholder_domain(samples) and is_tensor_placeholder_domain(uo_values):
            return "tensor_placeholder"
    if lower.endswith("_shape") or lower.endswith("_type") or lower.endswith("_dtype"):
        return "optional_presence"
    # Bare short columns with only placeholder sentinels (and no UO values) are tensor blobs.
    if is_tensor_placeholder_domain(samples) and is_tensor_placeholder_domain(uo_values) and "_" not in col:
        return "tensor_placeholder"
    return None


def hint_values_take_priority(hint: dict[str, Any] | None) -> bool:
    if not isinstance(hint, dict):
        return False
    if hint.get("locked") is True:
        return True
    source = str(hint.get("source") or "").lower()
    status = str(hint.get("status") or "").lower()
    return status in {"confirmed", "human", "final", "locked", "llm_confirmed"} or source in {"human", "llm_confirmed"}


def is_dtype_column(column: str) -> bool:
    return bool(DTYPE_COLUMN_RE.search(column)) and "mask" not in column.lower()


def is_probability_column(column: str) -> bool:
    return bool(PROBABILITY_COLUMN_RE.search(str(column or "")))


def is_keep_prob_column(column: str) -> bool:
    return bool(KEEP_PROB_COLUMN_RE.search(str(column or "")))


def is_drop_rate_column(column: str) -> bool:
    """Drop-rate columns (possibility/dropout) — domain should include 0, small values, and 1."""
    col = str(column or "")
    if is_keep_prob_column(col):
        return False
    return bool(DROP_RATE_COLUMN_RE.search(col))


def sanitize_domain_values(values: list[Any] | None, *, allow_none: bool = True) -> list[Any]:
    """Drop forbidden '_' cells; optionally keep NONE for optional absence."""
    out: list[Any] = []
    for value in values or []:
        text = str(value).strip() if value is not None else ""
        if text in FORBIDDEN_CELL_SENTINELS:
            continue
        if text == "" and not allow_none:
            continue
        out.append(value if text != "" else OPTIONAL_ABSENT if allow_none else value)
    return list(dict.fromkeys(out))


def shape_layout_alias_map(columns: list[str]) -> dict[str, str]:
    """Map layout-alias columns to canonical shape columns when both exist.

    Generic: Foo_layout → Foo_shape / FOO_shape if present. Primary Input_Layout stays.
    """
    col_lower = {c.lower(): c for c in columns if c}
    aliases: dict[str, str] = {}
    for col in columns:
        lower = col.lower()
        if not lower.endswith("_layout"):
            continue
        if is_primary_layout_column(col):
            continue
        stem = lower[: -len("_layout")]
        for cand in (f"{stem}_shape", f"{stem}_Shape", f"{stem.upper()}_shape"):
            hit = col_lower.get(cand.lower())
            if hit and hit != col:
                aliases[col] = hit
                break
    return aliases


def fold_shape_layout_columns(columns: list[str]) -> tuple[list[str], dict[str, str]]:
    """Return (emit_columns, layout_to_shape_aliases) with layout aliases removed from emit list."""
    aliases = shape_layout_alias_map(columns)
    emit = [c for c in columns if c not in aliases]
    return list(dict.fromkeys(emit)), aliases


def sanitize_cell_value(value: Any, *, role: str = "") -> Any:
    """Replace forbidden '_' with empty or NONE depending on role."""
    if value is None:
        return ""
    text = str(value).strip() if not isinstance(value, (int, float, bool)) else value
    if isinstance(text, str) and text in FORBIDDEN_CELL_SENTINELS:
        if role in {"tensor_placeholder", "metadata", "emit_skip"}:
            return ""
        return OPTIONAL_ABSENT
    return value


def parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def shape_range_domain(
    column: str,
    *,
    sample_ints: list[int] | None = None,
    int_range: dict[str, Any] | None = None,
    key_space: dict[str, Any] | None = None,
    hint_domain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build {kind:range,min,max} from hints/KEY/safe caps (samples optional)."""
    observed: list[int] = list(sample_ints or [])
    if int_range:
        for key in ("min", "max"):
            parsed = parse_int(int_range.get(key))
            if parsed is not None:
                observed.append(parsed)
    if isinstance(hint_domain, dict):
        for key in ("min", "max"):
            parsed = parse_int(hint_domain.get(key))
            if parsed is not None:
                observed.append(parsed)
        for value in hint_domain.get("values") or []:
            parsed = parse_int(value)
            if parsed is not None:
                observed.append(parsed)

    lo = min(observed) if observed else 1
    hi = max(observed) if observed else 1
    # Do not clamp Pre/Next (and similar) to >=1 — may be negative; mark via wide range
    # and force domain review. Shape dims B/N/S/D still stay positive.
    if column.upper() in {"B", "N", "N1", "N2", "S", "S1", "S2", "D", "D_V"}:
        lo = max(1, lo) if lo > 0 else 1
    elif column.upper() in {"PRE_TOCKENS", "NEXT_TOCKENS"} or column in {"Pre_Tockens", "Next_Tockens"}:
        safe = SAFE_CAPS.get(column) or SAFE_CAPS.get(column.upper()) or 65536
        if not observed:
            lo, hi = -int(safe), int(safe)
        else:
            lo = min(lo, -1) if lo >= 0 else lo
            hi = max(hi, 1)

    key_hi = _key_template_upper(column, key_space)
    safe = SAFE_CAPS.get(column) or SAFE_CAPS.get(column.upper()) or SAFE_CAPS.get(_canonical_shape(column) or "")
    pos_shape = column.upper() in {"B", "N", "N1", "N2", "S", "S1", "S2", "D", "D_V"}
    pre_next = column.upper() in {"PRE_TOCKENS", "NEXT_TOCKENS"} or column in {"Pre_Tockens", "Next_Tockens"}

    if pos_shape and key_hi is not None:
        # KEY template upper bound tightens SAFE_CAPS (e.g. DTemplateNum=768 beats SAFE 1024).
        ceiling = min(int(safe), int(key_hi)) if safe is not None else int(key_hi)
        hi = max(hi, ceiling)
        hi = min(hi, int(key_hi))  # clamp LLM/sample hints that exceed KEY
    else:
        candidates = [hi]
        if key_hi is not None:
            candidates.append(key_hi)
        if safe is not None and not pre_next:
            candidates.append(safe)
        elif safe is not None:
            candidates.append(int(safe))
            candidates.append(-int(safe))
        hi = max(candidates)
        if pre_next:
            lo = min(lo, min(candidates))
    if hi < lo:
        hi = lo
    return {"kind": "range", "min": int(lo), "max": int(hi)}


def merge_discrete_int_domain(
    samples: list[Any] | None = None,
    uo_values: list[Any] | None = None,
    hint_values: list[Any] | None = None,
    *,
    max_expand: int = 32,
    hint: dict[str, Any] | None = None,
) -> list[int]:
    """Union UO domain_entries + LLM/human hints (+ optional samples) for discrete ints.

    Priority when hint is confirmed/human: hints > UO > samples > SAFE_CAPS fallback.
    """
    if hint_values and hint_values_take_priority(hint):
        ints = [parse_int(v) for v in hint_values]
        ints = [v for v in ints if v is not None]
        if ints:
            return sorted(dict.fromkeys(ints))[:max_expand]
    ints: list[int] = []
    for value in list(samples or []) + list(uo_values or []) + list(hint_values or []):
        parsed = parse_int(value)
        if parsed is not None:
            ints.append(parsed)
    if not ints:
        return [0]
    out = sorted(dict.fromkeys(ints))
    if len(out) <= max_expand:
        return out
    picked = {out[0], out[-1]}
    step = max(1, len(out) // max_expand)
    for i in range(0, len(out), step):
        picked.add(out[i])
    return sorted(picked)[:max_expand]


def expand_enum_domain(
    column: str,
    samples: list[Any],
    *,
    evidence_tokens: list[str] | None = None,
    hint_values: list[Any] | None = None,
    hint: dict[str, Any] | None = None,
) -> list[str]:
    """Union labels from hints/tokens/samples for layout/dtype-like columns."""
    if hint_values and hint_values_take_priority(hint):
        clean = [str(v) for v in hint_values if str(v) != ""]
        if clean:
            return list(dict.fromkeys(clean))
    clean = [str(v) for v in list(samples or []) + list(hint_values or []) if str(v) != ""]
    out = list(dict.fromkeys(clean))
    if evidence_tokens:
        if is_primary_layout_column(column):
            for token in evidence_tokens:
                t = str(token).strip()
                if t and t.upper() in LAYOUT_EVIDENCE_LABELS and t not in out:
                    out.append(t if t.upper() == t else t.upper())
        if is_dtype_column(column):
            for token in evidence_tokens:
                t = str(token).strip()
                if t and t.lower() in DTYPE_EVIDENCE_LABELS and t not in out:
                    out.append(t.lower())
    # Always union baseline labels only for *primary* layout / dtype columns.
    # Secondary *layout* columns (mask/pse/atten) must not copy Input_Layout enums —
    # leave thin/empty for LLM domain review.
    if is_primary_layout_column(column):
        for label in ("BNSD", "TND", "BSND", "BSH", "SBH"):
            if label not in out:
                out.append(label)
    if is_dtype_column(column):
        for label in ("fp16", "bf16", "fp32"):
            if label not in out:
                out.append(label)
    if not out and is_primary_layout_column(column):
        out = ["BNSD", "TND", "BSND", "BSH", "SBH"]
    if not out and is_dtype_column(column):
        out = ["fp16", "bf16", "fp32"]
    # Never leave '_' as a domain member for consumer-runnable CSV.
    out = [v for v in out if str(v).strip() not in FORBIDDEN_CELL_SENTINELS]
    return list(dict.fromkeys(out))


def probability_domain_values(
    samples: list[Any] | None = None,
    hint_values: list[Any] | None = None,
    *,
    column: str = "",
) -> list[float]:
    """Probability domains: drop-rate includes 0/small/1; keep_prob stays >0."""
    raw: list[float] = []
    for value in list(samples or []) + list(hint_values or []):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        raw.append(parsed)

    if is_drop_rate_column(column) or (not column and not is_keep_prob_column(column) and any(v == 0 for v in raw)):
        # Drop-rate: must cover off (0), small rates, and full (1).
        cleaned = sorted({v for v in raw if 0.0 <= v <= 1.0})
        if not cleaned:
            return [0.0, 0.1, 0.2, 1.0]
        out = list(cleaned)
        if 0.0 not in out:
            out.insert(0, 0.0)
        if 1.0 not in out:
            out.append(1.0)
        # Ensure at least one small mid value when only endpoints exist.
        if not any(0.0 < v < 1.0 for v in out):
            out = sorted(set(out + [0.1, 0.2]))
        return out

    # keep_prob: never 0 (1/p consumers).
    cleaned = sorted({v for v in raw if v > 0})
    if not cleaned:
        return [1.0, 0.9, 0.8]
    return cleaned


def _canonical_shape(column: str) -> str | None:
    upper = column.upper()
    for key in SAFE_CAPS:
        if upper == key.upper():
            return key
    return None


def _key_template_field_values(column: str, key_space: dict[str, Any] | None) -> list[int]:
    if not key_space:
        return []
    hints = KEY_TEMPLATE_HINTS.get(column) or KEY_TEMPLATE_HINTS.get(column.upper()) or ()
    if not hints:
        return []
    out: list[int] = []
    for field in key_space.get("fields") or key_space.get("dimensions") or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or field.get("id") or "")
        bare = name.replace("KEY_", "").replace("VAR_KEY_", "")
        if not any(h.upper() == bare.upper() or bare.upper().endswith(h.upper()) for h in hints):
            continue
        values = field.get("values") or field.get("domain") or []
        if isinstance(values, dict):
            values = values.get("values") or []
        for value in values:
            parsed = parse_int(value)
            if parsed is not None:
                out.append(parsed)
    return sorted(dict.fromkeys(out))


def _key_template_upper(column: str, key_space: dict[str, Any] | None) -> int | None:
    values = _key_template_field_values(column, key_space)
    return max(values) if values else None


def key_template_buckets(column: str, key_space: dict[str, Any] | None) -> list[int]:
    """Discrete KEY template values for cover (prefer over arbitrary anchors)."""
    return _key_template_field_values(column, key_space)


def hint_importance_is_low(hint: dict[str, Any] | None) -> bool:
    if not isinstance(hint, dict):
        return False
    importance = str(hint.get("importance") or "").strip().lower()
    return importance in {"low", "noise", "optional", "skip"}


# --- Generic consumer heuristics (column-name / arch patterns; not per-op tables) ---

# Layouts that typically use per-batch sequence lists instead of fixed S dims.
PACKED_OR_VARLEN_LAYOUTS = frozenset(
    {"TND", "THD", "NTD", "TNH", "VARLEN", "PACKED", "NSA"}
)

# (query_heads_col, kv_heads_col) candidates when both exist as free CSV vars.
HEAD_GROUP_PAIR_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("N1", "N2"),
    ("Nq", "Nkv"),
    ("NQ", "NKV"),
    ("num_q_heads", "num_kv_heads"),
    ("num_heads", "num_kv_heads"),
    ("q_heads", "kv_heads"),
)

# Architecture token → KEY id substrings that may be constant-fixed by platform.
ARCHITECTURE_PLATFORM_KEY_TOKENS: dict[str, tuple[str, ...]] = {
    "arch35": ("ISREGBASE", "REGBASE"),
    "regbase": ("ISREGBASE", "REGBASE"),
    "dav3510": ("ISREGBASE", "REGBASE"),
    "3510": ("ISREGBASE", "REGBASE"),
}

_FIXED_SEQ_DIM_RE = re.compile(r"^(S\d*|S)$", re.IGNORECASE)
_VARLEN_SEQ_COLUMN_RE = re.compile(
    r"(seqlens|cu_seqlens|actual_seq|cu_seq)",
    re.IGNORECASE,
)


def normalize_architecture_token(arch: str) -> str:
    return str(arch or "").strip().lower().replace("-", "").replace("_", "")


def platform_key_tokens_for_architecture(arch: str) -> tuple[str, ...]:
    """Return KEY-name tokens that architecture may fix; empty if unknown."""
    token = normalize_architecture_token(arch)
    if not token:
        return ()
    for key, tokens in ARCHITECTURE_PLATFORM_KEY_TOKENS.items():
        if key in token or token == key:
            return tokens
    # Loose match: any arch*regbase / *3510*
    if "regbase" in token or "3510" in token or "arch35" in token:
        return ARCHITECTURE_PLATFORM_KEY_TOKENS["arch35"]
    return ()


def is_architecture_platform_key(var_id: str, arch: str | None = None) -> bool:
    """True if var_id looks like a platform KEY (optionally for a given architecture)."""
    text = str(var_id or "").upper().replace("-", "_")
    tokens = platform_key_tokens_for_architecture(arch or "") if arch else ()
    if not tokens:
        # Without arch: any known platform token across the map.
        tokens = tuple({t for vals in ARCHITECTURE_PLATFORM_KEY_TOKENS.values() for t in vals})
    return any(tok in text for tok in tokens)


def is_packed_or_varlen_layout(value: Any) -> bool:
    return str(value or "").strip().upper() in PACKED_OR_VARLEN_LAYOUTS


def is_varlen_sequence_column(column: str) -> bool:
    return bool(_VARLEN_SEQ_COLUMN_RE.search(str(column or "")))


def is_fixed_seq_dim_column(column: str) -> bool:
    return bool(_FIXED_SEQ_DIM_RE.fullmatch(str(column or "").strip()))


def primary_layout_column_name(columns: list[str] | None) -> str | None:
    cols = [str(c) for c in (columns or []) if c]
    for col in cols:
        if is_primary_layout_column(col):
            return col
    return None


def find_head_group_pair(columns: list[str] | None) -> tuple[str, str] | None:
    """Return (query_heads, kv_heads) column names when both exist."""
    colset = {str(c) for c in (columns or []) if c}
    for hi, lo in HEAD_GROUP_PAIR_CANDIDATES:
        if hi in colset and lo in colset:
            return hi, lo
    return None


def head_group_cover_pairs(
    hi_domain: Any,
    lo_domain: Any,
    *,
    max_pairs: int = 16,
) -> list[tuple[int, int]]:
    """Legal (hi, lo) pairs with hi % lo == 0 and hi >= lo, derived from domains."""

    def _ints(domain: Any) -> list[int]:
        if isinstance(domain, list):
            return [v for v in (parse_int(x) for x in domain) if v is not None and v > 0]
        if isinstance(domain, dict):
            if domain.get("values") is not None:
                return [v for v in (parse_int(x) for x in (domain.get("values") or [])) if v is not None and v > 0]
            lo = parse_int(domain.get("min"))
            hi = parse_int(domain.get("max"))
            if lo is None or hi is None or hi < lo:
                return []
            # Sparse sample of the range for pair generation.
            span = hi - lo
            steps = min(12, max(1, span))
            out = {max(1, lo), max(1, hi)}
            for i in range(steps + 1):
                out.add(max(1, lo + (span * i) // steps if steps else lo))
            return sorted(out)
        return []

    his = _ints(hi_domain) or [1, 2, 4, 8, 16, 32, 64, 128]
    los = _ints(lo_domain) or [1, 2, 4, 8, 16, 32]
    pairs: list[tuple[int, int]] = []
    for lo_v in los:
        for hi_v in his:
            if hi_v >= lo_v and hi_v % lo_v == 0:
                pairs.append((hi_v, lo_v))
            if len(pairs) >= max_pairs:
                return pairs
    if not pairs:
        pairs = [(1, 1)]
    return pairs[:max_pairs]


def head_group_global_constraint(hi_col: str, lo_col: str) -> dict[str, Any]:
    """Constraint: query_heads is an integer multiple of kv_heads (grouped heads)."""
    from .atom_bind import csv_var

    hi_id = csv_var(hi_col)
    lo_id = csv_var(lo_col)
    return {
        "id": f"CON_HEAD_GROUP_{hi_col}_{lo_col}_MULTIPLE",
        "expr": {
            "op": "and",
            "args": [
                {"op": "ge", "lhs": {"var": hi_id}, "rhs": {"var": lo_id}},
                {
                    "op": "eq",
                    "lhs": {"op": "mod", "args": [{"var": hi_id}, {"var": lo_id}]},
                    "rhs": 0,
                },
            ],
        },
        "source_refs": [{"path": "op_host", "reason": "head_group_multiple"}],
        "description": f"{hi_col} must be an integer multiple of {lo_col} (grouped query heads).",
    }
