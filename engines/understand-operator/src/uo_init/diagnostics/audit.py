# -*- coding: utf-8 -*-
"""Soundness/completeness audit for a committed ``.uo`` CodeMap.

The audit intentionally distinguishes *presence* from *evidence-backed
connectivity*. A graph with TilingKeys and Kernels but no proven selection path
must fail instead of being treated as complete.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.host_kernel import evidence_backed_host_kernel_path_exists


def audit_codemap(codemap: CodeMap) -> dict[str, Any]:
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    inputs = codemap.by_kind(EntityKind.INPUT)
    hosts = (
        codemap.by_kind(EntityKind.FUNCTION)
        + codemap.by_kind(EntityKind.FIELD)
        + codemap.by_kind(EntityKind.VARIABLE)
    )
    keys = codemap.by_kind(EntityKind.TILING_KEY)
    kernels = codemap.by_kind(EntityKind.KERNEL)
    instances = codemap.by_kind(EntityKind.TEMPLATE_INSTANCE)

    def block(code: str, detail: str, **extra: Any) -> None:
        blocking.append({"code": code, "detail": detail, **extra})

    def warn(code: str, detail: str, **extra: Any) -> None:
        warnings.append({"code": code, "detail": detail, **extra})

    if not hosts:
        block("MISSING_HOST", "no Host function/field/variable entities")
    if not inputs:
        block("MISSING_INPUT", "no API input entities")
    if not keys:
        block("MISSING_TILING_KEY", "no TilingKey entities")
    if not kernels:
        block("MISSING_KERNEL", "no Kernel entities")

    strict_path = evidence_backed_host_kernel_path_exists(codemap)
    if kernels and not strict_path:
        block(
            "MISSING_EVIDENCE_BACKED_HOST_KERNEL_PATH",
            "no semantic INPUT→…→KERNEL path; node presence alone is insufficient",
        )

    legacy_summary = codemap.summary()
    legacy_path = bool(legacy_summary.get("has_host_kernel_path"))
    if legacy_path and not strict_path:
        warn(
            "SUMMARY_HOST_KERNEL_PATH_FALSE_POSITIVE",
            "CodeMap.summary() reports a Host→Kernel path without an evidence-backed semantic path",
        )
    # Audit output is authoritative: never repeat the permissive legacy value.
    strict_summary = dict(legacy_summary)
    strict_summary["has_host_kernel_path"] = strict_path

    # Detect the exact anti-pattern that previously made every key select every
    # kernel. It is almost always a synthetic Cartesian product, not source
    # evidence. A genuine operator can still be represented by explicit branch
    # controls without requiring this matrix.
    select_pairs = {
        (rel.src, rel.dst)
        for rel in codemap.relations.values()
        if rel.kind_name() in {RelationKind.SELECTS.value, RelationKind.LAUNCHES.value}
    }
    if len(keys) > 1 and len(kernels) > 1:
        universal = all((key.id, kernel.id) in select_pairs for key in keys for kernel in kernels)
        if universal:
            block(
                "SUSPICIOUS_CARTESIAN_KEY_KERNEL",
                f"all {len(keys)} TilingKeys select/launch all {len(kernels)} Kernels",
            )

    outgoing: dict[str, list[Any]] = defaultdict(list)
    incoming: dict[str, list[Any]] = defaultdict(list)
    for rel in codemap.relations.values():
        outgoing[rel.src].append(rel)
        incoming[rel.dst].append(rel)

    selection_kinds = {
        RelationKind.SELECTS.value,
        RelationKind.CONTROLS.value,
        RelationKind.BINDS.value,
        RelationKind.INSTANTIATES.value,
        RelationKind.LAUNCHES.value,
    }
    unbound_keys = [
        e.name
        for e in keys
        if not any(r.kind_name() in selection_kinds for r in outgoing.get(e.id, ()))
    ]
    if unbound_keys:
        warn(
            "UNBOUND_TILING_KEYS",
            f"{len(unbound_keys)} TilingKeys have no outgoing selection/binding edge",
            examples=sorted(unbound_keys)[:20],
        )

    kernel_incoming = {
        RelationKind.SELECTS.value,
        RelationKind.CONTROLS.value,
        RelationKind.INSTANTIATES.value,
        RelationKind.LAUNCHES.value,
    }
    unbound_kernels = [
        e.name
        for e in kernels
        if not any(r.kind_name() in kernel_incoming for r in incoming.get(e.id, ()))
    ]
    if unbound_kernels:
        warn(
            "UNBOUND_KERNELS",
            f"{len(unbound_kernels)} Kernels have no incoming select/control/instantiate edge",
            examples=sorted(unbound_kernels)[:20],
        )

    unbound_instances = [
        e.name
        for e in instances
        if not any(
            r.kind_name() == RelationKind.INSTANTIATES.value
            and codemap.entities.get(r.dst)
            and codemap.entities[r.dst].kind_name() == EntityKind.KERNEL.value
            for r in outgoing.get(e.id, ())
        )
    ]
    if unbound_instances:
        warn(
            "UNBOUND_TEMPLATE_INSTANCES",
            f"{len(unbound_instances)} template instances have no explicit Kernel target",
            examples=sorted(unbound_instances)[:20],
        )

    unresolved_entities = [
        e.id for e in codemap.entities.values() if str(e.status).lower() in {"unresolved", "partial", "unknown"}
    ]
    unresolved_relations = [
        r.id for r in codemap.relations.values() if str(r.status).lower() in {"unresolved", "partial", "unknown"}
    ]
    if unresolved_entities or unresolved_relations:
        warn(
            "UNRESOLVED_FACTS",
            f"entities={len(unresolved_entities)} relations={len(unresolved_relations)}",
        )

    low_conf_entities = [e.id for e in codemap.entities.values() if float(e.confidence) < 0.8]
    low_conf_relations = [r.id for r in codemap.relations.values() if float(r.confidence) < 0.8]
    if low_conf_entities or low_conf_relations:
        warn(
            "LOW_CONFIDENCE_FACTS",
            f"entities={len(low_conf_entities)} relations={len(low_conf_relations)}",
        )

    return {
        "ok": not blocking,
        "op_name": codemap.op_name,
        "architecture": codemap.architecture,
        "summary": strict_summary,
        "legacy_summary_has_host_kernel_path": legacy_path,
        "evidence_backed_host_kernel_path": strict_path,
        "counts": {
            "inputs": len(inputs),
            "host_entities": len(hosts),
            "tiling_keys": len(keys),
            "kernels": len(kernels),
            "template_instances": len(instances),
            "unbound_tiling_keys": len(unbound_keys),
            "unbound_kernels": len(unbound_kernels),
            "unbound_template_instances": len(unbound_instances),
            "unresolved_entities": len(unresolved_entities),
            "unresolved_relations": len(unresolved_relations),
        },
        "blocking": blocking,
        "warnings": warnings,
    }


def audit_uo(path: str | Path) -> dict[str, Any]:
    from uo_init.store.reader import read_codemap, read_meta

    product = Path(path).expanduser().resolve()
    cm = read_codemap(product)
    report = audit_codemap(cm)
    report["product"] = str(product)
    report["size_bytes"] = product.stat().st_size
    report["meta"] = read_meta(product)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a committed UO CodeMap binary")
    parser.add_argument("uo", type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON (default is also JSON-safe text)")
    args = parser.parse_args(argv)
    try:
        report = audit_uo(args.uo)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
