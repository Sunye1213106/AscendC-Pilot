#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build/audit FlashAttentionScoreGrad arch35 from *current source only*.

This is the real-source regression gate for the structural CodeMap compiler. It
must not import ``.understand-operator.zip`` or any historical Host derivation.
The GitHub runner has no CANN SDK, so compiler-enriched IR is absent; the same
current-source passes used by production ``compile_codemap`` must nevertheless
recover the API/Host packing/TilingData/Kernel graph and all 19 TilingKey
producer roots.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from uo_init.build import compile_codemap
from uo_init.diagnostics.audit import audit_uo
from uo_init.ir.entity import EntityKind
from uo_init.store.reader import read_codemap
from uo_init.store.writer import write_codemap

OP_NAME = "flash_attention_score_grad"
ARCH = "arch35"
EXPECTED_KEY_COUNT = 19
# These identities are deliberately source-level, not values/formulas. They
# catch the exact regressions that previously made the graph green through a
# header initializer or unrelated branch constant.
CRITICAL_PRODUCERS = {
    "IsNzOut": {"lhs": "fBaseParams.isNzOut", "file": "flash_attention_score_grad_tiling_normal_regbase.cpp"},
    "IsTndSwizzle": {"lhs": "tndBaseInfo.isTndSwizzle", "file": "flash_attention_score_grad_tiling_normal_regbase.cpp"},
    "SplitAxis": {"lhs": "splitAxis", "file": "flash_attention_score_grad_tiling_normal_regbase.cpp"},
    "S1TemplateNum": {"lhs": "fBaseParams.s1TemplateType", "file": "flash_attention_score_grad_tiling_common_regbase.cpp"},
    "S2TemplateNum": {"lhs": "fBaseParams.s2TemplateType", "file": "flash_attention_score_grad_tiling_common_regbase.cpp"},
    "DTemplateNum": {"lhs": "fBaseParams.dTemplateType", "file": "flash_attention_score_grad_tiling_common_regbase.cpp"},
}


def _source_files(cm: Any) -> set[str]:
    files = {str(e.file) for e in cm.entities.values() if str(e.file or "").strip()}
    for rel in cm.relations.values():
        f = rel.attrs.get("file")
        if f:
            files.add(str(f))
    return files


def _relative_to_operator(path: str) -> str:
    norm = path.replace("\\", "/").lstrip("./")
    prefix = OP_NAME + "/"
    return norm[len(prefix):] if norm.startswith(prefix) else norm


def _arch35_source_check(operator: Path, uo: Path) -> dict[str, Any]:
    cm = read_codemap(uo)
    files = _source_files(cm)
    host_dir = operator / "op_host" / ARCH
    kernel_dir = operator / "op_kernel" / ARCH
    expected_host = sorted(p.name for p in host_dir.glob("*.cpp")) if host_dir.is_dir() else []
    expected_kernel = sorted(
        p.name for p in kernel_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".cpp", ".h", ".hpp"}
    ) if kernel_dir.is_dir() else []
    foreign_arch = sorted(
        f for f in files
        if any(token in f.replace("\\", "/").lower() for token in ("/arch22/", "/arch32/", "/arch40/"))
    )
    stale_evidence: list[str] = []
    existing_evidence: list[str] = []
    for f in sorted(files):
        rel = _relative_to_operator(f)
        candidate = operator / rel
        if candidate.is_file():
            existing_evidence.append(f)
        else:
            stale_evidence.append(f)
    host_evidence = {Path(_relative_to_operator(f)).name for f in files if "/op_host/" in f.replace("\\", "/")}
    kernel_evidence = {Path(_relative_to_operator(f)).name for f in files if "/op_kernel/" in f.replace("\\", "/")}
    matched_host = sorted(set(expected_host) & host_evidence)
    matched_kernel = sorted(set(expected_kernel) & kernel_evidence)
    return {
        "architecture": cm.architecture,
        "source_evidence_files": len(files),
        "existing_evidence_files": len(existing_evidence),
        "stale_evidence_files": stale_evidence[:100],
        "expected_host_files": expected_host,
        "matched_host_files": matched_host,
        "current_host_files_without_evidence": sorted(set(expected_host) - host_evidence),
        "expected_kernel_file_count": len(expected_kernel),
        "matched_kernel_file_count": len(matched_kernel),
        "foreign_arch_evidence": foreign_arch[:50],
        "ok": cm.architecture == ARCH and not foreign_arch and not stale_evidence and bool(files),
    }


def _fresh_soundness_checks(uo: Path, binary: dict[str, Any]) -> list[dict[str, Any]]:
    cm = read_codemap(uo)
    blocking: list[dict[str, Any]] = []
    summary = binary.get("summary") or {}
    expected = f"{EXPECTED_KEY_COUNT}/{EXPECTED_KEY_COUNT}"
    for field in (
        "tiling_key_declaration_coverage",
        "tiling_key_host_packing_coverage",
        "tiling_key_host_producer_coverage",
        "tiling_key_root_coverage",
    ):
        if summary.get(field) != expected:
            blocking.append({"code": "FRESH_KEY_COVERAGE_FAILED", "detail": f"{field}={summary.get(field)!r}, expected {expected}"})

    evidence = {row.get("key"): row for row in (binary.get("tiling_key_evidence") or []) if isinstance(row, dict)}
    for key, expected_producer in sorted(CRITICAL_PRODUCERS.items()):
        row = evidence.get(key) or {}
        sites = [site for site in (row.get("producer_sites") or []) if isinstance(site, dict)]
        matching = [
            site for site in sites
            if str(site.get("lhs") or "") == expected_producer["lhs"]
            and Path(str(site.get("file") or "")).name == expected_producer["file"]
            and str(site.get("file") or "").lower().endswith(".cpp")
        ]
        if not row.get("producer") or not row.get("rooted") or not matching:
            blocking.append(
                {
                    "code": "CRITICAL_KEY_PRODUCER_MISSING",
                    "detail": f"{key} must be produced by {expected_producer['lhs']} in {expected_producer['file']}",
                    "evidence": row,
                }
            )
        # Member-backed critical keys must never pick up the bare declaration
        # initializer that caused the old short-name ambiguity.
        if "." in expected_producer["lhs"]:
            bare = expected_producer["lhs"].split(".")[-1]
            bad = [
                site for site in sites
                if str(site.get("lhs") or "") == bare
                or str(site.get("file") or "").lower().endswith((".h", ".hpp", ".hh"))
            ]
            if bad:
                blocking.append(
                    {
                        "code": "CRITICAL_KEY_FALSE_PRODUCER",
                        "detail": f"{key} contains declaration/short-name producer pollution",
                        "bad_sites": bad,
                    }
                )

    synthetic_branch_roots = [
        e.id for e in cm.by_kind(EntityKind.COMPILE_VAR)
        if e.attrs.get("from_branch") and not e.attrs.get("compile_root") and not str(e.attrs.get("provenance") or "").startswith("source_")
    ]
    if synthetic_branch_roots:
        blocking.append(
            {
                "code": "SYNTHETIC_BRANCH_COMPILE_ROOT",
                "detail": "uppercase branch spellings were promoted to compile roots",
                "examples": synthetic_branch_roots[:20],
            }
        )

    if "input_root" in list(cm.meta.get("passes_run") or []):
        blocking.append(
            {
                "code": "RETIRED_DERIVED_KEY_PASS_ACTIVE",
                "detail": "fresh structural pipeline still runs legacy input_root/derive_key_fields adapter",
            }
        )

    meta_text = json.dumps(cm.meta, ensure_ascii=False, sort_keys=True)
    if "archive_import" in meta_text or "understand-operator.zip" in meta_text or "historical_understand_operator" in meta_text:
        blocking.append({"code": "HISTORICAL_FACT_LEAK", "detail": "fresh audit graph contains archive/historical import metadata"})
    return blocking


def run(operator: Path, out_dir: Path) -> dict[str, Any]:
    operator = operator.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (operator / "op_host" / ARCH).is_dir():
        raise FileNotFoundError(f"missing current arch35 host source: {operator / 'op_host' / ARCH}")

    result = compile_codemap(
        op_name=OP_NAME,
        architecture=ARCH,
        op_root=operator,
        host_ir=None,
        kernel_ir=None,
        declared={},
        key_fields=[],
        commit=False,
    )
    product = out_dir / f"{OP_NAME}.{ARCH}.uo"
    write_codemap(result["codemap"], product)

    binary = audit_uo(product)
    source = _arch35_source_check(operator, product)
    blocking = list(binary.get("blocking") or [])
    blocking.extend(_fresh_soundness_checks(product, binary))
    if not source["ok"]:
        blocking.append(
            {
                "code": "ARCH35_SOURCE_CROSSCHECK_FAILED",
                "detail": "retained CodeMap evidence is stale, foreign-arch, empty, or not scoped to arch35",
                "source": source,
            }
        )

    report = {
        "ok": not blocking,
        "mode": "fresh-current-source-structural-compiler",
        "fresh_source_graph": True,
        "historical_archive_used": False,
        "compiler_ir_used": False,
        "operator": str(operator),
        "product": str(product),
        "binary": binary,
        "source_crosscheck": source,
        "blocking": blocking,
    }
    (out_dir / "arch35-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    counts = binary.get("counts") or {}
    summary = binary.get("summary") or {}
    lines = [
        "# FlashAttentionScoreGrad arch35 fresh UO audit",
        "",
        f"- ok: `{report['ok']}`",
        f"- mode: `{report['mode']}`",
        f"- historical archive used: `{report['historical_archive_used']}`",
        f"- product: `{product.name}`",
        f"- entities / relations: `{summary.get('entity_count')}` / `{summary.get('relation_count')}`",
        f"- TilingKey declaration: `{summary.get('tiling_key_declaration_coverage')}`",
        f"- Host packing: `{summary.get('tiling_key_host_packing_coverage')}`",
        f"- Host producer: `{summary.get('tiling_key_host_producer_coverage')}`",
        f"- trusted root: `{summary.get('tiling_key_root_coverage')}`",
        f"- dependency skeleton complete: `{summary.get('tiling_key_dependency_coverage')}`",
        f"- API tensor inputs / attributes / outputs: `{counts.get('tensor_inputs')}` / `{counts.get('attributes')}` / `{counts.get('outputs')}`",
        f"- TilingData classes / fields: `{counts.get('tiling_data')}` / `{counts.get('tiling_fields')}`",
        f"- Kernels: `{counts.get('kernels')}`",
        f"- blocking: `{len(blocking)}`",
        f"- warnings: `{len(binary.get('warnings') or [])}`",
        "",
        "## Critical producer sites",
        "",
    ]
    evidence = {row.get("key"): row for row in (binary.get("tiling_key_evidence") or []) if isinstance(row, dict)}
    for key in sorted(CRITICAL_PRODUCERS):
        row = evidence.get(key) or {}
        sites = row.get("producer_sites") or []
        lines.append(f"- `{key}`: producer=`{row.get('producer')}`, rooted=`{row.get('rooted')}`, sites=`{sites[:6]}`")
    lines += ["", "## Blocking", ""]
    if blocking:
        lines.extend(f"- `{item.get('code')}`: {item.get('detail')}" for item in blocking)
    else:
        lines.append("- none")
    lines += ["", "## Binary warnings", ""]
    warnings = binary.get("warnings") or []
    if warnings:
        lines.extend(f"- `{item.get('code')}`: {item.get('detail')}" for item in warnings)
    else:
        lines.append("- none")
    (out_dir / "arch35-audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/uo-arch35"))
    args = parser.parse_args()
    try:
        report = run(args.operator, args.out_dir)
    except Exception as exc:  # noqa: BLE001
        args.out_dir.mkdir(parents=True, exist_ok=True)
        failure = {"ok": False, "error": str(exc), "architecture": ARCH}
        (args.out_dir / "arch35-audit.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
