# -*- coding: utf-8 -*-
"""Show what the UT parser actually extracted, before blaming the derivation.

A disagreement between derived and truth means either the derivation is wrong
or the inputs were mapped wrong. Printing the parse is how those get told apart.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _gt_compare import IN_ORDER, OUT_ORDER, UT, parse_cases  # noqa: E402


def main() -> int:
    cases = parse_cases(UT.read_text(encoding="utf-8", errors="replace"))
    for c in cases:
        tag = c["name"].rsplit("_", 1)[-1]
        ins, outs, at = c["inputs"], c["outputs"], c["attrs"]
        q = ins.get("query", {})
        print(f"\n=== case {tag} ===  tensors parsed: "
              f"{len(ins)} in / {len(outs)} out")
        print(f"  layout={at.get('input_layout')!r}  head_num={at.get('head_num')}  "
              f"keep_prob={at.get('keep_prob')}  sparse_mode={at.get('sparse_mode')}")
        print(f"  q shape={q.get('shape')} dtype={q.get('dtype')}")
        for n in ("key", "value", "atten_mask", "pse_shift", "drop_mask",
                  "actual_seq_qlen", "queryRope", "keyRope"):
            t = ins.get(n)
            if t is None:
                print(f"  {n:<16} <MISSING FROM PARSE>")
            elif t["shape"]:
                print(f"  {n:<16} {t['shape']} {t['dtype']}")
        empt = [n for n in IN_ORDER if ins.get(n) and not ins[n]["shape"]]
        print(f"  空输入: {empt}")
        outs_present = [n for n in OUT_ORDER if outs.get(n) and outs[n]["shape"]]
        print(f"  非空输出: {outs_present}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
