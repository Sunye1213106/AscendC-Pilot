# -*- coding: utf-8 -*-
"""Speak the static derivation's language on behalf of a replay case.

The derivation talks about `VAR_SHAPE_QUERY_D2` and `VAR_OPT_PSE_SHIFT`; the
replay side talks about `Case.d` and `Case.pse`. Both describe the same tensor
set, and the translation has been missing, which is why 50 extracted premises
and 19 derived expressions have never once been consulted while generating an
input.

Everything here goes through `inputs._shapes()` rather than reconstructing
shapes, because the variables are syntactic: `VAR_SHAPE_QUERY_D2` is whatever
`queryShape->GetDim(2)` returns, and which quantity that is depends on the
layout. Guessing from the name would be right for TND and wrong for BSND.
"""

from __future__ import annotations

import json
from math import prod
from pathlib import Path
from typing import Any

from . import inputs as I

ROOT = Path(__file__).resolve().parents[2]
DERIVE = ROOT / ".probe_cache" / "fag_derive.json"

#: Replay tensor name -> the slug the derivation minted for it. The derivation
#: slugs the C++ identifier, so `actualSeqQLen` becomes ACTUAL_SEQ_Q_LEN while
#: the operator definition spells it actual_seq_qlen. The rope tensors are
#: reached through an index variable, hence the _IDX tail.
TENSOR_SLUG = {
    "query": "QUERY",
    "key": "KEY",
    "value": "VALUE",
    "dy": "DY",
    "pse_shift": "PSE_SHIFT",
    "drop_mask": "DROP_MASK",
    "padding_mask": "PADDING_MASK",
    "atten_mask": "ATTEN_MASK",
    "softmax_max": "SOFTMAX_MAX",
    "softmax_sum": "SOFTMAX_SUM",
    "attention_in": "ATTENTION_IN",
    "prefix": "PREFIX",
    "actual_seq_qlen": "ACTUAL_SEQ_Q_LEN",
    "actual_seq_kvlen": "ACTUAL_SEQ_KV_LEN",
    "queryRope": "QUERY_ROPE_IDX",
    "keyRope": "KEY_ROPE_IDX",
    "dq": "DQ",
    "dk": "DK",
    "dv": "DV",
    "dpse": "DPSE",
    "dq_rope": "DQ_ROPE",
    "dk_rope": "DK_ROPE",
}

#: Attribute name in `to_csv_line` -> slug. Spelling follows the operator's own
#: attribute names, typos included.
ATTR_SLUG = {
    "scale_value": "SCALE_VALUE",
    "keep_prob": "KEEP_PROB",
    "pre_tockens": "PRE_TOCKENS",
    "next_tockens": "NEXT_TOCKENS",
    "head_num": "HEAD_NUM",
    "input_layout": "INPUT_LAYOUT",
    "inner_precise": "INNER_PRECISE",
    "sparse_mode": "SPARSE_MODE",
    "pse_type": "PSETYPE",
    "out_dtype": "OUT_DTYPE",
}

#: `INPUT_FORMAT_*` in flash_attention_score_grad_tiling_common_regbase.h.
#: BSH and BSND share a code; arch22 numbers them differently and is not this.
LAYOUT_CODE = {"BSH": 1, "BSND": 1, "SBH": 2, "BNSD": 3, "TND": 4}


def _elems(dims: list[int] | None) -> int | None:
    """Element count, or None when the tensor is absent.

    The distinction matters: expressions test `shape != nullptr` before they
    test `size != 0`, so folding an absent tensor to 0 flips those guards.
    """
    if not dims:
        return None
    return prod(dims)


def env_of(case: I.Case) -> dict[str, Any]:
    """The derivation's input variables, valued for this case.

    Host tiling state is deliberately absent. `fBaseParams.layoutType` reads
    like it should be `attr input_layout`, and it is not: `SupportTrans2BS2N2GD`
    rewrites TND to BSND when every sequence is the same length, and a later
    `bn2S2RouteLimit` branch rewrites it back. A dimension reading that field
    is not predictable from the inputs, which is exactly what the derivation
    says by marking it `input_derivable: false`. Supplying a guess here would
    turn an honest "unknown" into a confident wrong answer.
    """
    c = case.normalised()
    ins, outs = I._shapes(c)
    main = I.DT[c.dtype]

    env: dict[str, Any] = {}
    # Unset tiling state reads as unset, not as None: None is reserved for a
    # tensor that was passed but is absent. Supplying a key bound to None here
    # would make an evaluator's `env.get(var)` find a value it never had.
    for var in OBSERVED:
        env.pop(var, None)
    for name, slug in TENSOR_SLUG.items():
        dims = ins.get(name) if name in I.IN_ORDER else outs.get(name)
        present = bool(dims)
        env[f"VAR_OPT_{slug}"] = present
        env[f"VAR_SHAPE_{slug}"] = _elems(dims)
        # `GetDimNum()`, kept apart from the element count above: the host
        # checks a rank of 4 and an element count of 0 on the same tensor.
        env[f"VAR_RANK_{slug}"] = len(dims) if present else None
        env[f"VAR_DTYPE_{slug}"] = (
            I.FIXED_DT.get(name, main) if present else None)
        for i in range(4):
            env[f"VAR_SHAPE_{slug}_D{i}"] = (
                dims[i] if present and i < len(dims) else None)

    n1 = c.n2 * c.g
    for attr, slug in ATTR_SLUG.items():
        env[f"VAR_ATTR_{slug}"] = {
            "scale_value": 1.0 / (c.d ** 0.5),
            "keep_prob": c.keep_prob,
            "pre_tockens": c.pre_tokens,
            "next_tockens": c.next_tokens,
            "head_num": n1,
            "input_layout": c.layout,
            "inner_precise": c.inner_precise,
            "sparse_mode": c.sparse_mode,
            "pse_type": c.pse_type,
            "out_dtype": c.out_dtype,
        }[attr]

    # The prefix-sum tensors are read by value, not just by shape.
    for name, slug in (("actual_seq_qlen", "ACTUAL_SEQ_Q_LEN"),
                       ("actual_seq_kvlen", "ACTUAL_SEQ_KV_LEN")):
        vec = (c.seq_q if name == "actual_seq_qlen" else c.seq_kv) or []
        env[f"VAR_VALUE_{slug}"] = list(vec) or None
        env[f"VAR_ELEM_ELEM_{slug}"] = vec[-1] if vec else None
        env[f"VAR_REDUCE_MAX_{slug}"] = max(vec) if vec else None
        if vec:
            env[f"VAR_SHAPE_{slug}"] = len(vec)
            env[f"VAR_SHAPE_{slug}_D0"] = len(vec)
            env[f"VAR_RANK_{slug}"] = 1

    env["VAR_SESSION_DETERMINISTIC"] = bool(c.deterministic)
    env["VAR_PLATFORM_ARCH"] = 35
    return env


#: Host state the tiling logs, mapped onto the variable that holds it and the
#: dimension whose recorded value it was read from.
#:
#: The provenance is the point. Filling `VAR_TDF_SPLITAXIS` from the observed
#: `SplitAxis` and then "predicting" `SplitAxis` proves nothing -- the answer
#: was the question. Using it to predict `IsNzOut`, which reads the same field,
#: is a real check. So each observation records where it came from and is
#: withheld from the dimension it came from.
OBSERVED: dict[str, tuple[str, str]] = {
    # variable                             log column          from dimension
    "VAR_TDF_FBASEPARAMS_LAYOUTTYPE": ("log_isTnd", "IsTnd"),
    "VAR_TDF_SPLITAXIS": ("log_splitAxis", "SplitAxis"),
    "VAR_TDF_FBASEPARAMS_ISDETERMINISTIC": ("log_isDeterministic", "DeterType"),
    "VAR_AUX_FBASEPARAMS_ISDETERMINISTIC": ("log_isDeterministic", "DeterType"),
}


def observed(row: dict, case: I.Case) -> dict[str, tuple[Any, str]]:
    """Host state this run reported, each with the dimension it was read from.

    Only what the tiling actually printed. The array elements and loop
    reductions the hard dimensions also wait on are not logged, and are left
    unbound rather than guessed -- an unknown that stays unknown costs a
    prediction, an invented one costs the truth of every prediction near it.
    """
    out: dict[str, tuple[Any, str]] = {}
    for var, (col, whose) in OBSERVED.items():
        raw = row.get(col)
        if raw in (None, "", "None"):
            continue
        value: Any = int(raw)
        if var.endswith("LAYOUTTYPE"):
            # The tiling logs the boolean it derives, and `IsTnd` asks for
            # TND specifically. A true one settles it. A false one says the
            # layout is not TND *as the tiling used it* -- which is not the
            # attr's value, because `SupportTrans2BS2N2GD` rewrites a TND
            # layout to BSND when the sequences allow, and the attr still
            # reads TND. Reading the attr back would resurrect the rewritten
            # value the boolean just ruled out.
            value = LAYOUT_CODE["TND"] if value else LAYOUT_CODE["BSND"]
        elif var.endswith("ISDETERMINISTIC"):
            value = bool(value)
        out[var] = (value, whose)
    return out


def grounded_env(base: dict[str, Any], obs: dict[str, tuple[Any, str]]) -> dict[str, Any]:
    """`base` plus every real host state this run printed.

    The values are observed facts, not predictions: `log_splitAxis` is what the
    tiling computed and reported. Filling `VAR_TDF_SPLITAXIS` from it is not the
    self-fulfilling move that filling it from a guessed expression would be, so
    there is no target to exclude for. A dimension that reads the field then
    gets its true value and the rest of the expression is checked against it.
    """
    env = dict(base)
    for var, (value, _whose) in obs.items():
        env[var] = value
    return env


_cache: dict[str, Any] = {}


def derivation() -> dict[str, Any]:
    """The static derivation, read once."""
    if "d" not in _cache:
        with DERIVE.open(encoding="utf-8") as f:
            _cache["d"] = json.load(f)["host_derivation"]
    return _cache["d"]


def fields() -> dict[str, dict]:
    return {f["name"]: f for f in derivation()["fields"]}


def exact_fields() -> dict[str, dict]:
    """Dimensions the derivation claims to know exactly."""
    return {n: f for n, f in fields().items()
            if f["exactness"] in ("exact", "constant") and f.get("value_expr")}


def premises():
    """Every extracted legality condition, graded or not."""
    if "p" not in _cache:
        from uo_init.concrete_eval import Premises

        _cache["p"] = Premises(derivation().get("premises") or [])
    return _cache["p"]


GRADES = ROOT / ".probe_cache" / "replay" / "premise_grades.yaml"


def _unsound() -> set[str] | None:
    """Premises known to refuse inputs the host accepts, by source location.

    None when nothing has been graded yet, which is not the same as nothing
    being unsound: the extraction drops the guard a check sits behind, so
    `CheckSoftmaxMaxShape` demands rank 4 of layouts that never call it. An
    ungraded premise has not been shown to be safe, and gating on it would
    throw away witnesses.
    """
    if not GRADES.is_file():
        return None
    bad, where = set(), ""
    for line in GRADES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- where:"):
            where = line.split(":", 1)[1].strip()
        elif line == "grade: unsound":
            bad.add(where)
    return bad


def gated_premises():
    """The subset a preflight may refuse an input on."""
    if "g" not in _cache:
        from uo_init.concrete_eval import Premises

        bad = _unsound()
        blobs = [] if bad is None else [
            p for p in (derivation().get("premises") or [])
            if f"{Path(str(p.get('file'))).name}:{p.get('line')}" not in bad
        ]
        _cache["g"] = Premises(blobs)
    return _cache["g"]


def refused_by(case: I.Case) -> list[dict]:
    """Premises this case breaks, or an empty list if the host would take it."""
    return gated_premises().violations(env_of(case))


#: Roots naming host tiling state rather than anything a case can set.
STATE_ROOTS = {"TILING_DATA"}


def reads_host_state(field: dict) -> list[str]:
    """Variables in `field` that no input can set, so no env can supply."""
    return sorted(v for v, root in (field.get("var_roots") or {}).items()
                  if root in STATE_ROOTS)
