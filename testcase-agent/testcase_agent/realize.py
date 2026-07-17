from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .io import write_yaml
from .hashing import stable_hash


# Columns aligned with fag_debug_tools data/FASG_PSE_cases.csv
CSV_COLUMNS = [
    "Testcase_Name",
    "Enable",
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
    "cu_seqlens_q",
    "cu_seqlens_kv",
    "eod",
    "same_as_input",
    "seed",
    "offset",
    "is_deter",
    "rope",
    "inner_drop",
    "is_sink",
    "prefix",
]

DEFAULT_SHAPE = {
    "B": 2,
    "N1": 4,
    "N2": 2,
    "S1": 16,
    "S2": 16,
    "D": 64,
    "D_V": 64,
}


def realize_candidates_to_csv(
    out_root: Path,
    selected_candidates: list[dict[str, Any]],
    snapshot: dict[str, Any],
    *,
    dry_run: bool = False,
    level: str = "",
    case_name: str = "",
) -> dict[str, Any]:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    input_realization = _as_dict(constraints.get("input_realization"))
    rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for idx, candidate in enumerate(selected_candidates, start=1):
        model = _as_dict(candidate.get("model") or candidate.get("assignment"))
        if not model:
            # Reconstruct from coverage signature when older candidates lack model
            sig = _as_dict(candidate.get("coverage_signature"))
            model = dict(sig.get("key_fields") or {})
            for key in ("family_ref", "path_ref", "template_ref", "dtype_layout_class", "numerical_mode"):
                if sig.get(key) is not None:
                    mapping = {
                        "family_ref": "VAR_FAMILY",
                        "path_ref": "VAR_KERNEL_PATH",
                        "template_ref": "VAR_TEMPLATE",
                        "dtype_layout_class": "VAR_DTYPE_LAYOUT_CLASS",
                        "numerical_mode": "VAR_NUMERICAL_MODE",
                    }
                    model[mapping[key]] = sig[key]
            for branch, value in _as_dict(sig.get("branch_truth")).items():
                model[f"VAR_{branch}" if not str(branch).startswith("VAR_") else str(branch)] = value
        realization = match_realization(model, candidate, input_realization)
        if realization["status"] != "ok":
            blocked.append(
                {
                    "candidate_id": candidate.get("id") or f"CAND_{idx:04d}",
                    "status": "realize_blocked",
                    "reason": realization["reason"],
                    "model": model,
                }
            )
            continue
        row = build_case_row(candidate, model, realization, idx)
        rows.append(row)

    report = {
        "version": 1,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "test_level": level,
        "case_name": case_name,
        "selected_count": len(selected_candidates),
        "realized_count": len(rows),
        "blocked_count": len(blocked),
        "blocked": blocked,
        "csv_path": "",
        "report_path": "",
        "dry_run": dry_run,
    }
    cases_dir = out_root / "cases"
    if level:
        level = str(level).upper()
        cases_dir = cases_dir / "levels" / level
    cases_dir.mkdir(parents=True, exist_ok=True)
    csv_stem = safe_case_name(case_name or (level if level else "cases"))
    report_path = cases_dir / ("realize_report.yaml" if not level and not case_name else f"{csv_stem}.realize_report.yaml")
    report["report_path"] = report_path.as_posix()
    write_yaml(report_path, report)
    if dry_run:
        rows_path = cases_dir / ("realized_rows.yaml" if not level and not case_name else f"{csv_stem}.realized_rows.yaml")
        write_yaml(rows_path, {"rows": rows})
        return report
    csv_path = cases_dir / f"{csv_stem}.csv"
    write_cases_csv(csv_path, rows)
    report["csv_path"] = csv_path.as_posix()
    write_yaml(report_path, report)
    return report


def safe_case_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value).strip())
    return safe.strip("_") or "cases"


def match_realization(model: dict[str, Any], candidate: dict[str, Any], input_realization: dict[str, Any]) -> dict[str, Any]:
    hints = _as_dict(candidate.get("realization_hints"))
    expected_key = _as_dict(hints.get("expected_tiling_key") or candidate.get("expected_tiling_key"))
    # Prefer explicit shape from matched realization rules
    matched_refs: list[str] = []
    shapes: list[Any] = []
    for rid, rule in sorted(input_realization.items()):
        if not isinstance(rule, dict):
            continue
        if realization_matches_model(model, expected_key, rule):
            matched_refs.append(str(rid))
            shape = rule.get("shape") or rule.get("minimal_shape") or rule.get("shape_intent") or _as_dict(rule.get("realize")).get("shape")
            if shape:
                shapes.append(shape)
    if len(matched_refs) > 1 and len({stable_hash(s) for s in shapes}) > 1:
        return {"status": "blocked", "reason": "ambiguous input_realization matches", "refs": matched_refs}
    if matched_refs and shapes:
        shape = shapes[0]
        if isinstance(shape, dict):
            return {"status": "ok", "reason": "", "refs": matched_refs, "shape": shape, "source": "input_realization"}
        # Non-dict shape intent: use defaults tagged by layout tokens
        return {"status": "ok", "reason": "", "refs": matched_refs, "shape": dict(DEFAULT_SHAPE), "source": "input_realization_default", "shape_intent": shape}
    if matched_refs and not shapes:
        # Matched rule but no shape — allow default smoke shape when model is otherwise complete
        return {"status": "ok", "reason": "", "refs": matched_refs, "shape": dict(DEFAULT_SHAPE), "source": "default_shape_with_realization_ref"}
    if not input_realization:
        # No realization catalog: emit defaults only for L0-like minimal models
        return {"status": "ok", "reason": "", "refs": [], "shape": dict(DEFAULT_SHAPE), "source": "default_shape_no_catalog"}
    return {"status": "blocked", "reason": "no matching input_realization / shape rule", "refs": []}


def realization_matches_model(model: dict[str, Any], expected_key: dict[str, Any], rule: dict[str, Any]) -> bool:
    matches = _as_dict(rule.get("matches"))
    pattern = _as_dict(matches.get("key_pattern") or matches.get("pattern") or rule.get("key_pattern") or rule.get("pattern"))
    direct = {k: v for k, v in matches.items() if k not in {"key_pattern", "pattern", "family_refs", "kernel_path_refs", "dtypes", "dtype", "layouts", "layout", "dtype_layout_classes", "dtype_layout_class", "optional_inputs"}}
    pattern = {**pattern, **direct}
    key_fields = expected_key or {k.removeprefix("VAR_KEY_"): v for k, v in model.items() if str(k).startswith("VAR_KEY_")}
    for key, value in pattern.items():
        actual = key_fields.get(key)
        if actual is None:
            actual = model.get(f"VAR_{key}") or model.get(f"VAR_KEY_{key}") or model.get(key)
        if _norm(actual) != _norm(value):
            return False
    layouts = [str(item).upper() for item in _as_list(matches.get("layouts") or matches.get("layout") or rule.get("layouts") or rule.get("layout"))]
    if layouts:
        layout = str(model.get("VAR_LAYOUT") or model.get("Input_Layout") or key_fields.get("layout") or "").upper()
        # Also infer from ISTND
        if not layout and model.get("VAR_KEY_ISTND") in (1, True, "1"):
            layout = "TND"
        if layout and layout not in layouts:
            return False
    return bool(pattern or layouts or matches.get("family_refs") or rule.get("dtype_layout_intent"))


def build_case_row(candidate: dict[str, Any], model: dict[str, Any], realization: dict[str, Any], idx: int) -> dict[str, Any]:
    shape = _as_dict(realization.get("shape"))
    dtype = _infer_dtype(model)
    layout = _infer_layout(model)
    is_deter = _infer_deter(model)
    name = str(candidate.get("id") or f"case_{idx:04d}")
    row = {col: "" for col in CSV_COLUMNS}
    row.update(
        {
            "Testcase_Name": name,
            "Enable": "Enable",
            "Dtype": dtype,
            "out_dtype": dtype,
            "Input_Layout": layout,
            "B": shape.get("B", DEFAULT_SHAPE["B"]),
            "N1": shape.get("N1", DEFAULT_SHAPE["N1"]),
            "N2": shape.get("N2", DEFAULT_SHAPE["N2"]),
            "S1": shape.get("S1", DEFAULT_SHAPE["S1"]),
            "S2": shape.get("S2", DEFAULT_SHAPE["S2"]),
            "D": shape.get("D", DEFAULT_SHAPE["D"]),
            "D_V": shape.get("D_V", shape.get("D", DEFAULT_SHAPE["D_V"])),
            "Drop_Out_Possibility": shape.get("Drop_Out_Possibility", 1),
            "Pre_Tockens": shape.get("Pre_Tockens", 65536),
            "Next_Tockens": shape.get("Next_Tockens", 65536),
            "Atten_mask_dtype": "bool",
            "Atten_mask_shape": shape.get("Atten_mask_shape", "NONE"),
            "sparse_mode": shape.get("sparse_mode", 0),
            "PSE_type": shape.get("PSE_type", 0),
            "PSE_shape": shape.get("PSE_shape", "NONE"),
            "eod": 0,
            "same_as_input": 0,
            "seed": 2,
            "offset": 0,
            "is_deter": "true" if is_deter else "false",
            "rope": int(model.get("VAR_KEY_ISROPE") in (1, True, "1")),
            "inner_drop": 0,
            "is_sink": 0,
            "prefix": "",
        }
    )
    if layout == "TND":
        b = int(row["B"])
        s1 = int(row["S1"])
        # cumulative-style simple seqlens
        row["seqlens_list_q"] = str([s1 // b * (i + 1) for i in range(b)])
        row["seqlens_list_kv"] = row["seqlens_list_q"]
    return row


def write_cases_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})


def _infer_dtype(model: dict[str, Any]) -> str:
    raw = model.get("VAR_DTYPE_LAYOUT_CLASS") or model.get("VAR_KEY_INPUTDTYPE") or model.get("Dtype")
    text = str(raw or "fp16").upper()
    tokens = set(text.replace("-", "_").split("_"))
    if "BF16" in tokens or "BF16" in text:
        return "bf16"
    if "FP32" in tokens or "FP32" in text:
        return "fp32"
    if "FP16" in tokens or "FP16" in text:
        return "fp16"
    if str(raw) in {"0", "1", "2", "3"}:
        return {"0": "fp16", "1": "bf16", "2": "fp32"}.get(str(raw), "fp16")
    return "fp16"


def _infer_layout(model: dict[str, Any]) -> str:
    if model.get("VAR_KEY_ISTND") in (1, True, "1"):
        return "TND"
    raw = str(model.get("VAR_DTYPE_LAYOUT_CLASS") or model.get("Input_Layout") or "BNSD").upper()
    for layout in ("TND", "BNSD", "BSND", "BSH", "SBH", "ND", "NZ"):
        if layout in raw:
            return "BNSD" if layout == "ND" else layout
    return "BNSD"


def _infer_deter(model: dict[str, Any]) -> bool:
    if model.get("VAR_KEY_DETERTYPE") not in (None, 0, "0", False):
        try:
            return int(model.get("VAR_KEY_DETERTYPE")) > 0
        except (TypeError, ValueError):
            return True
    return model.get("VAR_KVAR_IS_DETER_OLD") in (1, True, "1") or model.get("VAR_KVAR_IS_DETER_NEW") in (1, True, "1")


def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value) if not isinstance(value, bool) else value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1"}:
            return True
        if text in {"false", "0"}:
            return False
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]
