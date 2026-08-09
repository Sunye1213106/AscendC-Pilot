#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build/audit a new .uo from the real FlashAttentionScoreGrad arch35 archive.

The public GitHub runner has no CANN toolchain. The user's flashattention repo
therefore supplies its committed ``.understand-operator.zip`` as compiler-fact
input. This tool imports that real extracted graph into the new one-file UO
format and cross-checks the evidence against the *current* arch35 source tree.
It deliberately does not claim to be a fresh Clang extraction.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from uo_init.diagnostics.audit import audit_uo
from uo_init.store.legacy_import import legacy_db_to_uo
from uo_init.store.reader import read_codemap

OP_NAME = "flash_attention_score_grad"
ARCH = "arch35"


def _db_meta(path: Path) -> dict[str, str]:
    try:
        conn = sqlite3.connect(str(path))
        try:
            tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "meta" not in tables:
                return {}
            return {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM meta")}
        finally:
            conn.close()
    except Exception:
        return {}


def _choose_arch35_db(root: Path) -> tuple[Path, list[dict[str, Any]]]:
    candidates: list[tuple[int, Path, dict[str, str]]] = []
    inventory: list[dict[str, Any]] = []
    for db in root.rglob("kb_graph.sqlite"):
        meta = _db_meta(db)
        path_text = db.as_posix().lower()
        arch = str(meta.get("architecture") or meta.get("arch") or "").lower()
        score = 0
        if arch == ARCH:
            score += 100
        if f"/{ARCH}/" in path_text or f"\\{ARCH}\\" in str(db).lower():
            score += 50
        if OP_NAME in str(meta.get("op_name") or "").lower():
            score += 10
        inventory.append({"path": str(db), "score": score, "meta": meta})
        candidates.append((score, db, meta))
    if not candidates:
        raise FileNotFoundError("archive contains no kb_graph.sqlite")
    candidates.sort(key=lambda x: (x[0], str(x[1])), reverse=True)
    best_score, best, _ = candidates[0]
    if best_score <= 0:
        raise RuntimeError(
            "found legacy DBs but none can be identified as arch35; refusing an ambiguous import"
        )
    return best, inventory


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
        for ev in ent.attrs.get("evidence") or []:
            if isinstance(ev, dict) and ev.get("file"):
                files.add(str(ev["file"]))
    return files


def _arch35_source_check(operator: Path, uo: Path) -> dict[str, Any]:
    cm = read_codemap(uo)
    files = _source_files(cm)
    basenames = {Path(f.replace("\\", "/")).name for f in files}
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
    matched_host = sorted(set(expected_host) & basenames)
    matched_kernel = sorted(set(expected_kernel) & basenames)
    return {
        "architecture": cm.architecture,
        "source_evidence_files": len(files),
        "expected_host_files": expected_host,
        "matched_host_files": matched_host,
        "missing_host_files": sorted(set(expected_host) - basenames),
        "expected_kernel_file_count": len(expected_kernel),
        "matched_kernel_file_count": len(matched_kernel),
        "foreign_arch_evidence": foreign_arch[:50],
        "ok": cm.architecture == ARCH and not foreign_arch and bool(files),
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

    with tempfile.TemporaryDirectory(prefix="uo-arch35-") as td:
        extracted = Path(td)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extracted)
        legacy_db, inventory = _choose_arch35_db(extracted)
        product = out_dir / f"{OP_NAME}.{ARCH}.uo"
        legacy_db_to_uo(
            legacy_db,
            product,
            op_name=OP_NAME,
            architecture=ARCH,
        )

    binary = audit_uo(product)
    source = _arch35_source_check(operator, product)
    blocking = list(binary.get("blocking") or [])
    if not source["ok"]:
        blocking.append(
            {
                "code": "ARCH35_SOURCE_CROSSCHECK_FAILED",
                "detail": "binary evidence is empty, foreign-arch, or not labelled arch35",
                "source": source,
            }
        )
    report = {
        "ok": not blocking,
        "mode": "archived-real-compiler-facts+live-source-crosscheck",
        "fresh_clang_extraction": False,
        "operator": str(operator),
        "archive": str(archive),
        "product": str(product),
        "binary": binary,
        "source_crosscheck": source,
        "legacy_db_inventory": inventory,
        "blocking": blocking,
    }
    (out_dir / "arch35-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# FlashAttentionScoreGrad arch35 UO audit",
        "",
        f"- ok: `{report['ok']}`",
        f"- mode: `{report['mode']}`",
        f"- product: `{product.name}`",
        f"- size_bytes: `{binary.get('size_bytes')}`",
        f"- entities: `{(binary.get('summary') or {}).get('entity_count')}`",
        f"- relations: `{(binary.get('summary') or {}).get('relation_count')}`",
        f"- evidence_backed_host_kernel_path: `{binary.get('evidence_backed_host_kernel_path')}`",
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
        f"- matched arch35 host files: `{len(source['matched_host_files'])}/{len(source['expected_host_files'])}`",
        f"- matched arch35 kernel files: `{source['matched_kernel_file_count']}/{source['expected_kernel_file_count']}`",
        f"- foreign arch evidence: `{len(source['foreign_arch_evidence'])}`",
        "",
        "> This CI calibration imports the repository's committed historical compiler facts because GitHub-hosted runners do not provide CANN. It does not replace a fresh local CANN/Clang extraction.",
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
