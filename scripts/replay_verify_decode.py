# -*- coding: utf-8 -*-
"""Check the key decode against the values the tiling logged.

The host passes a literal 0 for IsEmptyTensor, so any case decoding to 1 means
the bit layout is off and every coverage number built on it is wrong. This
re-encodes the logged dimensions and compares with the key the host returned.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import runner as R

LOG_TO_DIM = {
    "splitAxis": "SplitAxis", "inputDtype": "InputDType", "isTnd": "IsTnd",
    "dropValue": "IsDrop", "pseValue": "IsPse", "attenMaskCfg": "IsAttenMask",
    "s1TemplateType": "S1TemplateNum", "s2TemplateType": "S2TemplateNum",
    "dTemplateType": "DTemplateNum", "isDeterministic": "DeterType",
    "nEqual": "IsNEqual", "isBn2MultiBlk": "IsBn2MultiBlk",
    "dNoEqual": "IsDNoEqual", "hasRope": "IsRope", "outDtype": "OutDType",
    "isNzOut": "IsNzOut", "isTndSwizzle": "IsTndSwizzle",
    "isRegbasePlatformValue": "IsRegbase",
}


def main() -> int:
    path = R.CACHE / "fag_key_cases.csv"
    rows = path.read_text(encoding="utf-8").splitlines()
    head = rows[0].split(",")
    idx = {n: i for i, n in enumerate(head)}

    print("bit layout from the TPL header:")
    for d in R.SCHEMA.dims:
        print(f"  bit {d.bit_lo:>2}-{d.bit_hi:<2} w={d.bw} {d.name:<18} {list(d.value_domain)}")

    checked = mismatched = 0
    empty_one = []
    shown = 0
    for line in rows[1:]:
        f = line.split(",")
        if f[idx["ok"]] != "1":
            continue
        key = int(f[idx["tiling_key"]])
        logged = {}
        for log_name, dim in LOG_TO_DIM.items():
            raw = f[idx["log_" + log_name]]
            if raw == "":
                break
            logged[dim] = int(raw)
        if len(logged) != len(LOG_TO_DIM):
            continue
        checked += 1
        if f[idx["dim_IsEmptyTensor"]] == "1":
            empty_one.append((f[idx["case_id"]], key))
        # The host always passes 0 here, so a faithful encode must reproduce
        # the key from the logged values plus that constant.
        rebuilt = dict(logged)
        rebuilt["IsEmptyTensor"] = 0
        try:
            got = R.SCHEMA.encode_tiling_key(rebuilt)
        except Exception as exc:  # noqa: BLE001
            print(f"encode failed: {exc}")
            return 1
        if got != key:
            mismatched += 1
            if shown < 3:
                shown += 1
                print(f"\ncase {f[idx['case_id']]}")
                print(f"  host key   = {key}   ({key:055b})")
                print(f"  re-encoded = {got}   ({got:055b})")
                print(f"  xor        = {key ^ got}  bits={_bits(key ^ got)}")
    print(f"\nchecked {checked} cases, {mismatched} disagree with a re-encode")
    print(f"{len(empty_one)} cases decode IsEmptyTensor=1 "
          f"(host passes a literal 0)")
    if empty_one[:3]:
        print("  e.g.", empty_one[:3])
    return 0


def _bits(v: int) -> list[int]:
    return [i for i in range(64) if v >> i & 1]


if __name__ == "__main__":
    raise SystemExit(main())
