#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build/audit FlashAttentionScoreGrad arch35 from current source only."""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from uo_init.build import compile_codemap
from uo_init.diagnostics.audit import audit_uo
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.reader import read_codemap
from uo_init.store.writer import write_codemap

OP_NAME = "flash_attention_score_grad"
ARCH = "arch35"
EXPECTED_KEY_COUNT = 19
COLD_ANALYSIS_BUDGET_SECONDS = 300.0
CRITICAL_PRODUCERS = {
    "IsNzOut": {"lhs": "fBaseParams.isNzOut", "file": "flash_attention_score_grad_tiling_normal_regbase.cpp"},
    "IsTndSwizzle": {"lhs": "tndBaseInfo.isTndSwizzle", "file": "flash_attention_score_grad_tiling_normal_regbase.cpp"},
    "SplitAxis": {"lhs": "splitAxis", "file": "flash_attention_score_grad_tiling_normal_regbase.cpp"},
    "S1TemplateNum": {"lhs": "fBaseParams.s1TemplateType", "file": "flash_attention_score_grad_tiling_common_regbase.cpp"},
    "S2TemplateNum": {"lhs": "fBaseParams.s2TemplateType", "file": "flash_attention_score_grad_tiling_common_regbase.cpp"},
    "DTemplateNum": {"lhs": "fBaseParams.dTemplateType", "file": "flash_attention_score_grad_tiling_common_regbase.cpp"},
}
_BOUND_CALLS = {
    "source_kernel_call_bound_v2", "source_kernel_macro_call_bound_v2",
    "source_kernel_call_bound_v3", "source_kernel_call_dispatch_set_v3",
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


def _kernel_reachable(cm: Any) -> set[str]:
    starts = {e.id for e in cm.by_kind(EntityKind.KERNEL) if e.attrs.get("source_signature")}
    adj: dict[str, set[str]] = defaultdict(set)
    for rel in cm.relations.values():
        if rel.kind_name() == RelationKind.CALLS.value and str(rel.attrs.get("provenance") or "") in _BOUND_CALLS:
            adj[rel.src].add(rel.dst)
    seen = set(starts)
    q = deque(starts)
    while q:
        cur = q.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt); q.append(nxt)
    return seen


def _fresh_soundness_checks(uo: Path, binary: dict[str, Any], analysis_seconds: float) -> list[dict[str, Any]]:
    cm = read_codemap(uo)
    blocking: list[dict[str, Any]] = []
    summary = binary.get("summary") or {}
    expected = f"{EXPECTED_KEY_COUNT}/{EXPECTED_KEY_COUNT}"
    for field in (
        "tiling_key_declaration_coverage", "tiling_key_host_packing_coverage",
        "tiling_key_host_producer_coverage", "tiling_key_root_coverage",
    ):
        if summary.get(field) != expected:
            blocking.append({"code":"FRESH_KEY_COVERAGE_FAILED","detail":f"{field}={summary.get(field)!r}, expected {expected}"})

    evidence = {row.get("key"): row for row in (binary.get("tiling_key_evidence") or []) if isinstance(row, dict)}
    for key, expected_producer in sorted(CRITICAL_PRODUCERS.items()):
        row = evidence.get(key) or {}
        sites = [site for site in (row.get("producer_sites") or []) if isinstance(site, dict)]
        matching = [site for site in sites if str(site.get("lhs") or "") == expected_producer["lhs"]
                    and Path(str(site.get("file") or "")).name == expected_producer["file"]
                    and str(site.get("file") or "").lower().endswith(".cpp")]
        if not row.get("producer") or not row.get("rooted") or not matching:
            blocking.append({"code":"CRITICAL_KEY_PRODUCER_MISSING","detail":f"{key} must be produced by {expected_producer['lhs']} in {expected_producer['file']}","evidence":row})
        if "." in expected_producer["lhs"]:
            bare = expected_producer["lhs"].split(".")[-1]
            bad = [site for site in sites if str(site.get("lhs") or "") == bare or str(site.get("file") or "").lower().endswith((".h",".hpp",".hh"))]
            if bad:
                blocking.append({"code":"CRITICAL_KEY_FALSE_PRODUCER","detail":f"{key} contains declaration/short-name producer pollution","bad_sites":bad})

    synthetic_branch_roots = [e.id for e in cm.by_kind(EntityKind.COMPILE_VAR)
        if e.attrs.get("from_branch") and not e.attrs.get("compile_root") and not str(e.attrs.get("provenance") or "").startswith("source_")]
    if synthetic_branch_roots:
        blocking.append({"code":"SYNTHETIC_BRANCH_COMPILE_ROOT","detail":"uppercase branch spellings were promoted to compile roots","examples":synthetic_branch_roots[:20]})
    if "input_root" in list(cm.meta.get("passes_run") or []):
        blocking.append({"code":"RETIRED_DERIVED_KEY_PASS_ACTIVE","detail":"fresh structural pipeline still runs legacy input_root/derive_key_fields adapter"})

    meta_text = json.dumps(cm.meta, ensure_ascii=False, sort_keys=True)
    if "archive_import" in meta_text or "understand-operator.zip" in meta_text or "historical_understand_operator" in meta_text:
        blocking.append({"code":"HISTORICAL_FACT_LEAK","detail":"fresh audit graph contains archive/historical import metadata"})

    closure = dict(cm.meta.get("kernel_tiling_closure") or {})
    if not closure:
        blocking.append({"code":"MISSING_KERNEL_TILING_CLOSURE","detail":"verified Kernel/TilingData closure metadata is absent"})
    else:
        if not closure.get("architecture_pure"):
            blocking.append({"code":"KERNEL_ARCHITECTURE_POLLUTION","detail":"selected arch35 Kernel graph retains foreign source facts","closure":closure})
        if int(closure.get("kernel_entries") or 0) != 1:
            blocking.append({"code":"KERNEL_ENTRY_MISMATCH","detail":f"expected one arch35 Kernel entry, got {closure.get('kernel_entries')}"})
        if int(closure.get("kernel_template_args") or 0) != EXPECTED_KEY_COUNT:
            blocking.append({"code":"KERNEL_TEMPLATE_BINDING_MISMATCH","detail":f"kernel template args={closure.get('kernel_template_args')}, expected {EXPECTED_KEY_COUNT}"})
        if int(closure.get("kernel_abi_links") or 0) <= 0:
            blocking.append({"code":"MISSING_KERNEL_ABI","detail":"no verified arch35 API↔Kernel ABI links"})
        if int(closure.get("kernel_reachable_scopes") or 0) <= 1:
            blocking.append({"code":"KERNEL_CALL_GRAPH_NOT_REACHABLE","detail":"Kernel entry does not reach implementation scopes"})
        if int(closure.get("kernel_reachable_unresolved_internal_call_sites") or 0) != 0:
            blocking.append({"code":"UNCLASSIFIED_KERNEL_CALL_FRONTIER","detail":f"reachable unclassified internal calls={closure.get('kernel_reachable_unresolved_internal_call_sites')}"})
        if int(closure.get("tiling_ambiguous_writer_sites") or 0) != 0:
            blocking.append({"code":"AMBIGUOUS_TILINGDATA_WRITER","detail":f"ambiguous writer sites={closure.get('tiling_ambiguous_writer_sites')}"})
        if int(closure.get("tiling_entry_reachable_unresolved_read_sites") or 0) != 0:
            blocking.append({"code":"AMBIGUOUS_TILINGDATA_READ","detail":f"entry-reachable unresolved reads={closure.get('tiling_entry_reachable_unresolved_read_sites')}"})
        if int(closure.get("tiling_entry_reachable_fields") or 0) <= 0:
            blocking.append({"code":"NO_REACHABLE_TILINGDATA_FIELDS","detail":"no verified TilingData field read is reachable from Kernel entry"})
        missing_producers = list(closure.get("tiling_consumed_fields_without_producer") or [])
        if missing_producers:
            blocking.append({"code":"TILINGDATA_CONSUMER_WITHOUT_HOST_PRODUCER","detail":f"{len(missing_producers)} entry-reachable consumed fields have no Host writer/default","fields":missing_producers[:100]})
        if not closure.get("strict_closure_ok"):
            blocking.append({"code":"KERNEL_TILING_STRICT_CLOSURE_FAILED","detail":"verified Kernel/TilingData closure invariant is false","closure":closure})

    reachable = _kernel_reachable(cm)
    regbase = [e.id for e in cm.entities.values() if e.name == "RegbaseFAG" and e.attrs.get("source_definition")]
    if not regbase or not any(eid in reachable for eid in regbase):
        blocking.append({"code":"FAG_ENTRY_IMPLEMENTATION_UNREACHABLE","detail":"flash_attention_score_grad does not reach source-defined RegbaseFAG"})

    # The old arch22 top-level entry is in the same directory and used to leak
    # into arch35 because broad scanning accepted any __aicore__ file.
    bad_kernel_facts = []
    for rel in cm.relations.values():
        file = str(rel.attrs.get("file") or "").replace("\\","/")
        prov = str(rel.attrs.get("provenance") or "")
        if file.endswith("/op_kernel/flash_attention_score_grad.cpp") and prov.startswith("source_kernel"):
            bad_kernel_facts.append(rel.id)
    if bad_kernel_facts:
        blocking.append({"code":"ARCH22_TOPLEVEL_KERNEL_LEAK","detail":"arch35 graph contains verified Kernel facts from flash_attention_score_grad.cpp","examples":bad_kernel_facts[:20]})

    if analysis_seconds > COLD_ANALYSIS_BUDGET_SECONDS:
        blocking.append({"code":"COLD_ANALYSIS_BUDGET_EXCEEDED","detail":f"cold analysis {analysis_seconds:.3f}s exceeds {COLD_ANALYSIS_BUDGET_SECONDS:.0f}s"})
    return blocking


def run(operator: Path, out_dir: Path) -> dict[str, Any]:
    operator = operator.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (operator / "op_host" / ARCH).is_dir():
        raise FileNotFoundError(f"missing current arch35 host source: {operator / 'op_host' / ARCH}")

    started = time.perf_counter()
    result = compile_codemap(op_name=OP_NAME, architecture=ARCH, op_root=operator, host_ir=None, kernel_ir=None,
                             declared={}, key_fields=[], commit=False)
    analysis_seconds = time.perf_counter() - started
    product = out_dir / f"{OP_NAME}.{ARCH}.uo"
    write_codemap(result["codemap"], product)

    binary = audit_uo(product)
    source = _arch35_source_check(operator, product)
    blocking = list(binary.get("blocking") or [])
    blocking.extend(_fresh_soundness_checks(product, binary, analysis_seconds))
    if not source["ok"]:
        blocking.append({"code":"ARCH35_SOURCE_CROSSCHECK_FAILED","detail":"retained CodeMap evidence is stale, foreign-arch, empty, or not scoped to arch35","source":source})

    report = {
        "ok": not blocking,
        "mode": "fresh-current-source-structural-compiler",
        "fresh_source_graph": True,
        "historical_archive_used": False,
        "compiler_ir_used": False,
        "cold_analysis_seconds": round(analysis_seconds, 6),
        "cold_analysis_budget_seconds": COLD_ANALYSIS_BUDGET_SECONDS,
        "operator": str(operator), "product": str(product), "binary": binary,
        "kernel_tiling_closure": dict(result["codemap"].meta.get("kernel_tiling_closure") or {}),
        "source_crosscheck": source, "blocking": blocking,
    }
    (out_dir / "arch35-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    counts = binary.get("counts") or {}; summary = binary.get("summary") or {}; closure = report["kernel_tiling_closure"]
    lines = [
        "# FlashAttentionScoreGrad arch35 fresh UO audit", "",
        f"- ok: `{report['ok']}`", f"- mode: `{report['mode']}`",
        f"- historical archive used: `{report['historical_archive_used']}`",
        f"- cold analysis: `{analysis_seconds:.3f}s / {COLD_ANALYSIS_BUDGET_SECONDS:.0f}s`",
        f"- product: `{product.name}`", f"- entities / relations: `{summary.get('entity_count')}` / `{summary.get('relation_count')}`",
        f"- TilingKey declaration / packing / producer / root: `{summary.get('tiling_key_declaration_coverage')}` / `{summary.get('tiling_key_host_packing_coverage')}` / `{summary.get('tiling_key_host_producer_coverage')}` / `{summary.get('tiling_key_root_coverage')}`",
        f"- dependency skeleton complete: `{summary.get('tiling_key_dependency_coverage')}`",
        f"- Kernel entry / template args / ABI: `{closure.get('kernel_entries')}` / `{closure.get('kernel_template_args')}` / `{closure.get('kernel_abi_links')}`",
        f"- Kernel reachable scopes / call boundaries / unclassified calls: `{closure.get('kernel_reachable_scopes')}` / `{closure.get('kernel_reachable_call_boundary_sites')}` / `{closure.get('kernel_reachable_unresolved_internal_call_sites')}`",
        f"- TilingData classes / fields: `{counts.get('tiling_data')}` / `{counts.get('tiling_fields')}`",
        f"- TilingData reachable read fields / unresolved reads: `{closure.get('tiling_entry_reachable_fields')}` / `{closure.get('tiling_entry_reachable_unresolved_read_sites')}`",
        f"- TilingData consumed-field producer coverage: `{closure.get('tiling_consumed_field_producer_coverage')}`",
        f"- strict Kernel/TilingData closure: `{closure.get('strict_closure_ok')}`",
        f"- blocking: `{len(blocking)}`", f"- warnings: `{len(binary.get('warnings') or [])}`", "", "## Critical producer sites", "",
    ]
    evidence = {row.get("key"): row for row in (binary.get("tiling_key_evidence") or []) if isinstance(row, dict)}
    for key in sorted(CRITICAL_PRODUCERS):
        row = evidence.get(key) or {}; sites = row.get("producer_sites") or []
        lines.append(f"- `{key}`: producer=`{row.get('producer')}`, rooted=`{row.get('rooted')}`, sites=`{sites[:6]}`")
    lines += ["", "## Blocking", ""]
    lines.extend(f"- `{item.get('code')}`: {item.get('detail')}" for item in blocking) if blocking else lines.append("- none")
    lines += ["", "## Binary warnings", ""]
    warnings = binary.get("warnings") or []
    lines.extend(f"- `{item.get('code')}`: {item.get('detail')}" for item in warnings) if warnings else lines.append("- none")
    (out_dir / "arch35-audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--operator", type=Path, required=True); parser.add_argument("--out-dir", type=Path, default=Path("artifacts/uo-arch35")); args = parser.parse_args()
    try:
        report = run(args.operator, args.out_dir)
    except Exception as exc:  # noqa: BLE001
        args.out_dir.mkdir(parents=True, exist_ok=True)
        failure = {"ok":False,"error":str(exc),"architecture":ARCH}
        (args.out_dir / "arch35-audit.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False, indent=2)); return 2
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
