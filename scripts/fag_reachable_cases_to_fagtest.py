#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rewrite fag_arch35_reachable_cases.csv into the FASG.xls column schema.

Column names / defaults follow TEST/fag_debug_tools/data/FASG.xls so run_fag.py
reads the sheet the same way as the hand-written Excel cases:
  - empty ``prefix`` (script auto-builds via get_prefix*)
  - seed=2, offset=0, inner_drop=1
  - Layout / Atten_mask_Shape / pre_tockens naming
  - TND mask only SS/NONE; sm5/6 never NONE
  - sm2/3 Host NONE -> SS (FASG compress causal); sm4 Host NONE stays NONE
    (sm4 band uses pre/next; SS compress with bad diagonal previously broke S1>>S2)
  - TND: S1/S2/T(B*S) empty, seqlens filled (FASG_TND1); dense: opposite

Usage:
  python scripts/fag_reachable_cases_to_fagtest.py
  python scripts/fag_reachable_cases_to_fagtest.py --check
"""
from __future__ import annotations

import argparse
import ast
import csv
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parents[1] / "docs" / "fag" / "data" / "fag_arch35_reachable_cases.csv"

NAME_PREFIX = "tk_"
DTYPE_MAP = {"FLOAT16": "fp16", "BF16": "bf16", "FLOAT": "fp32"}
MASK_MAP = {
    "none": ("NONE", "NONE"),
    "ss": ("SS", "BOOL"),
    "11ss": ("11SS", "BOOL"),
    "b1ss": ("B1SS", "BOOL"),
    "bnss": ("BNSS", "BOOL"),
    "2048": ("SS", "BOOL"),
}
EXTERNAL_PSE_MAP = {"1nss": "1NSS", "bnss": "BNSS", "b1ss": "BNSS", "bnhs": "BNHS", "1nhs": "1NHS"}
ROPE_D = 64
ALIBI_H = 1024

# FASG.xls header order, then traceability extras.
XLS_COLUMNS = [
    "Testcase_Name", "enable", "is_deter", "Level", "Network_Type",
    "B", "N1", "N2", "S1", "S2", "D", "D_V",
    "Dtype", "out_dtype", "sparse_mode", "sparse", "prefix",
    "pre_tockens", "next_tockens", "Layout",
    "PSE_type", "PSE_shape", "Atten_mask_Dtype", "Atten_mask_Shape",
    "Drop_Out_Possibility", "Padding_Mask", "seed", "offset", "inner_drop", "rope",
    "T(B*S)", "seqlens_list_q", "seqlens_list_kv", "same_as_input", "EOD",
]
TRACE_COLUMNS = [
    "tiling_key", "tiling_key_hex", "declared", "est_attn_elems", "adapt_note",
    "dim_IsEmptyTensor", "dim_SplitAxis", "dim_InputDType", "dim_IsTnd", "dim_IsDrop",
    "dim_IsPse", "dim_IsAttenMask", "dim_S1TemplateNum", "dim_S2TemplateNum",
    "dim_DTemplateNum", "dim_DeterType", "dim_IsNEqual", "dim_IsBn2MultiBlk",
    "dim_IsDNoEqual", "dim_IsRope", "dim_OutDType", "dim_IsNzOut", "dim_IsTndSwizzle",
    "dim_IsRegbase",
]
OUT_COLUMNS = XLS_COLUMNS + TRACE_COLUMNS
DIM_COLUMNS = [c for c in TRACE_COLUMNS if c.startswith("dim_")]


def cumulative_to_lens(text: str) -> list[int]:
    cumulative = [int(x) for x in text.split("/")]
    return [cumulative[0]] + [cumulative[i + 1] - cumulative[i] for i in range(len(cumulative) - 1)]


def convert_row(row: dict) -> dict:
    notes = []
    layout = row["layout"]
    s1, s2 = int(row["s1"]), int(row["s2"])
    d, d1 = int(row["d"]), int(row["d1"])
    rope = int(row["rope"])
    sparse_mode = int(row["sparse_mode"])
    n2, g = int(row["n2"]), int(row["g"])
    n1 = n2 * g
    b = int(row["b"])
    dtype = DTYPE_MAP[row["dtype"]]

    if rope:
        d_out, dv_out = d1 + ROPE_D, d1
        notes.append(f"rope:D={dv_out}+{ROPE_D}")
    else:
        d_out, dv_out = d, d1

    mask_shape, mask_dtype = MASK_MAP[row["atten_mask"]]
    if row["atten_mask"] == "2048":
        notes.append("mask:2048->SS")
    # Align with FASG.xls / FASG_TND1.xls: TND never uses B1SS/BNSS.
    if layout == "TND" and mask_shape in ("B1SS", "BNSS"):
        notes.append(f"mask:{mask_shape}->SS(TND)")
        mask_shape, mask_dtype = "SS", "BOOL"
    # FASG.xls: sm2/3 always use SS/11SS compress causal — Host may witness
    # atten_mask=none (IsAttenMask=0), but PTA/test harness expect 2048 compress.
    # sm4 stays NONE: band is driven by pre/next; forcing SS previously broke S1>>S2.
    if sparse_mode in (2, 3) and mask_shape == "NONE":
        notes.append(f"mask:NONE->SS(sm{sparse_mode})")
        mask_shape, mask_dtype = "SS", "BOOL"
    # FASG.xls: every sm5/6 row has a concrete mask (TND→SS, dense→B1SS/BNSS/SS).
    if sparse_mode in (5, 6) and mask_shape == "NONE":
        if layout == "TND":
            notes.append("mask:NONE->SS(sm5/6)")
            mask_shape, mask_dtype = "SS", "BOOL"
        else:
            notes.append("mask:NONE->B1SS(sm5/6)")
            mask_shape, mask_dtype = "B1SS", "BOOL"

    src_pse_type = int(row["pse_type"])
    if row["pse"] == "0":
        pse_shape, pse_type = "NONE", 1
        if src_pse_type not in (0, 1):
            notes.append(f"pse_type:{src_pse_type}->1(no pse)")
    elif row["pse_shape"] in ("slope", "slope_n"):
        pse_shape = "BN" if row["pse_shape"] == "slope" else "N"
        pse_type = src_pse_type
    else:
        pse_shape = EXTERNAL_PSE_MAP[row["pse_shape"]]
        pse_type = src_pse_type
        if row["pse_shape"] == "b1ss":
            notes.append("pse:b1ss->BNSS")
        if layout == "TND" and s1 <= ALIBI_H:
            pse_shape, pse_type = "BN", 2
            notes.append(f"pse:{row['pse_shape']}->BN(alibi,TND S1<={ALIBI_H})")
        elif pse_shape in ("BNHS", "1NHS") and s1 <= ALIBI_H:
            pse_shape = "BNSS" if pse_shape == "BNHS" else "1NSS"
            notes.append(f"pse:{row['pse_shape']}->{pse_shape}(S1<={ALIBI_H})")

    # Dense FASG.xls: fill S1/S2, leave seqlens empty.
    # TND FASG_TND1.xls: no S1/S2 columns (empty here); fill seqlens only.
    # run_fag get_case derives S1/S2 = max(seqlens) for TND.
    if layout == "TND":
        lens_q = cumulative_to_lens(row["seq_q"])
        lens_kv = cumulative_to_lens(row["seq_kv"])
        # FASG_TND1 style: "[a,b,c]" without spaces.
        seq_q = "[" + ",".join(str(x) for x in lens_q) + "]"
        seq_kv = "[" + ",".join(str(x) for x in lens_kv) + "]"
        s1_cell = s2_cell = ""
        t_bs = ""
        est_attn = b * n1 * max(lens_q) * max(lens_kv)
    else:
        seq_q = seq_kv = ""
        s1_cell, s2_cell = s1, s2
        t_bs = b * s1
        est_attn = b * n1 * s1 * s2

    out = {
        "Testcase_Name": NAME_PREFIX + row["tiling_key"],
        "enable": "enable",
        "is_deter": 1 if row["deterministic"] == "1" else 0,
        "Level": "L2",
        "Network_Type": "reachable_witness",
        "B": b,
        "N1": n1,
        "N2": n2,
        "S1": s1_cell,
        "S2": s2_cell,
        "D": d_out,
        "D_V": dv_out,
        "Dtype": dtype,
        "out_dtype": dtype,
        "sparse_mode": sparse_mode,
        "sparse": 0,
        "prefix": "",  # FASG.xls leaves this empty; script calls get_prefix*.
        "pre_tockens": row["pre_tokens"],
        "next_tockens": row["next_tokens"],
        "Layout": layout,
        "PSE_type": pse_type,
        "PSE_shape": pse_shape,
        "Atten_mask_Dtype": mask_dtype,
        "Atten_mask_Shape": mask_shape,
        "Drop_Out_Possibility": row["keep_prob"],
        "Padding_Mask": "NONE",
        "seed": 2,
        "offset": 0,
        "inner_drop": 1,  # FASG.xls / David / TND1 all use 1.
        "rope": rope,
        "T(B*S)": t_bs,
        "seqlens_list_q": seq_q,
        "seqlens_list_kv": seq_kv,
        "same_as_input": 0,
        "EOD": "",
        "tiling_key": row["tiling_key"],
        "tiling_key_hex": row["tiling_key_hex"],
        "declared": row["declared"],
        "est_attn_elems": est_attn,
        "adapt_note": ";".join(notes),
    }
    out.update({col: row[col] for col in DIM_COLUMNS})
    return out


def convert(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if "layout" not in (rows[0] if rows else {}):
        raise SystemExit(f"{csv_path} is not in the closure schema; nothing to convert")
    return [convert_row(row) for row in rows]


def check(csv_path: Path) -> int:
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    missing = [c for c in XLS_COLUMNS if c not in rows[0]]
    if missing:
        print(f"FAIL: missing xls columns {missing}")
        return 2
    problems = []
    for row in rows:
        if row["Testcase_Name"] != NAME_PREFIX + row["tiling_key"]:
            problems.append((row["Testcase_Name"], "name"))
        if str(row.get("prefix", "")).strip() != "":
            problems.append((row["Testcase_Name"], "prefix must be empty like FASG.xls"))
        if str(row.get("inner_drop", "")) != "1":
            problems.append((row["Testcase_Name"], "inner_drop!=1"))
        if row["Layout"] not in ("BSH", "SBH", "BNSD", "BSND", "TND"):
            problems.append((row["Testcase_Name"], "layout"))
        if row["Atten_mask_Shape"] not in ("NONE", "SS", "11SS", "B1SS", "BNSS"):
            problems.append((row["Testcase_Name"], "mask"))
        if row["Layout"] == "TND" and row["Atten_mask_Shape"] in ("B1SS", "BNSS"):
            problems.append((row["Testcase_Name"], "TND B1SS/BNSS"))
        if row["sparse_mode"] in ("2", "3", "5", "6") and row["Atten_mask_Shape"] == "NONE":
            problems.append((row["Testcase_Name"], f"sm{row['sparse_mode']} NONE mask"))
        if row["Layout"] == "TND":
            if str(row.get("S1", "")).strip() != "" or str(row.get("S2", "")).strip() != "":
                problems.append((row["Testcase_Name"], "TND S1/S2 should be empty like FASG_TND1"))
            if str(row.get("seqlens_list_q", "")).strip() == "" or str(row.get("seqlens_list_kv", "")).strip() == "":
                problems.append((row["Testcase_Name"], "TND missing seqlens"))
            else:
                lens_q = ast.literal_eval(row["seqlens_list_q"])
                lens_kv = ast.literal_eval(row["seqlens_list_kv"])
                if len(lens_q) != int(row["B"]) or len(lens_kv) != int(row["B"]):
                    problems.append((row["Testcase_Name"], "seqlens length"))
        else:
            if str(row.get("S1", "")).strip() == "":
                problems.append((row["Testcase_Name"], "dense missing S1"))
            if str(row.get("seqlens_list_q", "")).strip() != "" or str(row.get("seqlens_list_kv", "")).strip() != "":
                problems.append((row["Testcase_Name"], "dense seqlens should be empty"))
    if problems:
        for name, why in problems[:20]:
            print(f"FAIL: {name}: {why}")
        print(f"FAIL: {len(problems)} problem(s)")
        return 2
    print(f"ok: {len(rows)} rows aligned to FASG.xls schema")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check(args.csv)
    rows = convert(args.csv)
    with args.csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.csv}")
    return check(args.csv)


if __name__ == "__main__":
    raise SystemExit(main())
