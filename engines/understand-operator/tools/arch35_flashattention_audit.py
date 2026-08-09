#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build/audit FlashAttentionScoreGrad arch35 as a unified ``.uo``.

The GitHub runner has no installed CANN SDK, so the calibration combines the
historical structured UO archive with deterministic facts parsed from the
*current* operator source.  Current REG_OP, template-key, TilingData and Kernel
signatures override archive cardinality.  No free-text derivation is promoted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from uo_init.diagnostics.audit import audit_uo
from uo_init.store.reader import read_codemap
from uo_init.store.understand_archive import understand_archive_to_uo

OP_NAME = "flash_attention_score_grad"
ARCH = "arch35"


def _source_files(cm: Any) -> set[str]:
    files = {str(e.file) for e in cm.entities.values() if str(e.file or "").strip()}
    for rel in cm.relations.values():
        f = rel.attrs.get("file")
        if f:
            files.add(str(f))
        for ev in rel.attrs.get("evidence") or []:
            if isinstance(ev, dict) and ev.get("file"):
                files.add(str(ev["file"]))
    for ent in cm.entities.values():
        for key in ("evidence", "sources", "candidate_sources"):
            for ev in ent.attrs.get(key) or []:
                if isinstance(ev, dict) and ev.get("file"):
                    files.add(str(ev["file"]))
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
        p.name
        for p in kernel_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".cpp", ".h", ".hpp"}
    ) if kernel_dir.is_dir() else []

    foreign_arch = sorted(
        f
        for f in files
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

    host_evidence = {
        Path(_relative_to_operator(f)).name
        for f in files
        if "/op_host/" in f.replace("\\", "/")
    }
    kernel_evidence = {
        Path(_relative_to_operator(f)).name
        for f in files
        if "/op_kernel/" in f.replace("\\", "/")
    }
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


def run(operator: Path, archive: Path, out_dir: Path) -> dict[str, Any]:
    operator = operator.expanduser().resolve()
    archive = archive.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not archive.is_file():
        raise FileNotFoundError(f"missing archived UO facts: {archive}")
    if not (operator / "op_host" / ARCH).is_dir():
        raise FileNotFoundError(f"missing current arch35 host source: {operator / 'op_host' / ARCH}")

    product = out_dir / f"{OP_NAME}.{ARCH}.uo"
    imported = understand_archive_to_uo(
        archive,
        product,
        op_name=OP_NAME,
        architecture=ARCH,
        operator_root=operator,
    )

    binary = audit_uo(product)
    source = _arch35_source_check(operator, product)
    blocking = list(binary.get("blocking") or [])
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
        "mode": "historical-structured-facts+current-source-structural-enrichment",
        "fresh_clang_extraction": False,
        "operator": str(operator),
        "archive": str(archive),
        "product": str(product),
        "archive_import": imported,
        "binary": binary,
        "source_crosscheck": source,
        "blocking": blocking,
    }
    (out_dir / "arch35-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    counts = binary.get("counts") or {}
    lines = [
        "# FlashAttentionScoreGrad arch35 UO audit",
        "",
        f"- ok: `{report['ok']}`",
        f"- mode: `{report['mode']}`",
        f"- fresh Clang extraction: `{report['fresh_clang_extraction']}`",
        f"- product: `{product.name}`",
        f"- size_bytes: `{binary.get('size_bytes')}`",
        f"- entities / relations: `{(binary.get('summary') or {}).get('entity_count')}` / `{(binary.get('summary') or {}).get('relation_count')}`",
        f"- API tensor inputs / attributes / outputs: `{counts.get('tensor_inputs')}` / `{counts.get('attributes')}` / `{counts.get('outputs')}`",
        f"- TilingKeys: `{counts.get('tiling_keys')}` (current source declares `{counts.get('source_declared_tiling_keys')}`)",
        f"- TilingData classes / fields: `{counts.get('tiling_data')}` / `{counts.get('tiling_fields')}`",
        f"- Kernels: `{counts.get('kernels')}`",
        f"- unresolved entities: `{counts.get('unresolved_entities')}`",
        f"- exact archived runtime→key bindings: `{imported.get('archive_exact_runtime_bindings')}`",
        f"- INPUT→TILING_KEY→KERNEL: `{binary.get('evidence_backed_input_tilingkey_kernel_path')}`",
        f"- TILING_DATA→KERNEL: `{binary.get('evidence_backed_tilingdata_kernel_path')}`",
        f"- INPUT→KERNEL→OUTPUT: `{binary.get('evidence_backed_input_output_path')}`",
        f"- blocking: `{len(blocking)}`",
        f"- warnings: `{len(binary.get('warnings') or [])}`",
        "",
        "## Blocking",
        "",
    ]
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
    lines += [
        "",
        "## Source cross-check",
        "",
        f"- evidence files: `{source['source_evidence_files']}`",
        f"- existing evidence files: `{source['existing_evidence_files']}`",
        f"- stale evidence files: `{len(source['stale_evidence_files'])}`",
        f"- matched current arch35 host files: `{len(source['matched_host_files'])}/{len(source['expected_host_files'])}`",
        f"- matched current arch35 kernel files: `{source['matched_kernel_file_count']}/{source['expected_kernel_file_count']}`",
        f"- foreign arch evidence: `{len(source['foreign_arch_evidence'])}`",
        "",
        "> Current-source structural facts are authoritative for API, TilingKey cardinality, TilingData declarations and Kernel ABI. Historical prose remains diagnostic only. A local CANN/Clang run can add deeper compiler facts but must not change these source-declared contracts.",
    ]
    (out_dir / "arch35-audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/uo-arch35"))
    args = parser.parse_args()
    archive = args.archive or (args.operator / ".understand-operator.zip")
    try:
        report = run(args.operator, archive, args.out_dir)
    except Exception as exc:  # noqa: BLE001
        args.out_dir.mkdir(parents=True, exist_ok=True)
        failure = {"ok": False, "error": str(exc), "architecture": ARCH}
        (args.out_dir / "arch35-audit.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
