#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1/P2: rebuild FAG KB and emit chain_break_report."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UO_SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(UO_SRC))

from uo_init import paths  # noqa: E402

DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

OP = paths.op_dir(relative=DEFAULT_OPERATOR)
CANN = paths.cann_root()
OPS = paths.ops_root()
DEBUG = ROOT / "docs" / "debug" / "uo-tg-closure"


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def probe(uo: Path) -> dict:
    from uo_init.op_spec import discover
    from uo_init.tpl_dsl import expand_legal_instances, parse_file

    spec = discover(OP)
    schema = parse_file(spec.tiling_key_header) if spec.tiling_key_header else None
    legal = expand_legal_instances(schema) if schema else []
    breaks = []

    def add(bid: str, severity: str, script_fixable: bool, detail: str) -> None:
        breaks.append(
            {
                "id": bid,
                "severity": severity,
                "script_fixable": script_fixable,
                "detail": detail,
            }
        )

    key_space = _load_yaml(uo / "tiling" / "key_space.yaml")
    exhaustive = _load_yaml(uo / "tiling" / "exhaustive_key_space.yaml")
    coverage = _load_yaml(uo / "tiling" / "coverage_model.yaml")
    variables = _load_yaml(uo / "tiling" / "variables.yaml")
    constraints = _load_yaml(uo / "tiling" / "constraints.yaml")
    reach = _load_yaml(uo / "tiling" / "key_reachability.yaml")
    branches = _load_yaml(uo / "kernel" / "branches.yaml")
    quality = _load_yaml(uo / "quality.yaml")
    integrity = _load_yaml(uo / "checks" / "integrity.yaml")

    dims = key_space.get("dimensions") or []
    fields = key_space.get("fields") or {}
    if not dims and not fields:
        add("KEY_SPACE_EMPTY", "blocking", True, "key_space missing dimensions/fields")
    blocks = exhaustive.get("template_blocks") or []
    product_sum = sum(int(b.get("product_count") or 0) for b in blocks)
    declared = (
        exhaustive.get("legal_key_count")
        or key_space.get("legal_key_count")
        or coverage.get("legal_key_count")
        or (product_sum if product_sum else None)
    )
    if declared is not None and len(legal) != int(declared):
        add(
            "LEGAL_COUNT",
            "blocking",
            True,
            f"legal={len(legal)} declared={int(declared)}",
        )
    if not blocks:
        add("TEMPLATE_BLOCKS_EMPTY", "blocking", True, "exhaustive.template_blocks empty")
    elif abs(product_sum - len(legal)) > 0:
        add(
            "PRODUCT_SUM_MISMATCH",
            "blocking",
            True,
            f"sum(product_count)={product_sum} legal={len(legal)}",
        )
    kfo = coverage.get("key_field_obligations") or {}
    if not kfo:
        add("COVERAGE_KFO_EMPTY", "blocking", True, "coverage_model.key_field_obligations empty")
    if coverage.get("status") == "extracted" and not kfo:
        add("COVERAGE_FALSE_EXTRACTED", "blocking", True, "status=extracted but empty obligations")
    if not (variables.get("domains") or variables.get("variables") or variables.get("nodes")):
        add("VARIABLES_EMPTY", "blocking", True, "tiling/variables empty")
    if not (constraints.get("input_realization") or constraints.get("relations")):
        add("CONSTRAINTS_THIN", "warning", True, "constraints missing relations/input_realization")
    keys = reach.get("keys") or []
    if len(keys) != len(legal):
        add(
            "REACHABILITY_COUNT",
            "blocking",
            True,
            f"key_reachability={len(keys)} legal={len(legal)}",
        )
    missing_reason = sum(1 for k in keys if not k.get("reason_code"))
    if missing_reason:
        add("REACHABILITY_REASON", "blocking", True, f"{missing_reason} keys missing reason_code")
    branch_list = branches.get("branches") or []
    if not branch_list and not (branches.get("nodes") or []):
        add("KERNEL_BRANCHES_EMPTY", "warning", True, "kernel/branches empty")
    if not (uo / "indexes" / "kb_graph.sqlite").is_file():
        add("SQLITE_MISSING", "blocking", True, "indexes/kb_graph.sqlite missing")
    if integrity.get("status") not in (None, "pass") and integrity.get("ok") is False:
        add("INTEGRITY_FAIL", "blocking", True, str(integrity.get("errors")))

    # FastEncode sample
    sample_ok = 0
    if schema and legal:
        for inst in legal[:50]:
            full = {d.name: str(inst.get(d.name, d.value_domain[0])) for d in schema.dims}
            key = schema.encode_tiling_key(full)
            dec = schema.decode_tiling_key(key)
            if all(dec[n] == full[n] for n in full):
                sample_ok += 1
        if sample_ok != min(50, len(legal)):
            add("ENCODE_ROUNDTRIP", "blocking", True, f"sample_ok={sample_ok}/50")

    blocking = [b for b in breaks if b["severity"] == "blocking"]
    return {
        "legal_instances": len(legal),
        "template_blocks": len(blocks),
        "key_reachability": len(keys),
        "branch_rows": len(branch_list),
        "quality": {
            "source_closure": quality.get("source_closure"),
            "input_controllability": quality.get("input_controllability"),
            "blocker_count": quality.get("blocker_count"),
        },
        "integrity_status": integrity.get("status"),
        "breaks": breaks,
        "blocking_count": len(blocking),
        "encode_sample_ok": f"{sample_ok}/50" if schema else "n/a",
        "declared_key_count": declared,
        "gate_pass": len(blocking) == 0,
    }


def main() -> int:
    if OP is None or CANN is None or OPS is None:
        print(
            f"operator sources, CANN or ops-transformer not available\n{paths.explain()}",
            file=sys.stderr,
        )
        return 1
    DEBUG.mkdir(parents=True, exist_ok=True)
    from uo_init.assemble_kb import export_operator_closure
    from uo_init.pilot_engines import prepare_layout, scope_confirm, scope_scan

    ctx = {"run_id": "uo_tg_closure_1", "force_confirm": True}
    t0 = time.time()
    prep = prepare_layout(OP, ctx)
    scan = scope_scan(OP, ctx)
    conf = scope_confirm(OP, ctx)
    print(
        json.dumps(
            {
                "prepare": prep.get("ok"),
                "layout_reset": prep.get("layout_reset"),
                "scope_scan": scan.get("ok"),
                "scope_confirm": conf.get("ok"),
            },
            ensure_ascii=False,
        )
    )
    receipt = export_operator_closure(
        op_dir=OP,
        cann_root=str(CANN),
        ops_root=str(OPS),
        fold_kernel=True,
        harness_workers=6,
    )
    elapsed = round(time.time() - t0, 1)
    uo = OP / ".ascendc-pilot" / "uo"
    report = probe(uo)
    report["elapsed_s"] = elapsed
    report["export_receipt"] = {
        k: receipt.get(k)
        for k in (
            "ok",
            "source_closure",
            "blocker_count",
            "kernel_branch_count",
            "legal_key_count",
            "template_block_count",
            "materialize_ok",
            "kernel_fold",
        )
    }
    out_yaml = uo / "tiling" / "chain_break_report.yaml"
    out_yaml.write_text(
        yaml.safe_dump(report, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )

    rebuild_md = DEBUG / "01_kb_rebuild.md"
    rebuild_md.write_text(
        "\n".join(
            [
                "# P1 KB rebuild",
                "",
                f"- elapsed_s: {elapsed}",
                f"- export ok: {receipt.get('ok')}",
                f"- source_closure: {receipt.get('source_closure')}",
                f"- blocker_count: {receipt.get('blocker_count')}",
                f"- kernel_branch_count: {receipt.get('kernel_branch_count')}",
                f"- legal_key_count: {receipt.get('legal_key_count')}",
                f"- template_block_count: {receipt.get('template_block_count')}",
                f"- materialize_ok: {receipt.get('materialize_ok')}",
                f"- fold: {receipt.get('kernel_fold')}",
                f"- top: {sorted(p.name for p in uo.iterdir())}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    breaks_md = DEBUG / "02_kb_chain_break.md"
    lines = [
        "# P2 KB chain break",
        "",
        f"- gate_pass: {report['gate_pass']}",
        f"- blocking_count: {report['blocking_count']}",
        f"- legal_instances: {report['legal_instances']}",
        f"- encode_sample_ok: {report['encode_sample_ok']}",
        "",
        "| id | severity | script_fixable | detail |",
        "|----|----------|-----------------|--------|",
    ]
    for b in report["breaks"]:
        lines.append(
            f"| {b['id']} | {b['severity']} | {b['script_fixable']} | {b['detail']} |"
        )
    if not report["breaks"]:
        lines.append("| (none) | | | |")
    lines.extend(
        [
            "",
            "根因：此前 assemble/export 未 materialize KEY/template_blocks/coverage → 空壳 extracted。",
            "修复手段：script（materialize_tiling + kb_export 契约视图）。",
            f"验证：`python scripts/uo_tg_rebuild_and_probe.py` → chain_break_report.yaml",
            f"结果：gate_pass={report['gate_pass']}",
            "",
        ]
    )
    breaks_md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
