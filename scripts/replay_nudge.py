# -*- coding: utf-8 -*-
"""Take a witness and push exactly one dimension toward an unreached key.

89% of the keys in U - R sit one dimension away from something already
produced. Random mutation never lands on them because it moves several inputs
at once and drifts off the ledge it is standing on. This walks the other way:
start from the witness's exact inputs, change only what feeds the one dimension
that differs, and keep everything else fixed.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import inputs as I  # noqa: E402
from replay import runner as R  # noqa: E402

#: How to move a dimension, given the value we want it to take. Only the ones
#: with a direct input knob; SplitAxis, IsNzOut and IsBn2MultiBlk are decided
#: by the tiling's own arithmetic and need a different tactic.
D_LADDER = [64, 72, 96, 128, 192, 256, 512, 768]


def _variants(c: I.Case, dim: str, want: str) -> list[I.Case]:
    if dim == "IsPse":
        if want == "1":
            return [replace(c, pse=True, pse_shape=s)
                    for s in ("full", "bnss", "b1ss", "1nss", "slope_bn", "slope_n")]
        return [replace(c, pse=False)]
    if dim == "IsDrop":
        return [replace(c, keep_prob=0.5 if want == "1" else 1.0)]
    if dim == "IsRope":
        return ([replace(c, rope=True, d=192, d1=None)] if want == "1"
                else [replace(c, rope=False)])
    if dim == "IsAttenMask":
        return ([replace(c, atten_mask=m) for m in ("ss", "bss", "b1ss", "1sss")]
                if want == "1" else [replace(c, atten_mask="none")])
    if dim == "IsTnd":
        if want == "1":
            n = max(1, c.b)
            return [replace(c, layout="TND",
                            seq_q=[c.s1] * n, seq_kv=[c.s2] * n),
                    replace(c, layout="TND",
                            seq_q=[c.s1] * n,
                            seq_kv=[max(1, c.s2 // 2)] * n)]
        return [replace(c, layout=lay, seq_q=None, seq_kv=None)
                for lay in ("BSND", "BNSD", "BSH", "SBH")]
    if dim == "DTemplateNum":
        want_i = int(want)
        # The template is a ceiling over D, so the value just under the step
        # and the step itself both land in the same bucket.
        lo = max([x for x in D_LADDER if x < want_i], default=0)
        return [replace(c, d=v, d1=None if (c.d1 or c.d) >= v else c.d1)
                for v in {want_i, max(1, want_i - 1), lo + 1} if v > 0]
    if dim == "IsDNoEqual":
        if want == "1":
            return [replace(c, d1=v) for v in (16, 32, 64, 96, 128)
                    if v < (c.d or 128)]
        return [replace(c, d1=None)]
    if dim == "S1TemplateNum":
        want_i = int(want)
        return [replace(c, s1=v) for v in
                (want_i, want_i - 1, want_i + 1, want_i * 2, want_i * 4)
                if v > 0]
    if dim == "S2TemplateNum":
        want_i = int(want)
        return [replace(c, s2=v) for v in
                (want_i, want_i - 1, want_i * 2, want_i * 4) if v > 0]
    if dim == "InputDType":
        code = {"1": "FLOAT", "2": "BF16", "3": "FLOAT16"}.get(want)
        return [replace(c, dtype=code)] if code else []
    if dim == "OutDType":
        return [replace(c, out_dtype=int(want))]
    if dim == "DeterType":
        return [replace(c, deterministic=1, sparse_mode=m) for m in (0, 2, 3, 5)]
    return []


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    queue = R.CACHE / "open_key_queue.csv"
    lines = queue.read_text(encoding="utf-8").splitlines()[1:]

    wide: dict[str, dict] = {}
    for p in sorted(R.CACHE.glob("fag_key_cases*.csv")):
        rows = p.read_text(encoding="utf-8").splitlines()
        head = rows[0].split(",")
        for line in rows[1:]:
            f = line.split(",")
            if len(f) == len(head):
                wide.setdefault(f[0], dict(zip(head, f)))

    cases: dict[str, I.Case] = {}
    targets: dict[int, str] = {}
    skipped: Counter = Counter()
    for line in lines:
        key_s, dist, dims, _, wcase = line.split(",")[:5]
        if dist != "1":
            continue
        row = wide.get(wcase)
        if row is None:
            skipped["witness row missing"] += 1
            continue
        dim = dims
        want = str(R.SCHEMA.decode_tiling_key(int(key_s))[dim])
        # Older runs predate some columns, so every read carries a default.
        def s(name, dflt=""):
            v = row.get(name, dflt)
            return dflt if v in ("", "None") else v

        base = I.Case(
            layout=s("layout", "BSND"), dtype=s("dtype", "FLOAT16"),
            b=int(s("b", 1)), s1=int(s("s1", 128)), s2=int(s("s2", 128)),
            n2=int(s("n2", 1)), g=int(s("g", 1)), d=int(s("d", 128)),
            d1=int(s("d1")) if s("d1") else None,
            atten_mask=s("atten_mask", "none"), pse=s("pse", "0") == "1",
            pse_shape=s("pse_shape", "full"),
            pse_type=int(s("pse_type", 1)), rope=s("rope", "0") == "1",
            keep_prob=float(s("keep_prob", 1.0)),
            sparse_mode=int(s("sparse_mode", 0)),
            pre_tokens=int(s("pre_tokens", 65536)),
            next_tokens=int(s("next_tokens", 65536)),
            out_dtype=int(s("out_dtype", 0)),
            deterministic=int(s("deterministic", 0)),
            seq_q=[int(x) for x in s("seq_q").split("/") if x] or None,
            seq_kv=[int(x) for x in s("seq_kv").split("/") if x] or None,
        )
        vs = _variants(base, dim, want)
        if not vs:
            skipped[f"no knob for {dim}"] += 1
            continue
        targets[int(key_s)] = dim
        for j, v in enumerate(vs):
            cases[f"n{key_s[-9:]}_{j}"] = v
        if limit and len(targets) >= limit:
            break

    print(f"{len(targets)} target keys, {len(cases)} probe cases")
    for why, n in skipped.most_common():
        print(f"  skipped {n}: {why}")

    found: dict[int, str] = {}
    other: set[int] = set()
    items = list(cases.items())
    for i in range(0, len(items), 2000):
        chunk = dict(items[i:i + 2000])
        res = R.run(chunk, tag=f"nudge{i}")
        for cid, r in res.items():
            if not r.ok:
                continue
            if r.key in targets and r.key not in found:
                found[r.key] = cid
            else:
                other.add(r.key)
        print(f"  batch {i // 2000}: {len(found)}/{len(targets)} targets hit")

    print(f"\nhit {len(found)} of {len(targets)} targeted keys "
          f"({len(found) / max(1, len(targets)) * 100:.0f}%)")
    by_dim: Counter = Counter()
    miss: Counter = Counter()
    for k, dim in targets.items():
        (by_dim if k in found else miss)[dim] += 1
    print("\n  hit by dimension:")
    for d in sorted(set(by_dim) | set(miss)):
        print(f"    {d:<16} {by_dim[d]:>4} hit, {miss[d]:>4} missed")

    if found:
        out = R.CACHE / "nudge_hits.csv"
        with out.open("w", encoding="utf-8") as f:
            f.write("tiling_key,case_id,dimension\n")
            for k, cid in found.items():
                f.write(f"{k},{cid},{targets[k]}\n")
        print(f"\nhits -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
