# -*- coding: utf-8 -*-
"""Read-only probe: check L2 CSV rows against host rules extracted from FAG arch35 source.

Rules (source: op_host/arch35/flash_attention_score_grad_tiling_{common,normal}_regbase.cpp)
  R1 dNoEqual = (d1 != d) || hasRope            -> IsRope=1 => IsDNoEqual=1
  R2 GetDTemplateType: hasRope => DTemplateNum == 192
  R3 GetDTemplateType (no rope): DTemplateNum is a *bucket* of d
  R4 GetS1S2TemplateType couples InputDType with (S1TemplateNum, S2TemplateNum)
  R5 isRegbasePlatformValue = ENABLE (constant, platform) -> not input controllable
"""
from __future__ import annotations

import csv
import sys
from collections import Counter

from uo_init import paths

DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

_OP = paths.op_dir(relative=DEFAULT_OPERATOR)
CSV = (
    _OP / ".ascendc-pilot" / "tg" / "cases" / "L2_legal_tilingkeys.csv"
    if _OP is not None
    else None
)

BUCKET_LO = {64: 1, 128: 65, 192: 129, 256: 193, 768: 257}


def s1s2_expected(input_dtype: str, d: int) -> set[tuple[int, int]]:
    if input_dtype == "1":  # FLOAT32
        return {(64, 128)} if d > 256 else {(128, 128)}
    if input_dtype in ("4", "5"):  # FP8_E5M2 / FP8_E4M3FN
        return {(64, 256)}
    if input_dtype == "6":  # HIFLOAT8
        return {(512, 512)}
    return {(128, 128)}


def main() -> int:
    if CSV is None:
        print(f"operator sources not available\n{paths.explain()}", file=sys.stderr)
        return 1
    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
    v = Counter()
    samples: dict[str, list[str]] = {}

    def flag(name: str, row: dict[str, str], msg: str) -> None:
        v[name] += 1
        samples.setdefault(name, [])
        if len(samples[name]) < 3:
            samples[name].append(f"{row['Testcase_Name']} {msg}")

    for r in rows:
        if r["Enable"] != "Enable":
            continue
        rope = int(r["IsRope"])
        dno = int(r["IsDNoEqual"])
        dt = int(r["DTemplateNum"])
        d = int(r["D"])
        dv = int(r["D_V"])
        s1t, s2t = int(r["S1TemplateNum"]), int(r["S2TemplateNum"])
        idt = r["InputDType"]

        if rope == 1 and dno != 1:
            flag("R1_rope_implies_dNoEqual", r, f"IsRope=1 IsDNoEqual={dno}")
        if rope == 1 and dt != 192:
            flag("R2_rope_implies_DTemplate192", r, f"IsRope=1 DTemplateNum={dt}")
        if rope == 0 and dt in BUCKET_LO and not (BUCKET_LO[dt] <= d <= dt):
            flag("R3_D_outside_bucket", r, f"D={d} not in [{BUCKET_LO[dt]},{dt}]")
        exp = s1s2_expected(idt, d)
        if (s1t, s2t) not in exp:
            flag("R4_s1s2_dtype_conflict", r, f"InputDType={idt} D={d} (S1T,S2T)=({s1t},{s2t}) expected {sorted(exp)}")
        if dno == 1 and dv == d:
            flag("R6_dNoEqual_but_DV_eq_D", r, f"IsDNoEqual=1 D={d} D_V={dv}")
        if dno == 0 and dv != d:
            flag("R6b_dEqual_but_DV_ne_D", r, f"IsDNoEqual=0 D={d} D_V={dv}")
        if rope == 1 and dv == d:
            flag("R7_rope_needs_d1_ne_d", r, f"rope=1 D={d} D_V={dv}")

    print(f"rows={len(rows)} enable={sum(1 for r in rows if r['Enable']=='Enable')}")
    print("--- violations ---")
    for k in sorted(v):
        print(f"{k:34s} {v[k]:6d}")
        for s in samples[k]:
            print(f"    {s}")
    print("--- column value spread on Enable rows ---")
    for col in ("B", "N1", "N2", "S1", "S2", "IsRegbase", "Input_Layout", "Dtype"):
        print(f"{col:14s} {dict(Counter(r[col] for r in rows if r['Enable']=='Enable'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
