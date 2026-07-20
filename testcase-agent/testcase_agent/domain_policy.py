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
    r"^(rope|is_sink|inner_drop|eod|same_as_input|keep_prob|Drop_Out_Possibility)$",
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
TENSOR_PLACEHOLDER_SENTINELS = frozenset({"_", "NONE", ""})

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
    source = str(hint.get("source") or "").lower()
    status = str(hint.get("status") or "").lower()
    return status in {"confirmed", "human", "final"} or source in {"human", "llm_confirmed"}


def is_dtype_column(column: str) -> bool:
    return bool(DTYPE_COLUMN_RE.search(column)) and "mask" not in column.lower()


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
    if column.upper() in {"B", "N", "N1", "N2", "S", "S1", "S2", "D", "D_V"}:
        lo = max(1, min(lo, 1) if lo > 0 else 1)

    key_hi = _key_template_upper(column, key_space)
    safe = SAFE_CAPS.get(column) or SAFE_CAPS.get(column.upper()) or SAFE_CAPS.get(_canonical_shape(column) or "")
    candidates = [hi]
    if key_hi is not None:
        candidates.append(key_hi)
    if safe is not None:
        candidates.append(safe)
    hi = max(candidates)
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
        if is_layout_column(column):
            for token in evidence_tokens:
                t = str(token).strip()
                if t and t.upper() in LAYOUT_EVIDENCE_LABELS and t not in out:
                    out.append(t if t.upper() == t else t.upper())
        if is_dtype_column(column):
            for token in evidence_tokens:
                t = str(token).strip()
                if t and t.lower() in DTYPE_EVIDENCE_LABELS and t not in out:
                    out.append(t.lower())
    # Always union baseline layout/dtype labels so domains are not token-pinched.
    if is_layout_column(column):
        for label in ("BNSD", "TND", "BSND", "BSH", "SBH"):
            if label not in out:
                out.append(label)
    if is_dtype_column(column):
        for label in ("fp16", "bf16", "fp32"):
            if label not in out:
                out.append(label)
    if not out and is_layout_column(column):
        out = ["BNSD", "TND", "BSND", "BSH", "SBH"]
    if not out and is_dtype_column(column):
        out = ["fp16", "bf16", "fp32"]
    return list(dict.fromkeys(out))


def _canonical_shape(column: str) -> str | None:
    upper = column.upper()
    for key in SAFE_CAPS:
        if upper == key.upper():
            return key
    return None


def _key_template_upper(column: str, key_space: dict[str, Any] | None) -> int | None:
    if not key_space:
        return None
    hints = KEY_TEMPLATE_HINTS.get(column) or KEY_TEMPLATE_HINTS.get(column.upper()) or ()
    if not hints:
        return None
    best: int | None = None
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
            if parsed is None:
                continue
            best = parsed if best is None else max(best, parsed)
    return best
