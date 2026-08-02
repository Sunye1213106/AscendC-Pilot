# -*- coding: utf-8 -*-
"""Coverage-guided search for reachable tiling keys.

The search treats "produced a key, or a dimension value, we had not seen" as the
novelty signal, keeps those inputs, and mutates around them. That is the fuzzer
idea without the fuzzer: tiling is pure computation and a case costs microseconds,
so the budget goes into proposing inputs rather than into instrumentation.

Seeds are structured rather than random. Every dimension whose value is directly
settable from an input (dtype, layout, mask presence, rope, deterministic) is
enumerated, and the sizes are placed on the thresholds the tiling compares
against, so the first batch already spans most of the space.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from . import inputs as I
from .runner import DIM_NAMES, Result

DTYPES = ["FLOAT", "FLOAT16", "BF16", "HIFLOAT8", "FLOAT8_E4M3FN", "FLOAT8_E5M2"]

#: Sizes chosen to straddle the constants the tiling branches on.
S_STEPS = [64, 128, 256, 512, 1024, 2048, 4096]
D_STEPS = [64, 72, 96, 128, 192, 256]
#: value's D. Reaching DTemplateNum=64 together with IsDNoEqual=1 needs a D1
#: below 64, which the query-side ladder never produces.
D1_STEPS = [16, 32, 48, 64, 72, 96, 128, 192, 256, 320]
B_STEPS = [1, 2, 8, 24, 48]
NG_STEPS = [(1, 1), (2, 1), (1, 2), (4, 1), (8, 1), (2, 2)]
#: The host classifies the mask by rank and leading dims, so shape is a knob.
MASKS = ["none", "ss", "2048", "bnss", "b1ss", "11ss"]
#: The four-dimension names CheckPseShape classifies into, plus the rank-2
#: alibi slope forms, which take a different path and are the only pse TND
#: accepts without an atten mask.
PSE_SHAPES = ["bnss", "b1ss", "1nss", "1nhs", "bnhs", "slope", "slope_n"]


def seeds() -> dict[str, I.Case]:
    """Structured first batch: one axis varied at a time over a few bases."""
    out: dict[str, I.Case] = {}

    def add(prefix: str, c: I.Case) -> None:
        out[f"{prefix}{len(out)}"] = c

    bases = [
        I.Case(layout="BSND", dtype="FLOAT16", b=2, s1=1024, s2=1024, n2=2, g=1, d=128),
        I.Case(layout="BNSD", dtype="BF16", b=1, s1=256, s2=256, n2=1, g=1, d=128),
        I.Case(layout="SBH", dtype="FLOAT", b=1, s1=256, s2=256, n2=1, g=1, d=128),
        I.Case(layout="BSH", dtype="FLOAT16", b=4, s1=512, s2=512, n2=2, g=2, d=64),
        I.Case(layout="TND", dtype="FLOAT16", n2=2, g=1, d=128, sparse_mode=4,
               seq_q=_prefix([1024, 768, 2048]), seq_kv=_prefix([1024, 768, 2048])),
    ]

    # Every layout crossed with every dtype: these two drive four dimensions
    # between them and cost nothing to enumerate.
    for layout in I.LAYOUTS:
        for dt in DTYPES:
            base = next(b for b in bases if b.layout == layout)
            add("dt", _with(base, dtype=dt, tag=f"{layout}/{dt}"))

    # Size ladders, one axis at a time, for the three template-number dims.
    for base in bases:
        for s in S_STEPS:
            add("s1", _resize(base, s1=s, tag=f"s1={s}"))
            add("s2", _resize(base, s2=s, tag=f"s2={s}"))
        for d in D_STEPS:
            add("d", _with(base, d=d, tag=f"d={d}"))
        # value's D drives IsDNoEqual, but the host requires D1 <= D, so the
        # pairs have to be generated that way round or they are all rejected.
        for d in (64, 96, 128, 192, 256, 512):
            for d1 in D1_STEPS:
                if d1 < d:
                    add("dv", _with(base, d=d, d1=d1, tag=f"d={d},d1={d1}"))
        for b in B_STEPS:
            add("b", _resize(base, b=b, tag=f"b={b}"))
        for n2, g in NG_STEPS:
            add("ng", _with(base, n2=n2, g=g, tag=f"n2={n2},g={g}"))

    # Boolean switches, flipped over every base.
    for base in bases:
        for m in MASKS[1:]:
            add("mask", _with(base, atten_mask=m, tag=f"mask={m}"))
        for shape in PSE_SHAPES:
            for pt in (0, 1, 2, 3):
                add("pse", _with(base, pse=True, pse_shape=shape, pse_type=pt,
                                 tag=f"pse={shape},type={pt}"))
        add("drop", _with(base, keep_prob=0.9, tag="drop"))
        add("rope", _with(base, rope=True, tag="rope"))
        add("det", _with(base, deterministic=1, tag="det"))
        add("odt", _with(base, out_dtype=1, tag="out_dtype=1"))
        for sm in (0, 1, 2, 3, 4, 6):
            for m in ("2048", "bnss", "11ss"):
                add("sp", _with(base, sparse_mode=sm, pre_tokens=128,
                                next_tokens=0, atten_mask=m,
                                tag=f"sparse={sm},mask={m}"))

    # Deterministic crossed with sparsity: DeterType has five values and they
    # come from that pairing rather than from the flag alone.
    for base in bases:
        for sm in (0, 2, 3, 4):
            add("dsp", _with(base, deterministic=1, sparse_mode=sm,
                             atten_mask="2048", pre_tokens=128, next_tokens=0,
                             tag=f"det,sparse={sm}"))

    out.update(tnd_seeds())
    out.update(targeted_seeds())
    return out


def targeted_seeds() -> dict[str, I.Case]:
    """Cases aimed at dimension values the broad sweep does not reach.

    Each group below encodes a condition read out of the tiling source, so a
    miss here is informative: it means the condition as written cannot be met
    from the inputs, not that the search was unlucky.
    """
    out: dict[str, I.Case] = {}

    def add(name: str, c: I.Case) -> None:
        out[f"tg{len(out)}"] = _with(c, tag=name)

    # DTemplateNum=768 needs D above 256; with DT_FLOAT the same case also
    # takes the only non-quantised path to S1TemplateNum=64.
    for d in (320, 384, 512, 768):
        for dt in ("FLOAT", "FLOAT16", "BF16"):
            add(f"bigD d={d} {dt}",
                I.Case(layout="BSND", dtype=dt, b=1, s1=256, s2=256, n2=1, g=1, d=d))
            add(f"bigD_bnsd d={d} {dt}",
                I.Case(layout="BNSD", dtype=dt, b=1, s1=128, s2=128, n2=1, g=1, d=d))

    # DeterType=1 (DETER_OLD) is the fallthrough: deterministic on, but the
    # sparse mode is none of the ones with a dedicated deterministic path.
    for sm in (5, 6, 7, 8):
        for mask in ("2048", "ss", "none"):
            add(f"deterOld sparse={sm} mask={mask}",
                I.Case(layout="BSND", dtype="FLOAT16", b=2, s1=1024, s2=1024,
                       n2=2, g=1, d=128, deterministic=1, sparse_mode=sm,
                       atten_mask=mask, pre_tokens=128, next_tokens=0))

    # IsNzOut wants 64 < D < 128 with D not a multiple of 16, a non-float
    # non-quantised dtype, both S at least 2048, and the swizzle enabled --
    # which in turn needs the data to spill L2 and blockOuter to hit aicNum.
    for d in (72, 88, 104, 120):
        for dt in ("FLOAT16", "BF16"):
            for b, n2, s in ((2, 8, 4096), (4, 8, 2048), (1, 16, 4096), (8, 4, 2048)):
                add(f"nzout d={d} {dt} b={b} n2={n2} s={s}",
                    I.Case(layout="BSND", dtype=dt, b=b, s1=s, s2=s, n2=n2, g=1, d=d))

    # DeterType=1 (DETER_OLD) also needs isSparse, which for the prefix modes
    # means a valid per-batch prefix vector rather than just the attr.
    for sm in (5, 6):
        for b in (1, 2, 4, 8):
            for pf in (0, 128, 512):
                add(f"deterOldPrefix sparse={sm} b={b} prefix={pf}",
                    I.Case(layout="BSND", dtype="FLOAT16", b=b, s1=1024, s2=1024,
                           n2=2, g=1, d=128, deterministic=1, sparse_mode=sm,
                           atten_mask="2048", pre_tokens=128, next_tokens=0,
                           prefix_n=[pf]))

    # IsTndSwizzle: TND, not deterministic, the BN2S2 split, S1 over 2048 (or
    # over 1024 when S2 exceeds 128), fewer than 129 batches, no zero-length
    # sequence and no EOD tail. The catch is that enableSwizzle also needs the
    # data to spill L2, and reaching that by adding batches pushes b past 129 --
    # so the volume has to come from long sequences and many heads instead.
    for nb in (2, 4, 8, 16, 32, 64, 96, 128):
        for slen in (4096, 8192, 16384):
            for n2 in (4, 8, 16):
                lens = [slen - (i % 2) * 128 for i in range(nb)]
                add(f"tndbig b={nb} s={slen} n2={n2}",
                    I.Case(layout="TND", dtype="FLOAT16", n2=n2, g=1, d=128,
                           seq_q=_prefix(lens), seq_kv=_prefix(lens)))

    for nb, s1, s2 in ((4, 4096, 4096), (8, 2048, 2048), (16, 2048, 512),
                       (32, 2048, 2048), (64, 1024, 512), (8, 4096, 1024),
                       (128, 2048, 2048), (2, 8192, 8192)):
        lens_q = [s1 - (i % 2) * 128 for i in range(nb)]
        lens_kv = [s2 - (i % 2) * 128 for i in range(nb)]
        for sm in (0, 2, 3, 4):
            for dt in ("FLOAT16", "BF16"):
                add(f"tndswz b={nb} s1={s1} s2={s2} sparse={sm} {dt}",
                    I.Case(layout="TND", dtype=dt, n2=2, g=1, d=128,
                           seq_q=_prefix(lens_q), seq_kv=_prefix(lens_kv),
                           sparse_mode=sm,
                           atten_mask="2048" if sm else "none",
                           pre_tokens=128 if sm else 65536,
                           next_tokens=0 if sm else 65536))
    return out


def tnd_seeds() -> dict[str, I.Case]:
    """TND cases aimed at the properties only the sequence vector can reach.

    Equal-length sequences are the trap here: the host silently rewrites such a
    TND case to BSND, so IsTnd comes back 0 unless the lengths differ or the
    sparse mode is high enough to block the rewrite.
    """
    out: dict[str, I.Case] = {}

    def add(name: str, lens_q, lens_kv, **kw) -> None:
        kw.setdefault("dtype", "FLOAT16")
        c = I.Case(layout="TND", n2=2, g=1, d=128,
                   seq_q=_prefix(lens_q), seq_kv=_prefix(lens_kv), tag=name, **kw)
        out[f"tnd{len(out)}"] = c

    add("all_same", [512, 512, 512], [512, 512, 512])
    add("all_same_sparse4", [512, 512, 512], [512, 512, 512], sparse_mode=4,
        pre_tokens=128, next_tokens=0)
    add("varied", [256, 1024, 512], [256, 1024, 512])
    add("q_ne_kv", [512, 1024, 256], [256, 512, 1024])
    add("s1_gt_s2", [1024, 2048, 1536], [256, 512, 384])
    add("s1_lt_s2", [256, 512, 384], [1024, 2048, 1536])
    add("has_zero", [512, 0, 1024], [512, 0, 1024])
    add("single_batch", [4096], [4096])
    add("big_s1_2048", [2048, 3072, 2560], [2048, 3072, 2560])
    add("big_s1_1024_s2gt128", [1024, 1536, 1280], [256, 512, 384])

    # b on both sides of the 129 cutoff that gates the swizzle path.
    for b in (2, 8, 64, 128, 129, 160):
        lens = [512 + (i % 5) * 128 for i in range(b)]
        add(f"b={b}", lens, lens)

    # Large totals, to push past L2 and turn on enableSwizzle.
    for n, s in ((8, 4096), (16, 4096), (32, 2048), (64, 2048)):
        lens = [s + (i % 3) * 256 for i in range(n)]
        add(f"large_{n}x{s}", lens, lens, sparse_mode=0)
        add(f"large_{n}x{s}_det", lens, lens, deterministic=1)

    # EOD: a negative step, then zeros, is how the host is told the batch ended.
    add("eod", [512, 1024, 0, 0], [512, 1024, 0, 0])

    for sm in (0, 2, 3, 4, 6):
        add(f"sparse={sm}", [1024, 2048, 1536], [1024, 2048, 1536],
            sparse_mode=sm, atten_mask="2048", pre_tokens=128, next_tokens=0)
    for dt in DTYPES:
        add(f"dtype={dt}", [1024, 2048, 1536], [1024, 2048, 1536], dtype=dt)
    return out


def _prefix(lens: list[int]) -> list[int]:
    """Cumulative sums, which is what the tensor actually carries."""
    out, run = [], 0
    for v in lens:
        run += v
        out.append(run)
    return out


def _with(base: I.Case, **kw) -> I.Case:
    from dataclasses import replace
    tag = kw.pop("tag", "")
    return replace(base, tag=f"{base.layout}:{tag}", **kw)


def _resize(base: I.Case, **kw) -> I.Case:
    """Resize a case, keeping TND's vector in step with the requested sizes."""
    from dataclasses import replace
    tag = kw.pop("tag", "")
    c = replace(base, tag=f"{base.layout}:{tag}", **kw)
    if c.layout == "TND":
        n = kw.get("b", len(base.seq_q or [1]))
        lens_q = [c.s1 - (i % 3) * 128 for i in range(n)]
        lens_kv = [c.s2 - (i % 3) * 128 for i in range(n)]
        c = replace(c, seq_q=_prefix(lens_q), seq_kv=_prefix(lens_kv))
    return c


def mutate(case: I.Case, rng: random.Random) -> I.Case:
    """One random step away from a case that proved interesting."""
    from dataclasses import replace
    c = case
    what = rng.choice(
        ["size", "dtype", "switch", "sparse", "heads", "d", "seq"]
        + (["seq", "seq"] if c.layout == "TND" else [])
    )
    if what == "size":
        c = _resize(c, s1=rng.choice(S_STEPS), s2=rng.choice(S_STEPS))
    elif what == "dtype":
        c = replace(c, dtype=rng.choice(DTYPES))
    elif what == "switch":
        c = replace(c, **rng.choice([
            {"atten_mask": rng.choice(MASKS)},
            {"pse": not c.pse, "pse_shape": rng.choice(PSE_SHAPES)},
            {"pse": True, "pse_shape": rng.choice(PSE_SHAPES),
             "pse_type": rng.choice([0, 1, 2, 3])},
            {"keep_prob": rng.choice([1.0, 0.9])},
            {"rope": not c.rope},
            {"deterministic": 1 - c.deterministic},
            {"out_dtype": rng.choice([0, 1, 2, 3])},
        ]))
    elif what == "sparse":
        c = replace(c, sparse_mode=rng.choice([0, 1, 2, 3, 4, 6]),
                    pre_tokens=rng.choice([0, 128, 1024, 65536]),
                    next_tokens=rng.choice([0, 128, 1024, 65536]))
    elif what == "heads":
        n2, g = rng.choice(NG_STEPS)
        c = replace(c, n2=n2, g=g)
    elif what == "d":
        d = rng.choice(D_STEPS + [320, 512])
        smaller = [x for x in D1_STEPS if x < d]
        c = replace(c, d=d,
                    d1=rng.choice([None] + smaller) if smaller else None)
    elif what == "seq" and c.layout == "TND":
        c = replace(c, seq_q=_mutate_seq(c.lens_q, rng),
                    seq_kv=_mutate_seq(c.lens_kv, rng))
    elif what == "seq":
        c = _resize(c, b=rng.choice(B_STEPS))
    return replace(c, tag=c.tag + "+mut")


def _mutate_seq(lens: list[int], rng: random.Random) -> list[int]:
    """Perturb the per-batch lengths, then hand back the prefix sum."""
    lens = list(lens) or [512]
    op = rng.choice(["scale", "jitter", "zero", "grow", "shrink", "equalise", "eod"])
    if op == "scale":
        f = rng.choice([0.5, 2, 4])
        lens = [max(int(v * f), 0) for v in lens]
    elif op == "jitter":
        i = rng.randrange(len(lens))
        lens[i] = max(lens[i] + rng.choice([-512, -128, 128, 512, 1024]), 0)
    elif op == "zero":
        lens[rng.randrange(len(lens))] = 0
    elif op == "grow":
        lens = lens + [rng.choice(S_STEPS) for _ in range(rng.randint(1, 8))]
    elif op == "shrink" and len(lens) > 1:
        lens = lens[: rng.randint(1, len(lens) - 1)]
    elif op == "equalise":
        lens = [lens[0]] * len(lens)
    elif op == "eod":
        cut = rng.randrange(len(lens))
        lens = lens[: cut + 1]
        return _prefix(lens) + [0] * rng.randint(1, 3)
    return _prefix(lens)


class Coverage:
    """What has been seen so far, and whether a result adds anything."""

    def __init__(self) -> None:
        self.keys: dict[int, str] = {}                       # key -> case id
        self.dim_values: dict[str, set] = defaultdict(set)   # dim -> values seen
        self.rejects: Counter = Counter()

    def offer(self, cid: str, r: Result) -> bool:
        """Record the result; True if it showed something new."""
        if not r.ok:
            self.rejects[_reject_kind(r.reject)] += 1
            return False
        fresh = False
        if r.key not in self.keys:
            self.keys[r.key] = cid
            fresh = True
        for name in DIM_NAMES:
            v = r.dims.get(name)
            if v is not None and v not in self.dim_values[name]:
                self.dim_values[name].add(v)
                fresh = True
        return fresh

    def missing(self, schema) -> dict[str, list]:
        """Declared values of each dimension that no case has produced."""
        out = {}
        for d in schema.dims:
            declared = {_norm(v) for v in d.value_domain}
            seen = {_norm(v) for v in self.dim_values[d.name]}
            gap = sorted(declared - seen, key=str)
            if gap:
                out[d.name] = gap
        return out


def _norm(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def _reject_kind(msg: str) -> str:
    if not msg:
        return "no message"
    for probe in ("must be", "should be", "not support", "invalid", "same"):
        if probe in msg:
            return msg[msg.find(probe):][:70]
    return msg[:70]
