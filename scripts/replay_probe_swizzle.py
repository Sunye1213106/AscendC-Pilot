# -*- coding: utf-8 -*-
"""Hunt for the one dimension value the sweep never reached: IsTndSwizzle=1.

Its six preconditions pull against each other. Enabling the swizzle needs the
data to spill L2, which the sweep only achieved by piling on batches -- and past
128 batches the swizzle is switched off again. Sparse modes are no help either:
the exceed-L2 path marks them UNSUPPORTED. So the volume has to come from long
sequences, many heads or large D, at fewer than 129 batches and no sparsity.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import inputs as I
from replay import runner as R
from replay.search import _prefix


def main() -> int:
    cases: dict[str, I.Case] = {}
    for b in (32, 64, 96, 112, 120, 124, 127, 128):
        for slen in (1024, 1536, 2048, 3072, 4096):
            for n2, g, d in ((2, 1, 128), (4, 1, 128), (8, 1, 128), (2, 1, 192)):
                lens = [slen - (i % 5) * 128 for i in range(b)]
                cases[f"b{b}_s{slen}_n{n2}g{g}_d{d}"] = I.Case(
                    layout="TND", dtype="FLOAT16", n2=n2, g=g, d=d,
                    seq_q=_prefix(lens), seq_kv=_prefix(lens), sparse_mode=0)

    print(f"probing {len(cases)} cases")
    res = R.run(cases, tag="swz")

    hits, near = [], []
    for cid, r in res.items():
        if not r.ok:
            continue
        sw = r.diag.get("enableSwizzle")
        sp = r.logged.get("splitAxis")
        st = r.diag.get("sparseType")
        if str(r.dims.get("IsTndSwizzle")) == "1":
            hits.append((cid, r.key))
        elif sw == 1 or sp == 5:
            near.append((cid, sp, sw, st, r.diag.get("isExceedL2Cache")))

    print(f"\nIsTndSwizzle=1: {len(hits)} cases")
    for cid, key in hits[:10]:
        print(f"  {cid}  key={key}")
    if not hits:
        print("\nnear misses (split=5 or swizzle on):")
        for row in near[:25]:
            print(f"  {row[0]:<26} split={row[1]} swizzle={row[2]} "
                  f"sparseType={row[3]} exceedL2={row[4]}")
        ok = [r for r in res.values() if r.ok]
        print(f"\n{len(ok)}/{len(cases)} accepted; "
              f"exceedL2=1 in {sum(1 for r in ok if r.diag.get('isExceedL2Cache') == 1)}, "
              f"split=5 in {sum(1 for r in ok if r.logged.get('splitAxis') == 5)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
