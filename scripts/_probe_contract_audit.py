# -*- coding: utf-8 -*-
"""E2 的验收: 生成器的几个出口到底还认不认同一个用例。

一个用例出生成器有四个门 —— 喂给 host 的那行 CSV、喂给求解器的静态 env、写进
宽表的那一行、以及从那一行重建回来的 Case。四份代码手写，共用一个脑子里的模型,
谁先学会一件新事谁就先漂走。漂走了不报错: host 照跑, 求解器照答, 只是它们答的
不是同一个问题, 而每一条静态结论都建立在「env 描述的就是跑的那个」上。

这个脚本先建门, 再让门自己把已经漂掉的地方喊出来。所以它现在**预期是红的**;
先看清楚有多少条、都是什么类, 再决定哪条改哪边。

    python scripts/_probe_contract_audit.py
    python scripts/_probe_contract_audit.py --corpus --limit 3000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: How many offenders of each kind to print. The counts are the finding; the
#: examples are only there to make each count actionable.
SHOW = 3


def synthetic_cases():
    """Cases chosen to walk every closed field, not to be realistic.

    A random sample says nothing about the values it happened to miss, and the
    fields that drift are exactly the rare ones -- the slope pse, the prefix
    tensor, the layout with no B in any shape.
    """
    from replay.inputs import ATTEN_MASKS, DT, LAYOUTS, PSE_SHAPES, Case

    out = []
    for layout in LAYOUTS:
        for mask in ATTEN_MASKS:
            out.append(Case(layout=layout, atten_mask=mask,
                            tag=f"mask-{layout}-{mask}"))
        for shape in PSE_SHAPES:
            out.append(Case(layout=layout, pse=True, pse_shape=shape,
                            tag=f"pse-{layout}-{shape}"))
        out.append(Case(layout=layout, rope=True, tag=f"rope-{layout}"))
        out.append(Case(layout=layout, d=128, d1=64, tag=f"d1-{layout}"))
    for dtype in DT:
        out.append(Case(dtype=dtype, tag=f"dt-{dtype}"))
    for mode in range(7):
        out.append(Case(sparse_mode=mode, tag=f"sparse-{mode}"))
    for inner in (0, 1):
        out.append(Case(inner_precise=inner, tag=f"inner-{inner}"))
    for det in (0, 1):
        out.append(Case(deterministic=det, tag=f"det-{det}"))
    out.append(Case(layout="TND", seq_q=[128, 256, 384], seq_kv=[128, 256, 384],
                    tag="tnd-even"))
    out.append(Case(layout="TND", seq_q=[64, 256, 384], seq_kv=[128, 256, 300],
                    tag="tnd-ragged"))
    out.append(Case(layout="TND", seq_q=[0, 128], seq_kv=[0, 128],
                    tag="tnd-zero"))
    out.append(Case(keep_prob=0.9, tag="dropout"))
    out.append(Case(pse=True, pse_shape="slope", pse_type=2, tag="slope-alibi"))
    # A prefix the case names rather than one `normalised` invents: the two
    # are indistinguishable unless the value differs from s2/2.
    out.append(Case(b=3, sparse_mode=5, prefix_n=[7, 11, 13], tag="prefix-own"))
    out.append(Case(b=2, sparse_mode=6, prefix_n=[0], tag="prefix-zero"))
    for pse_type in (0, 1, 2, 3):
        out.append(Case(pse=True, pse_type=pse_type, tag=f"psetype-{pse_type}"))
    for out_dtype in (0, 1, 2, 3):
        out.append(Case(out_dtype=out_dtype, tag=f"outdt-{out_dtype}"))
    out.append(Case(pre_tokens=64, next_tokens=0, tag="tokens-band"))
    out.append(Case(n2=4, g=3, tag="gqa"))
    return out


def corpus_cases(limit: int, timeout: float):
    """Cases that actually ran, so the audit covers what the run recorded."""
    from replay import corpus

    samples, scan = corpus.scan(limit=limit, timeout=timeout)
    print(scan.report(), flush=True)
    return [s.case for s in samples]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", action="store_true",
                    help="audit recorded cases instead of synthetic ones")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--show", type=int, default=SHOW)
    args = ap.parse_args()

    from replay.contract_audit import audit_many
    from replay.surfaces import fag

    t0 = time.time()
    cases = corpus_cases(args.limit, args.timeout) if args.corpus \
        else synthetic_cases()
    report = audit_many(cases, fag())
    print(f"\n{report.summary()}  ({time.time() - t0:.1f}s)\n")

    for kind, items in sorted(report.by_kind().items(),
                              key=lambda kv: -len(kv[1])):
        wheres = sorted({v.where for v in items})
        print(f"{kind}: {len(items)} over {len(wheres)} fields")
        print(f"    fields: {', '.join(wheres[:12])}"
              + (" ..." if len(wheres) > 12 else ""))
        for v in items[:args.show]:
            print(f"    e.g. {v}")
        print()

    return 0 if report.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
