# -*- coding: utf-8 -*-
"""Check the generated inputs are accepted and the log parsing lines up.

Before running a search worth thousands of cases it is worth knowing that a
hand-written case survives the host's shape checks and that the dimensions
decoded from the key agree with the ones the tiling logged. Disagreement there
would mean the decode is wrong and every later number is meaningless.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import inputs as I
from replay import runner as R

#: Field names as logged, paired with the TPL dimension they end up in.
LOG_TO_DIM = {
    "splitAxis": "SplitAxis",
    "inputDtype": "InputDType",
    "isTnd": "IsTnd",
    "dropValue": "IsDrop",
    "pseValue": "IsPse",
    "attenMaskCfg": "IsAttenMask",
    "isDeterministic": "DeterType",
    "isBn2MultiBlk": "IsBn2MultiBlk",
    "hasRope": "IsRope",
    "isNzOut": "IsNzOut",
    "isTndSwizzle": "IsTndSwizzle",
    "s1TemplateType": "S1TemplateNum",
    "s2TemplateType": "S2TemplateNum",
    "dTemplateType": "DTemplateNum",
    "nEqual": "IsNEqual",
    "dNoEqual": "IsDNoEqual",
    "outDtype": "OutDType",
    "isRegbasePlatformValue": "IsRegbase",
}


def main() -> int:
    cases = {
        "sbh": I.Case(layout="SBH", dtype="FLOAT", b=1, s1=256, s2=256, n2=1, g=1,
                      d=128, atten_mask="ss", tag="smoke"),
        "bsnd": I.Case(layout="BSND", dtype="FLOAT16", b=2, s1=2000, s2=2000,
                       n2=8, g=1, d=128, tag="smoke"),
        "bnsd": I.Case(layout="BNSD", dtype="FLOAT", b=1, s1=64, s2=128, n2=1,
                       g=1, d=129, tag="smoke"),
        "bsh": I.Case(layout="BSH", dtype="BF16", b=3, s1=128, s2=121, n2=1, g=1,
                      d=128, tag="smoke"),
        "tnd_even": I.Case(layout="TND", dtype="FLOAT16", n2=1, g=2, d=32,
                           seq_q=[128, 384, 768, 974], seq_kv=[128, 384, 768, 974],
                           atten_mask="2048", sparse_mode=4, pre_tokens=45,
                           next_tokens=2, tag="smoke"),
        "tnd_zero": I.Case(layout="TND", dtype="FLOAT16", n2=1, g=2, d=32,
                           seq_q=[128, 128, 384], seq_kv=[128, 128, 384],
                           tag="smoke"),
    }

    print(f"replaying {len(cases)} smoke cases...")
    res = R.run(cases, tag="smoke")

    bad = 0
    for cid, case in cases.items():
        r = res[cid]
        status = "ok" if r.ok else f"REJECTED {r.reject[:80]}"
        print(f"\n{cid:10} {status}")
        if not r.ok:
            bad += 1
            continue
        print(f"  key={r.key}")
        if not r.logged:
            print("  NO LOG PARSED (cross-check did not run)")
            bad += 1
        checked = 0
        # The logged values and the decoded ones come from different paths; if
        # they disagree the decode cannot be trusted.
        for log_name, dim_name in LOG_TO_DIM.items():
            if log_name not in r.logged or dim_name not in r.dims:
                continue
            checked += 1
            lv, dv = r.logged[log_name], r.dims[dim_name]
            if int(lv) != int(dv):
                print(f"  MISMATCH {dim_name}: logged={lv} decoded={dv}")
                bad += 1
        print(f"  cross-checked {checked}/{len(LOG_TO_DIM)} dims")
        c = case.normalised()
        if c.layout == "TND":
            print(f"  lens_q={c.lens_q} lens_kv={c.lens_kv} b={c.b} s1={c.s1}")
        print(f"  diag={r.diag}")

    out = R.CACHE / "smoke_wide.csv"
    R.write_wide(out, cases, res)
    print(f"\nwide table -> {out}")
    print("all consistent" if bad == 0 else f"{bad} problems")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
