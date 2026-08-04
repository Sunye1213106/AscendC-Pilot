#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rewrite fag_arch35_reachable_cases.csv into the schema fag_debug_tools/run_fag.py reads.

The closure pipeline emits witnesses in the replay driver's own vocabulary (lower case
layout/dtype tokens, `n2`/`g` instead of N1/N2, cumulative TND offsets joined by "/").
`fag_test.test_utils.get_case` expects the Excel-style column names used by the FAG test
sheets. This script performs that translation in place, keeping `tiling_key` /
`tiling_key_hex` / `declared` and the 19 `dim_*` columns so每行仍能追溯到原 TilingKey。

None of the rewrites touch a field that participates in the TilingKey: the 19 dimensions
only see IsPse (not the PSE shape) and IsAttenMask (not the mask shape), so remapping an
unsupported PSE/mask spelling to a supported one keeps the witness valid.

Usage:
  python scripts/fag_reachable_cases_to_fagtest.py            # rewrite in place
  python scripts/fag_reachable_cases_to_fagtest.py --check    # verify only
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parents[1] / "docs" / "fag" / "data" / "fag_arch35_reachable_cases.csv"

# Testcase_Name is the decimal TilingKey behind this prefix, so a bare "tk_" grep pulls every
# case name out of run_log.txt / the result sheet without also matching the raw key columns.
NAME_PREFIX = "tk_"

DTYPE_MAP = {"FLOAT16": "fp16", "BF16": "bf16", "FLOAT": "fp32"}

# (Atten_mask_shape, Atten_mask_dtype). "2048" is the compressed 2048x2048 mask; the test
# tool builds that tensor itself whenever sparse_mode is 2/3/4/6, so the sheet only needs a
# non-NONE 2D spelling to keep IsAttenMask=1.
MASK_MAP = {
    "none": ("NONE", ""),
    "ss": ("SS", "bool"),
    "11ss": ("11SS", "bool"),
    "b1ss": ("B1SS", "bool"),
    "bnss": ("BNSS", "bool"),
    "2048": ("SS", "bool"),
}

EXTERNAL_PSE_MAP = {"1nss": "1NSS", "bnss": "BNSS", "b1ss": "BNSS", "bnhs": "BNHS", "1nhs": "1NHS"}

# D of queryRope/keyRope must be 64 (normal_regbase.cpp:361). The test tool derives the rope
# width as D - D_V, so D_V carries the tiling-visible d1 and D adds the fixed rope width.
ROPE_D = 64

# Compressed alibi (BNHS/1NHS) and TND external PSE both require S1 > 1024 on the device.
ALIBI_H = 1024

DIM_COLUMNS = [
    "dim_IsEmptyTensor", "dim_SplitAxis", "dim_InputDType", "dim_IsTnd", "dim_IsDrop",
    "dim_IsPse", "dim_IsAttenMask", "dim_S1TemplateNum", "dim_S2TemplateNum",
    "dim_DTemplateNum", "dim_DeterType", "dim_IsNEqual", "dim_IsBn2MultiBlk",
    "dim_IsDNoEqual", "dim_IsRope", "dim_OutDType", "dim_IsNzOut", "dim_IsTndSwizzle",
    "dim_IsRegbase",
]

OUT_COLUMNS = [
    "Testcase_Name", "tiling_key", "tiling_key_hex", "declared",
    "Enable", "Dtype", "out_dtype", "Input_Layout",
    "B", "N1", "N2", "S1", "S2", "D", "D_V",
    "Drop_Out_Possibility", "Pre_Tockens", "Next_Tockens",
    "Atten_mask_dtype", "Atten_mask_shape", "sparse_mode",
    "PSE_type", "PSE_shape", "seqlens_list_q", "seqlens_list_kv",
    "is_deter", "rope",
    "est_attn_elems", "adapt_note",
] + DIM_COLUMNS


def cumulative_to_lens(text: str) -> list[int]:
    """"1024/1792/3840" -> [1024, 768, 2048]; the driver writes cumulative offsets."""
    cumulative = [int(x) for x in text.split("/")]
    return [cumulative[0]] + [cumulative[i + 1] - cumulative[i] for i in range(len(cumulative) - 1)]


def convert_row(row: dict) -> dict:
    notes = []
    layout = row["layout"]
    s1, s2 = int(row["s1"]), int(row["s2"])
    d, d1 = int(row["d"]), int(row["d1"])
    rope = int(row["rope"])

    if rope:
        d_out, dv_out = d1 + ROPE_D, d1
        notes.append(f"rope:D={dv_out}+{ROPE_D}")
    else:
        d_out, dv_out = d, d1

    mask_shape, mask_dtype = MASK_MAP[row["atten_mask"]]
    if row["atten_mask"] == "2048":
        notes.append("mask:2048->SS")

    src_pse_type = int(row["pse_type"])
    if row["pse"] == "0":
        pse_shape, pse_type = "NONE", 1
        if src_pse_type not in (0, 1):
            # alibi pse_type without a pse tensor is rejected by aclnn; harmless to normalise
            # because the key only records IsPse.
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
            # TND requires Sq >= 1024 for an external pse_shift; fall back to internal alibi.
            pse_shape, pse_type = "BN", 2
            notes.append(f"pse:{row['pse_shape']}->BN(alibi,TND S1<={ALIBI_H})")
        elif pse_shape in ("BNHS", "1NHS") and s1 <= ALIBI_H:
            pse_shape = "BNSS" if pse_shape == "BNHS" else "1NSS"
            notes.append(f"pse:{row['pse_shape']}->{pse_shape}(S1<={ALIBI_H})")

    if layout == "TND":
        seq_q = str(cumulative_to_lens(row["seq_q"]))
        seq_kv = str(cumulative_to_lens(row["seq_kv"]))
    else:
        seq_q = seq_kv = ""

    n2, g = int(row["n2"]), int(row["g"])
    dtype = DTYPE_MAP[row["dtype"]]

    out = {
        "Testcase_Name": NAME_PREFIX + row["tiling_key"],
        "tiling_key": row["tiling_key"],
        "tiling_key_hex": row["tiling_key_hex"],
        "declared": row["declared"],
        "Enable": "Enable",
        "Dtype": dtype,
        "out_dtype": dtype,
        "Input_Layout": layout,
        "B": row["b"],
        "N1": n2 * g,
        "N2": n2,
        "S1": s1,
        "S2": s2,
        "D": d_out,
        "D_V": dv_out,
        "Drop_Out_Possibility": row["keep_prob"],
        "Pre_Tockens": row["pre_tokens"],
        "Next_Tockens": row["next_tokens"],
        "Atten_mask_dtype": mask_dtype,
        "Atten_mask_shape": mask_shape,
        "sparse_mode": row["sparse_mode"],
        "PSE_type": pse_type,
        "PSE_shape": pse_shape,
        "seqlens_list_q": seq_q,
        "seqlens_list_kv": seq_kv,
        "is_deter": "true" if row["deterministic"] == "1" else "false",
        "rope": rope,
        "est_attn_elems": int(row["b"]) * n2 * g * s1 * s2,
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
    """Re-parse the rewritten sheet the way run_fag.py does and report anything unusable."""
    import ast

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    missing = [c for c in OUT_COLUMNS if c not in rows[0]]
    if missing:
        print(f"FAIL: missing columns {missing}")
        return 2
    problems = []
    for row in rows:
        if row["Testcase_Name"] != NAME_PREFIX + row["tiling_key"]:
            problems.append((row["Testcase_Name"], "name is not the prefixed tiling key"))
        if row["Dtype"] not in ("fp16", "bf16", "fp32"):
            problems.append((row["Testcase_Name"], "dtype"))
        if row["Input_Layout"] not in ("BSH", "SBH", "BNSD", "BSND", "TND"):
            problems.append((row["Testcase_Name"], "layout"))
        if row["Atten_mask_shape"] not in ("NONE", "SS", "11SS", "B1SS", "BNSS"):
            problems.append((row["Testcase_Name"], "mask"))
        if row["PSE_shape"] not in ("NONE", "BN1S", "1NSS", "BNSS", "BNHS", "1NHS", "BN", "N"):
            problems.append((row["Testcase_Name"], "pse_shape"))
        if row["PSE_shape"] in ("BN", "N") and row["PSE_type"] not in ("2", "3"):
            problems.append((row["Testcase_Name"], "alibi needs pse_type 2/3"))
        if row["PSE_shape"] not in ("NONE", "BN", "N") and row["PSE_type"] not in ("0", "1"):
            problems.append((row["Testcase_Name"], "external pse needs pse_type 0/1"))
        if int(row["N1"]) % int(row["N2"]):
            problems.append((row["Testcase_Name"], "N1%N2"))
        if row["Input_Layout"] == "TND":
            lens_q = ast.literal_eval(row["seqlens_list_q"])
            lens_kv = ast.literal_eval(row["seqlens_list_kv"])
            if len(lens_q) != int(row["B"]) or len(lens_kv) != int(row["B"]):
                problems.append((row["Testcase_Name"], "seqlens length"))
            if min(lens_q + lens_kv) < 0:
                problems.append((row["Testcase_Name"], "negative seqlen"))
            if max(lens_q) != int(row["S1"]) or max(lens_kv) != int(row["S2"]):
                problems.append((row["Testcase_Name"], "seqlens vs S1/S2"))
        elif row["seqlens_list_q"]:
            problems.append((row["Testcase_Name"], "seqlens on non-TND"))
    if problems:
        for name, why in problems[:20]:
            print(f"FAIL: {name}: {why}")
        print(f"FAIL: {len(problems)} problem(s)")
        return 2
    names = set(r["Testcase_Name"] for r in rows)
    if len(names) != len(rows):
        print(f"FAIL: {len(rows) - len(names)} duplicate Testcase_Name")
        return 2
    print(f"ok: {len(rows)} rows, {len(set(r['tiling_key'] for r in rows))} distinct tiling keys")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--check", action="store_true", help="validate an already converted sheet")
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
