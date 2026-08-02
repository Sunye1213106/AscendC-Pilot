# -*- coding: utf-8 -*-
"""Build FlashAttentionScoreGrad inputs that the host tiling will accept.

The tiling rejects inconsistent shapes before it ever computes a key, so a
sampler that emits raw dimension tuples wastes most of its budget. This module
holds the layout-to-shape mapping the host applies, so a case is described by
what actually drives tiling (B, S1, S2, N2, G, D) and the tensor shapes are
derived from it.

TND is the reason this file exists. There, B and S are absent from every shape:
B is the length of the actual_seq_qlen tensor and the per-batch lengths are the
first differences of its contents, which are a prefix sum. A whole family of
tiling decisions keys off properties of that vector -- all-equal lengths, a zero
somewhere, EOD trailing zeros -- and no amount of reshaping can reach them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

LAYOUTS = ("SBH", "BSH", "BNSD", "BSND", "TND")

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
    pse_shape: str = "full"        # full | 1n | b1 | slope
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


def _shapes(c: Case) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
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
    if c.atten_mask in mask_shapes:
        ins["atten_mask"] = mask_shapes[c.atten_mask]

    if c.prefix_n:
        ins["prefix"] = [len(c.prefix_n)]
    if c.pse:
        ins["pse_shift"] = {
            "full": [c.b, n1, c.s1, c.s2],
            "1n": [1, n1, c.s1, c.s2],
            "b1": [c.b, n1, 1, c.s2],
            "slope": [c.b, n1],
        }.get(c.pse_shape, [c.b, n1, c.s1, c.s2])
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


def to_csv_line(c: Case, case_id: str) -> str:
    """Render the case in the replay driver's input format."""
    c = c.normalised()
    ins, outs = _shapes(c)
    main = DT[c.dtype]

    in_shapes, in_dtypes = [], []
    for name in IN_ORDER:
        dims = ins.get(name, [])
        field_text = "|".join(str(x) for x in dims)
        if name == "actual_seq_qlen" and c.seq_q:
            field_text = f"{len(c.seq_q)}@" + "/".join(str(v) for v in c.seq_q)
        elif name == "actual_seq_kvlen" and c.seq_kv:
            field_text = f"{len(c.seq_kv)}@" + "/".join(str(v) for v in c.seq_kv)
        elif name == "prefix" and c.prefix_n:
            field_text = f"{len(c.prefix_n)}@" + "/".join(str(v) for v in c.prefix_n)
        in_shapes.append(field_text)
        in_dtypes.append(str(FIXED_DT.get(name, main)))

    out_shapes = ["|".join(str(x) for x in outs.get(n, [])) for n in OUT_ORDER]
    out_dtypes = [str(main)] * len(OUT_ORDER)

    attrs = [
        ("scale_value", "f", f"{1.0 / (c.d ** 0.5):.8f}"),
        ("keep_prob", "f", f"{c.keep_prob}"),
        ("pre_tockens", "i", str(c.pre_tokens)),
        ("next_tockens", "i", str(c.next_tokens)),
        ("head_num", "i", str(c.n1)),
        ("input_layout", "s", c.layout),
        ("inner_precise", "i", str(c.inner_precise)),
        ("sparse_mode", "i", str(c.sparse_mode)),
        ("pse_type", "i", str(c.pse_type)),
        ("seed", "i", "2"),
        ("offset", "i", "0"),
        ("out_dtype", "i", str(c.out_dtype)),
        ("softmax_in_layout", "s", ""),
    ]
    return ";".join([
        case_id,
        ",".join(in_shapes),
        ",".join(in_dtypes),
        ",".join(out_shapes),
        ",".join(out_dtypes),
        "&".join(f"{k}={kind}:{v}" for k, kind, v in attrs),
        # Deterministic mode is read off the context, not from the attrs.
        str(c.deterministic),
    ])


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
        "out_dtype": c.out_dtype,
        "deterministic": c.deterministic,
        "seq_q": "/".join(str(v) for v in (c.seq_q or [])),
        "seq_kv": "/".join(str(v) for v in (c.seq_kv or [])),
        # The properties the TND branch derives from the vector and nothing else.
        "all_same": int(bool(lens_q) and len(set(lens_q)) == 1 and len(set(lens_kv)) == 1),
        "s1s2_same": int(lens_q == lens_kv),
        "seq_has_zero": int(any(v == 0 for v in lens_q + lens_kv)),
        "tag": c.tag,
    }
