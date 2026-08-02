#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P5: generate L1/L2 CSV from new UO contract (script-first TG path)."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UO_SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(UO_SRC))

from uo_init import paths  # noqa: E402

DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

OP = paths.op_dir(relative=DEFAULT_OPERATOR)
DEBUG = ROOT / "docs" / "debug" / "uo-tg-closure"
#: fag_debug_tools is a separate checkout sitting beside ops-transformer.
_OPS = paths.ops_root()
FAG_DATA = _OPS.parent / "fag_debug_tools" / "data" if _OPS is not None else None

INPUT_DTYPE = {
    "0": "fp16",
    "1": "fp32",
    "2": "bf16",
    "3": "fp16",
    "4": "fp8_e5m2",
    "5": "fp8_e4m3",
    "6": "hifp8",
}
OUT_DTYPE = {"0": "fp16", "1": "fp32", "2": "bf16", "3": "fp16"}


def _i(dims: dict, name: str, default: int = 0) -> int:
    try:
        return int(str(dims.get(name, default)))
    except ValueError:
        return default


def shape_from_dims(dims: dict[str, str]) -> dict[str, object]:
    """Deterministic witness shape locked to key dims (no rope D override)."""
    s1_t = _i(dims, "S1TemplateNum")
    s2_t = _i(dims, "S2TemplateNum")
    d_t = _i(dims, "DTemplateNum")
    s1 = s1_t if s1_t > 0 else 16
    s2 = s2_t if s2_t > 0 else 16
    d = d_t if d_t > 0 else 64
    n_equal = _i(dims, "IsNEqual")
    n1, n2 = (4, 4) if n_equal else (8, 2)
    d_no = _i(dims, "IsDNoEqual")
    rope = _i(dims, "IsRope")
    if rope and d_no:
        d_v = max(d // 2, 32) if d > 64 else 32
    elif d_no:
        d_v = max(d // 2, 32) if d > 64 else 32
    else:
        d_v = d
    is_tnd = _i(dims, "IsTnd")
    layout = "TND" if is_tnd else "BNSD"
    empty = _i(dims, "IsEmptyTensor")
    dtype = INPUT_DTYPE.get(str(dims.get("InputDType", "3")), "fp16")
    out_dtype = OUT_DTYPE.get(str(dims.get("OutDType", "3")), dtype)
    drop = 0.9 if _i(dims, "IsDrop") else 1.0
    pse = _i(dims, "IsPse")
    atten = _i(dims, "IsAttenMask")
    deter = _i(dims, "DeterType")
    is_deter = "true" if deter in (1, 2, 3, 4) else "false"
    if deter == 3:
        sparse_mode, pre_tok, next_tok = 2, 65536, 0
        atten_shape = "11SS"
    elif deter == 4:
        sparse_mode, pre_tok, next_tok = 4, 8, 16
        atten_shape = "B1SS"
    else:
        sparse_mode = 0 if not atten else 1
        pre_tok = next_tok = 65536
        atten_shape = "B1SS" if atten else "NONE"
    seqlens = ""
    if is_tnd and not empty:
        half = max(s1 // 2, 8)
        seqlens = f"[{half}, {s1}]"
    return {
        "Dtype": dtype,
        "out_dtype": out_dtype,
        "Input_Layout": layout,
        "B": 1 if empty else 2,
        "N1": n1,
        "N2": n2,
        "S1": s1,
        "S2": s2,
        "D": d,
        "D_V": d_v,
        "Drop_Out_Possibility": drop,
        "Pre_Tockens": pre_tok,
        "Next_Tockens": next_tok,
        "Atten_mask_dtype": "bool" if atten else "",
        "Atten_mask_shape": atten_shape,
        "sparse_mode": sparse_mode,
        "PSE_type": 1 if pse else 0,
        "PSE_shape": "BNSS" if pse else "NONE",
        "seqlens_list_q": seqlens,
        "seqlens_list_kv": seqlens,
        "is_deter": is_deter,
        "rope": rope,
        "IsEmptyTensor_flag": empty,
    }


def main() -> int:
    if OP is None or FAG_DATA is None:
        print(
            f"operator sources or ops-transformer not available\n{paths.explain()}",
            file=sys.stderr,
        )
        return 1
    if not FAG_DATA.parent.is_dir():
        print(f"fag_debug_tools checkout not found: {FAG_DATA.parent}", file=sys.stderr)
        return 1
    uo = OP / ".ascendc-pilot" / "uo"
    tg = OP / ".ascendc-pilot" / "tg" / "cases"
    tg.mkdir(parents=True, exist_ok=True)
    reach = yaml.safe_load((uo / "tiling" / "key_reachability.yaml").read_text(encoding="utf-8"))
    keys = list(reach.get("keys") or [])
    branches_doc = yaml.safe_load((uo / "kernel" / "branches.yaml").read_text(encoding="utf-8")) or {}
    branch_rows = list(branches_doc.get("branches") or [])

    dim_names = list(keys[0]["dims"].keys()) if keys else []
    l2_headers = [
        "Testcase_Name",
        "Enable",
        "Level",
        "Obligation_Id",
        "block_reason",
        "block_detail",
        "Dtype",
        "out_dtype",
        "Input_Layout",
        "B",
        "N1",
        "N2",
        "S1",
        "S2",
        "D",
        "D_V",
        "Drop_Out_Possibility",
        "Pre_Tockens",
        "Next_Tockens",
        "Atten_mask_dtype",
        "Atten_mask_shape",
        "sparse_mode",
        "PSE_type",
        "PSE_shape",
        "seqlens_list_q",
        "seqlens_list_kv",
        "is_deter",
        "rope",
        "TilingKey",
        "TilingKeyHex",
        *dim_names,
    ]

    l2_path = tg / "L2_legal_tilingkeys.csv"
    shape_fp_counter: Counter[tuple] = Counter()
    enable_c = Counter()
    reason_c = Counter()
    false_enable = 0

    with l2_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=l2_headers, extrasaction="ignore")
        w.writeheader()
        for row in keys:
            dims = {k: str(v) for k, v in (row.get("dims") or {}).items()}
            shape = shape_from_dims(dims)
            reason = str(row.get("reason_code") or "REALIZATION_MISSING")
            detail = str(row.get("detail") or "")
            status = str(row.get("status") or "underivable")
            enable = "Enable" if status == "reachable" and reason == "OK" else "Disable"
            # Consistency gate: D must equal DTemplate when present
            d_t = _i(dims, "DTemplateNum")
            if enable == "Enable" and d_t > 0 and int(shape["D"]) != d_t:
                false_enable += 1
                enable = "Disable"
                reason = "HOST_ENCODE_CONFLICT"
                detail = f"shape D={shape['D']} vs DTemplateNum={d_t}"
            enable_c[enable] += 1
            reason_c[reason] += 1
            fp = (
                shape["Dtype"],
                shape["Input_Layout"],
                shape["B"],
                shape["N1"],
                shape["N2"],
                shape["S1"],
                shape["S2"],
                shape["D"],
                shape["D_V"],
                shape["sparse_mode"],
                shape["PSE_type"],
                shape["rope"],
                shape["Drop_Out_Possibility"],
                shape["is_deter"],
            )
            if enable == "Enable":
                shape_fp_counter[fp] += 1
            key = int(row["tiling_key"])
            name = f"l2_{row['index']:05d}_{key:016x}"
            out = {
                "Testcase_Name": name,
                "Enable": enable,
                "Level": "L2",
                "Obligation_Id": f"L2_KEY_{row['index']:04d}",
                "block_reason": reason if enable == "Disable" else "OK",
                "block_detail": detail,
                "TilingKey": str(key),
                "TilingKeyHex": row.get("tiling_key_hex") or f"0x{key:016x}",
                **{k: v for k, v in shape.items() if k != "IsEmptyTensor_flag"},
            }
            out.update(dims)
            w.writerow(out)

    # L1: one case per input_controllable branch
    l1_headers = [
        "Testcase_Name",
        "Enable",
        "Level",
        "Obligation_Id",
        "branch_id",
        "target_value",
        "block_reason",
        "block_detail",
        "Dtype",
        "Input_Layout",
        "B",
        "N1",
        "N2",
        "S1",
        "S2",
        "D",
        "D_V",
    ]
    l1_path = tg / "L1_input_controllable_branches.csv"
    with l1_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=l1_headers, extrasaction="ignore")
        w.writeheader()
        for i, br in enumerate(branch_rows):
            if br.get("input_controllable") is False:
                continue
            bid = str(br.get("id") or f"BR_{i}")
            for tv in br.get("variants") or [True]:
                name = f"l1_{i:04d}_{bid}_{str(tv).lower()}"
                w.writerow(
                    {
                        "Testcase_Name": name,
                        "Enable": "Enable",
                        "Level": "L1",
                        "Obligation_Id": f"L1_{bid}_{tv}",
                        "branch_id": bid,
                        "target_value": tv,
                        "block_reason": "OK",
                        "block_detail": "",
                        "Dtype": "fp16",
                        "Input_Layout": "BNSD",
                        "B": 2,
                        "N1": 8,
                        "N2": 2,
                        "S1": 128,
                        "S2": 128,
                        "D": 64,
                        "D_V": 64,
                    }
                )

    # Sync L2 to fag_debug_tools
    FAG_DATA.mkdir(parents=True, exist_ok=True)
    fag_csv = FAG_DATA / "FASG_8705_tilingkey_cases.csv"
    fag_csv.write_bytes(l2_path.read_bytes())

    multi = sum(1 for n in shape_fp_counter.values() if n > 1)
    max_share = max(shape_fp_counter.values()) if shape_fp_counter else 0
    summary = {
        "l2_rows": len(keys),
        "l2_unique_keys": len({int(k["tiling_key"]) for k in keys}),
        "enable": dict(enable_c),
        "reason": dict(reason_c),
        "false_enable_fixed": false_enable,
        "enable_unique_shapes": len(shape_fp_counter),
        "enable_shapes_shared_by_gt1_keys": multi,
        "max_enable_keys_per_shape": max_share,
        "l1_branch_rows": len(branch_rows),
        "l2_csv": str(l2_path),
        "l1_csv": str(l1_path),
        "fag_csv": str(fag_csv),
        "gate": {
            "unique_keys_8705": len(keys) == 8705 and len({int(k["tiling_key"]) for k in keys}) == 8705,
            "no_false_d_override": false_enable == 0,
        },
    }
    (tg / "generation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    DEBUG.mkdir(parents=True, exist_ok=True)
    (DEBUG / "05_tg_script.md").write_text(
        "\n".join(
            [
                "# P5 TG script CSV",
                "",
                "```json",
                json.dumps(summary, ensure_ascii=False, indent=2),
                "```",
                "",
                "L2 shape 由 key dims 确定性投影（D≡DTemplateNum），禁止 rope 强改 D。",
                "同一 Enable shape 可被多个 key 共享仅当 dims 差异不落在 CSV shape 列（记录在 max_enable_keys_per_shape）。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    ok = summary["gate"]["unique_keys_8705"] and summary["l2_rows"] == 8705
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
