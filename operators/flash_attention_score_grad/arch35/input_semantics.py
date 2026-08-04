# -*- coding: utf-8 -*-
"""FlashAttentionScoreGrad input semantics: Case, shapes, dtypes, report.

Lives in the operator package because every rule here is FAG-specific: the
five layouts, the seven pse forms, TND prefix sums, sparse prefix, rope D.
The generic engine only knows the InputSemantics protocol; this file is the
FAG answer to that protocol.

TND is the reason this file exists. There, B and S are absent from every shape:
B is the length of the actual_seq_qlen tensor and the per-batch lengths are the
first differences of its contents, which are a prefix sum. A whole family of
tiling decisions keys off properties of that vector -- all-equal lengths, a zero
somewhere, EOD trailing zeros -- and no amount of reshaping can reach them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

LAYOUTS = ("SBH", "BSH", "BNSD", "BSND", "TND")

#: Mask variants the host classifies, plus the absent case. Anything else is
#: refused: silently dropping it produced a case with no mask under a name
#: saying it had one.
ATTEN_MASKS = ("none", "ss", "2048", "bnss", "b1ss", "11ss")

#: Pse variants the host classifies. Anything else is refused: falling back
#: to bnss made every case naming an unknown shape a duplicate of one that
#: already ran.
PSE_SHAPES = ("bnss", "b1ss", "1nss", "1nhs", "bnhs", "slope", "slope_n")

#: ge::DataType codes, by name.
DT = {
    "FLOAT": 0, "FLOAT16": 1, "INT8": 2, "INT32": 3, "UINT8": 4, "INT64": 9,
    "BF16": 27, "HIFLOAT8": 34, "FLOAT8_E5M2": 35, "FLOAT8_E4M3FN": 36,
}

#: Positional order of the operator's 24 inputs.
IN_ORDER = [
    "query", "key", "value", "dy", "pse_shift", "drop_mask", "padding_mask",
    "atten_mask", "softmax_max", "softmax_sum", "softmax_in", "attention_in",
    "prefix", "actual_seq_qlen", "actual_seq_kvlen", "q_start_idx", "kv_start_idx",
    "dScaleQ", "dScaleK", "dScaleV", "dScaledy", "dScaleo", "queryRope", "keyRope",
]
OUT_ORDER = ["dq", "dk", "dv", "dpse", "dq_rope", "dk_rope"]

#: Inputs whose dtype is fixed regardless of the case's main dtype.
FIXED_DT = {
    "drop_mask": DT["UINT8"], "padding_mask": DT["FLOAT"], "atten_mask": DT["UINT8"],
    "softmax_max": DT["FLOAT"], "softmax_sum": DT["FLOAT"],
    "prefix": DT["INT64"], "actual_seq_qlen": DT["INT64"],
    "actual_seq_kvlen": DT["INT64"], "q_start_idx": DT["INT64"],
    "kv_start_idx": DT["INT64"],
}

ROPE_D = 64
#: MAX_BASIC_BLOCK_SIZE, the fixed middle extent of the alibi pse shapes.
PSE_ALIBI_S = 1024
#: D that the host substitutes whenever rope inputs are present.
ROPE_TOTAL_D = 192


@dataclass
class Case:
    """One replayable input, described by the quantities tiling reads."""

    layout: str = "BSND"
    dtype: str = "FLOAT16"
    b: int = 1
    s1: int = 128
    s2: int = 128
    n2: int = 1
    g: int = 1
    d: int = 128
    d1: int | None = None          # value's D; defaults to d
    atten_mask: str = "none"       # none | ss | 2048 | bnss | b1ss | 11ss
    pse: bool = False
    pse_shape: str = "bnss"        # bnss | b1ss | 1nss | 1nhs | bnhs
    rope: bool = False
    keep_prob: float = 1.0
    sparse_mode: int = 0
    pre_tokens: int = 65536
    next_tokens: int = 65536
    inner_precise: int = 0
    pse_type: int = 1
    out_dtype: int = 0
    deterministic: int = 0
    #: TND only: prefix sums, i.e. cumulative sequence lengths per batch.
    seq_q: list[int] | None = None
    seq_kv: list[int] | None = None
    #: sparse_mode 5/6 only: per-batch prefix lengths, one entry per batch.
    prefix_n: list[int] | None = None
    tag: str = ""

    @property
    def n1(self) -> int:
        return self.n2 * self.g

    @property
    def dv(self) -> int:
        return self.d if self.d1 is None else self.d1

    @property
    def lens_q(self) -> list[int]:
        """Per-batch query lengths, i.e. first differences of the prefix sum."""
        return _diff(self.seq_q or [])

    @property
    def lens_kv(self) -> list[int]:
        return _diff(self.seq_kv or [])

    def normalised(self) -> "Case":
        """Make the case self-consistent so tiling will not reject it outright."""
        c = self
        if c.layout == "TND":
            q = c.seq_q or _uniform_prefix(c.b, c.s1)
            kv = c.seq_kv or _uniform_prefix(c.b, c.s2)
            if len(kv) != len(q):
                kv = _uniform_prefix(len(q), c.s2)
            # B and the S values are read off the vector, not off any shape, so
            # they have to be brought back in line with it or the two disagree.
            lens_q, lens_kv = _diff(q), _diff(kv)
            c = replace(c, seq_q=q, seq_kv=kv, b=len(q),
                        s1=max(lens_q) if lens_q else 0,
                        s2=max(lens_kv) if lens_kv else 0)
        if c.rope:
            c = replace(c, d=ROPE_TOTAL_D, d1=None)
        if c.sparse_mode in (5, 6):
            # Tiling insists on one entry per batch here and refuses the case
            # outright otherwise, so the vector is sized from b, not sampled.
            want = c.prefix_n or [max(c.s2 // 2, 0)]
            c = replace(c, prefix_n=[want[i % len(want)] for i in range(c.b)])
        else:
            c = replace(c, prefix_n=None)
        return c


def _diff(prefix: list[int]) -> list[int]:
    """Recover per-batch lengths, clamping negatives the way the host does."""
    out = []
    for i, v in enumerate(prefix):
        got = v if i == 0 else v - prefix[i - 1]
        out.append(max(got, 0))
    return out


def _uniform_prefix(b: int, s: int) -> list[int]:
    return [s * (i + 1) for i in range(max(b, 1))]


def dtype_of(c: Case, name: str, main: int) -> int:
    """The dtype the host will be handed for this input.

    Every exit has to agree on this, so it lives in one place. It did not,
    once: the line special-cased the slope vector and the static environment
    did not, which made the derivation reason about a pse dtype no run ever
    used.
    """
    # The alibi slope vector is checked against FLOAT on its own, so it does
    # not follow query's dtype the way a normal pse tensor does.
    if name == "pse_shift" and c.pse_shape.startswith("slope"):
        return DT["FLOAT"]
    return FIXED_DT.get(name, main)


def shapes(c: Case) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Tensor shapes for the case, following the host's layout handling."""
    n1, d, dv = c.n1, c.d, c.dv
    ins: dict[str, list[int]] = {}

    if c.layout == "SBH":
        ins["query"] = [c.s1, c.b, n1 * d]
        ins["key"] = [c.s2, c.b, c.n2 * d]
        ins["value"] = [c.s2, c.b, c.n2 * dv]
        ins["dy"] = [c.s1, c.b, n1 * dv]
    elif c.layout == "BSH":
        ins["query"] = [c.b, c.s1, n1 * d]
        ins["key"] = [c.b, c.s2, c.n2 * d]
        ins["value"] = [c.b, c.s2, c.n2 * dv]
        ins["dy"] = [c.b, c.s1, n1 * dv]
    elif c.layout == "BNSD":
        ins["query"] = [c.b, n1, c.s1, d]
        ins["key"] = [c.b, c.n2, c.s2, d]
        ins["value"] = [c.b, c.n2, c.s2, dv]
        ins["dy"] = [c.b, n1, c.s1, dv]
    elif c.layout == "TND":
        t1 = (c.seq_q or [0])[-1]
        t2 = (c.seq_kv or [0])[-1]
        ins["query"] = [t1, n1, d]
        ins["key"] = [t2, c.n2, d]
        ins["value"] = [t2, c.n2, dv]
        ins["dy"] = [t1, n1, dv]
    else:  # BSND
        ins["query"] = [c.b, c.s1, n1, d]
        ins["key"] = [c.b, c.s2, c.n2, d]
        ins["value"] = [c.b, c.s2, c.n2, dv]
        ins["dy"] = [c.b, c.s1, n1, dv]

    if c.layout == "TND":
        t1 = (c.seq_q or [0])[-1]
        ins["softmax_max"] = [t1, n1, 8]
        ins["softmax_sum"] = [t1, n1, 8]
    else:
        ins["softmax_max"] = [c.b, n1, c.s1, 8]
        ins["softmax_sum"] = [c.b, n1, c.s1, 8]
    # attention_in is the forward output, so it carries value's D, not query's.
    # Giving it query's shape makes every D1 != D case fail a consistency check.
    ins["attention_in"] = list(ins["dy"])

    # The host reads the mask's rank and leading dims to classify it, so the
    # shape variants are separate cases rather than cosmetic.
    mask_shapes = {
        "ss": [c.s1, c.s2],
        "2048": [2048, 2048],
        "bnss": [c.b, n1, c.s1, c.s2],
        "b1ss": [c.b, 1, c.s1, c.s2],
        "11ss": [1, 1, c.s1, c.s2],
    }
    if c.atten_mask not in ATTEN_MASKS:
        raise ValueError(
            f"{c.atten_mask!r} is not a mask shape; expected one of "
            f"{ATTEN_MASKS}. Dropping it silently produced a case with no "
            f"mask at all, under a name saying it had one.")
    if c.atten_mask in mask_shapes:
        ins["atten_mask"] = mask_shapes[c.atten_mask]

    if c.prefix_n:
        ins["prefix"] = [len(c.prefix_n)]
    # The sequence tensors are passed like any other, and the host reads their
    # rank and dtype before it reads their contents. Leaving them out here
    # made every exit that works off these shapes call them absent.
    if c.seq_q:
        ins["actual_seq_qlen"] = [len(c.seq_q)]
    if c.seq_kv:
        ins["actual_seq_kvlen"] = [len(c.seq_kv)]
    if c.pse:
        # The five shapes CheckPseShape accepts, named after the classification
        # it assigns. The alibi pair carries a literal 1024 rather than s1, and
        # TND accepts nothing else.
        pse_shapes = {
            "bnss": [c.b, n1, c.s1, c.s2],
            "b1ss": [c.b, n1, 1, c.s2],
            "1nss": [1, n1, c.s1, c.s2],
            "1nhs": [1, n1, PSE_ALIBI_S, c.s2],
            "bnhs": [c.b, n1, PSE_ALIBI_S, c.s2],
            # Rank 2: the alibi slope vector, checked on its own path rather
            # than by CheckPseShape. It is the only pse TND accepts with no mask.
            "slope": [c.b, n1],
            "slope_n": [n1],
        }
        if c.pse_shape not in pse_shapes:
            raise ValueError(
                f"{c.pse_shape!r} is not a pse shape; expected one of "
                f"{PSE_SHAPES}. Falling back to bnss made every case naming "
                f"an unknown shape a duplicate of one that already ran.")
        ins["pse_shift"] = pse_shapes[c.pse_shape]
    if c.rope:
        rope_shape = {
            "SBH": [c.s1, c.b, n1 * ROPE_D],
            "BSH": [c.b, c.s1, n1 * ROPE_D],
            "BNSD": [c.b, n1, c.s1, ROPE_D],
            "BSND": [c.b, c.s1, n1, ROPE_D],
            "TND": [(c.seq_q or [0])[-1], n1, ROPE_D],
        }[c.layout]
        k_rope = {
            "SBH": [c.s2, c.b, c.n2 * ROPE_D],
            "BSH": [c.b, c.s2, c.n2 * ROPE_D],
            "BNSD": [c.b, c.n2, c.s2, ROPE_D],
            "BSND": [c.b, c.s2, c.n2, ROPE_D],
            "TND": [(c.seq_kv or [0])[-1], c.n2, ROPE_D],
        }[c.layout]
        ins["queryRope"] = rope_shape
        ins["keyRope"] = k_rope

    outs: dict[str, list[int]] = {
        "dq": list(ins["query"]),
        "dk": list(ins["key"]),
        "dv": list(ins["value"]),
    }
    if c.rope:
        outs["dq_rope"] = list(ins["queryRope"])
        outs["dk_rope"] = list(ins["keyRope"])
    return ins, outs


# Temporary alias: callers still saying `_shapes` keep working while imports
# migrate. Remove once every site uses `shapes`.
_shapes = shapes


def describe(c: Case) -> dict:
    """Flat record of what defines the case, for the wide output table."""
    c = c.normalised()
    lens_q, lens_kv = c.lens_q, c.lens_kv
    return {
        "layout": c.layout,
        "dtype": c.dtype,
        "b": c.b,
        "s1": c.s1,
        "s2": c.s2,
        "n2": c.n2,
        "g": c.g,
        "d": c.d,
        "d1": c.dv,
        "atten_mask": c.atten_mask,
        "pse": int(c.pse),
        "pse_shape": c.pse_shape if c.pse else "",
        "pse_type": c.pse_type,
        "rope": int(c.rope),
        "keep_prob": c.keep_prob,
        "sparse_mode": c.sparse_mode,
        "pre_tokens": c.pre_tokens,
        "next_tokens": c.next_tokens,
        "inner_precise": c.inner_precise,
        "out_dtype": c.out_dtype,
        "deterministic": c.deterministic,
        "seq_q": "/".join(str(v) for v in (c.seq_q or [])),
        "seq_kv": "/".join(str(v) for v in (c.seq_kv or [])),
        "prefix_n": "/".join(str(v) for v in (c.prefix_n or [])),
        # The properties the TND branch derives from the vector and nothing else.
        "all_same": int(bool(lens_q) and len(set(lens_q)) == 1 and len(set(lens_kv)) == 1),
        "s1s2_same": int(lens_q == lens_kv),
        "seq_has_zero": int(any(v == 0 for v in lens_q + lens_kv)),
        "tag": c.tag,
    }


class FagInputSemantics:
    """The InputSemantics answer for this operator."""

    @property
    def in_order(self):
        return IN_ORDER

    @property
    def out_order(self):
        return OUT_ORDER

    def shapes(self, case: Case):
        return shapes(case.normalised())

    def dtype_of(self, case: Case, name: str, main: int) -> int:
        return dtype_of(case, name, main)

    def normalize(self, case: Case) -> Case:
        return case.normalised()

    def describe(self, case: Case) -> dict:
        return describe(case)

    def enums(self) -> dict:
        return {
            "layout": LAYOUTS,
            "dtype": tuple(DT),
            "atten_mask": ATTEN_MASKS,
            "pse_shape": PSE_SHAPES,
        }

    def knob_schema(self) -> dict:
        return {
            "layout": {"kind": "categorical", "domain": list(LAYOUTS), "mutable": True},
            "dtype": {"kind": "categorical", "domain": ["FLOAT16", "BF16", "FLOAT"], "mutable": True},
            "b": {"kind": "numeric", "mutable": True, "default": 1},
            "s1": {"kind": "numeric", "mutable": True, "default": 128},
            "s2": {"kind": "numeric", "mutable": True, "default": 128},
            "n2": {"kind": "numeric", "mutable": True, "default": 1},
            "g": {"kind": "numeric", "mutable": True, "default": 1},
            "d": {"kind": "numeric", "mutable": True, "default": 128},
            "d1": {"kind": "numeric", "mutable": True, "default": None},
            "atten_mask": {"kind": "categorical", "domain": list(ATTEN_MASKS), "mutable": True},
            "pse": {"kind": "bool", "mutable": True, "default": False},
            "pse_shape": {"kind": "categorical", "domain": list(PSE_SHAPES), "mutable": True},
            "pse_type": {"kind": "numeric", "mutable": True, "default": 1},
            "rope": {"kind": "bool", "mutable": True, "default": False},
            "keep_prob": {"kind": "numeric", "mutable": True, "default": 1.0},
            "sparse_mode": {"kind": "numeric", "mutable": True, "default": 0},
            "pre_tokens": {"kind": "numeric", "mutable": True, "default": 65536},
            "next_tokens": {"kind": "numeric", "mutable": True, "default": 65536},
            "out_dtype": {"kind": "numeric", "mutable": True, "default": 0},
            "deterministic": {"kind": "numeric", "mutable": True, "default": 0},
            "seq_q": {"kind": "sequence", "mutable": False, "default": None},
            "seq_kv": {"kind": "sequence", "mutable": False, "default": None},
            "prefix_n": {"kind": "sequence", "mutable": False, "default": None},
        }

    def from_knobs(self, knobs: dict) -> Case:
        schema = self.knob_schema()
        payload = {}
        for name, meta in schema.items():
            if name in knobs:
                payload[name] = knobs[name]
            elif "default" in meta:
                payload[name] = meta["default"]
        return Case(**payload)

    def knobs_of(self, case: Case) -> dict:
        return describe(case)

    def repair(self, case: Case) -> Case:
        return case.normalised()


SEMANTICS = FagInputSemantics()
