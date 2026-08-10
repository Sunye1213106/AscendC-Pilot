# -*- coding: utf-8 -*-
"""Soundness/completeness audit for a committed ``.uo`` CodeMap.

Presence is not completeness. A CodeMap is useful to an Agent only when the
binary preserves source-backed API roots, compile-time selection, TilingData
transport, Kernel execution and output flow without synthetic Cartesian edges.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.host_kernel import evidence_backed_host_kernel_path_exists

_FLOW_KINDS = {
    RelationKind.DERIVES.value,
    RelationKind.FLOWS_TO.value,
    RelationKind.CONTROLS.value,
    RelationKind.BINDS.value,
    RelationKind.SELECTS.value,
    RelationKind.INSTANTIATES.value,
    RelationKind.LAUNCHES.value,
    RelationKind.CALLS.value,
    RelationKind.READS.value,
    RelationKind.WRITES.value,
}
_ROOT_FLOW_KINDS = {
    RelationKind.DERIVES.value,
    RelationKind.FLOWS_TO.value,
    RelationKind.CONTROLS.value,
}
_ROOT_KINDS = {
    EntityKind.INPUT.value,
    EntityKind.COMPILE_VAR.value,
    EntityKind.MACRO.value,
    EntityKind.BUILD_VARIANT.value,
    EntityKind.ARCH.value,
}


def _path_exists(
    codemap: CodeMap,
    *,
    start_kind: EntityKind,
    end_kind: EntityKind,
    require_kind: EntityKind | None = None,
) -> bool:
    starts = codemap.by_kind(start_kind)
    ends = {e.id for e in codemap.by_kind(end_kind)}
    if not starts or not ends:
        return False
    adj: dict[str, list[str]] = defaultdict(list)
    for rel in codemap.relations.values():
        if rel.kind_name() in _FLOW_KINDS:
            adj[rel.src].append(rel.dst)
    required = require_kind.value if require_kind is not None else ""
    q: deque[tuple[str, bool]] = deque(
        (e.id, e.kind_name() == required if required else True) for e in starts
    )
    seen = set(q)
    while q:
        cur, has_required = q.popleft()
        if cur in ends and has_required:
            return True
        for nxt in adj.get(cur, ()):
            ent = codemap.entities.get(nxt)
            next_required = has_required or bool(ent and ent.kind_name() == required)
            state = (nxt, next_required)
            if state not in seen:
                seen.add(state)
                q.append(state)
    return False


def _source_rooted_entities(codemap: CodeMap) -> set[str]:
    roots = {
        ent.id
        for ent in codemap.entities.values()
        if ent.kind_name() in _ROOT_KINDS
    }
    adj: dict[str, list[str]] = defaultdict(list)
    for rel in codemap.relations.values():
        if rel.kind_name() in _ROOT_FLOW_KINDS:
            adj[rel.src].append(rel.dst)
    seen = set(roots)
    queue = deque(roots)
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def audit_codemap(codemap: CodeMap) -> dict[str, Any]:
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    inputs = codemap.by_kind(EntityKind.INPUT)
    tensor_inputs = [e for e in inputs if e.attrs.get("api_kind") == "tensor"]
    attributes = [e for e in inputs if e.attrs.get("api_kind") == "attribute"]
    outputs = codemap.by_kind(EntityKind.OUTPUT)
    hosts = (
        codemap.by_kind(EntityKind.FUNCTION)
        + codemap.by_kind(EntityKind.FIELD)
        + codemap.by_kind(EntityKind.VARIABLE)
    )
    keys = codemap.by_kind(EntityKind.TILING_KEY)
    declared_keys = sorted(
        (e for e in keys if e.attrs.get("source_declared")),
        key=lambda e: int(e.attrs.get("decl_order") or 0),
    )
    tiling_data = codemap.by_kind(EntityKind.TILING_DATA)
    tiling_fields = codemap.by_kind(EntityKind.TILING_FIELD)
    kernels = codemap.by_kind(EntityKind.KERNEL)
    instances = codemap.by_kind(EntityKind.TEMPLATE_INSTANCE)

    def block(code: str, detail: str, **extra: Any) -> None:
        blocking.append({"code": code, "detail": detail, **extra})

    def warn(code: str, detail: str, **extra: Any) -> None:
        warnings.append({"code": code, "detail": detail, **extra})

    if not hosts:
        block("MISSING_HOST", "no Host function/field/variable entities")
    if not inputs:
        block("MISSING_INPUT", "no API input/attribute entities")
    if not outputs:
        block("MISSING_OUTPUT", "no API output entities")
    if not keys:
        block("MISSING_TILING_KEY", "no TilingKey entities")
    if not tiling_data or not tiling_fields:
        block("MISSING_TILING_DATA", "no structured TilingData class/field model")
    if not kernels:
        block("MISSING_KERNEL", "no Kernel entities")

    source_key_count = int(codemap.meta.get("source_declared_tiling_key_count") or 0)
    if source_key_count and len(keys) != source_key_count:
        block(
            "TILING_KEY_CARDINALITY_MISMATCH",
            f"current source declares {source_key_count} TilingKeys but CodeMap contains {len(keys)}",
            declared=codemap.meta.get("source_declared_tiling_keys") or [],
        )

    host_packing = codemap.meta.get("host_tiling_key_packing") or {}
    packing_calls = int(host_packing.get("calls") or 0)
    packing_bound = int(host_packing.get("fields_bound") or 0)
    packing_mismatches = list(host_packing.get("argument_count_mismatches") or [])
    packing_missing = [e.name for e in declared_keys if not e.attrs.get("host_packing_expressions")]
    if packing_calls and (packing_bound != len(declared_keys) or packing_missing or packing_mismatches):
        block(
            "INCOMPLETE_HOST_TILINGKEY_PACKING",
            f"Host packing covers {packing_bound}/{len(declared_keys)} source-declared TilingKeys",
            missing=packing_missing,
            argument_count_mismatches=packing_mismatches,
        )

    rooted = _source_rooted_entities(codemap)
    rooted_keys = [e.name for e in declared_keys if e.id in rooted]
    unrooted_keys = [e.name for e in declared_keys if e.id not in rooted]
    if declared_keys and unrooted_keys:
        block(
            "UNROOTED_TILING_KEYS",
            f"{len(unrooted_keys)}/{len(declared_keys)} source-declared TilingKeys have no API/compile root",
            unrooted=unrooted_keys,
        )

    strict_path = evidence_backed_host_kernel_path_exists(codemap)
    input_key_kernel = _path_exists(
        codemap,
        start_kind=EntityKind.INPUT,
        end_kind=EntityKind.KERNEL,
        require_kind=EntityKind.TILING_KEY,
    )
    tdata_kernel = _path_exists(
        codemap,
        start_kind=EntityKind.TILING_DATA,
        end_kind=EntityKind.KERNEL,
    )
    input_output = _path_exists(
        codemap,
        start_kind=EntityKind.INPUT,
        end_kind=EntityKind.OUTPUT,
    )
    if kernels and not strict_path:
        block(
            "MISSING_EVIDENCE_BACKED_HOST_KERNEL_PATH",
            "no semantic INPUT→…→KERNEL path; node presence alone is insufficient",
        )
    if inputs and keys and kernels and not input_key_kernel:
        block(
            "MISSING_INPUT_TILINGKEY_KERNEL_PATH",
            "no source-backed INPUT→…→TILING_KEY→…→KERNEL selection path",
        )
    if tiling_data and kernels and not tdata_kernel:
        block(
            "MISSING_TILINGDATA_KERNEL_PATH",
            "TilingData is present but no source-backed TILING_DATA→KERNEL consumption path exists",
        )
    if inputs and outputs and kernels and not input_output:
        block(
            "MISSING_INPUT_OUTPUT_PATH",
            "no source-backed INPUT→…→KERNEL→OUTPUT execution/data path exists",
        )

    legacy_summary = codemap.summary()
    legacy_path = bool(legacy_summary.get("has_host_kernel_path"))
    if legacy_path and not strict_path:
        warn(
            "SUMMARY_HOST_KERNEL_PATH_FALSE_POSITIVE",
            "CodeMap.summary() reports a Host→Kernel path without an evidence-backed semantic path",
        )
    strict_summary = dict(legacy_summary)
    strict_summary["has_host_kernel_path"] = strict_path
    strict_summary["has_input_tilingkey_kernel_path"] = input_key_kernel
    strict_summary["has_tilingdata_kernel_path"] = tdata_kernel
    strict_summary["has_input_output_path"] = input_output
    strict_summary["tiling_key_root_coverage"] = f"{len(rooted_keys)}/{len(declared_keys)}"
    strict_summary["tiling_key_host_packing_coverage"] = f"{packing_bound}/{len(declared_keys)}"

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
        RelationKind.FLOWS_TO.value,
        RelationKind.CALLS.value,
    }
    unbound_kernels = [
        e.name
        for e in kernels
        if not any(r.kind_name() in kernel_incoming for r in incoming.get(e.id, ()))
    ]
    if unbound_kernels:
        warn(
            "UNBOUND_KERNELS",
            f"{len(unbound_kernels)} Kernels have no incoming semantic edge",
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
        "evidence_backed_input_tilingkey_kernel_path": input_key_kernel,
        "evidence_backed_tilingdata_kernel_path": tdata_kernel,
        "evidence_backed_input_output_path": input_output,
        "tiling_key_rooted": rooted_keys,
        "tiling_key_unrooted": unrooted_keys,
        "counts": {
            "inputs": len(inputs),
            "tensor_inputs": len(tensor_inputs),
            "attributes": len(attributes),
            "outputs": len(outputs),
            "host_entities": len(hosts),
            "tiling_keys": len(keys),
            "source_declared_tiling_keys": source_key_count,
            "host_packing_bound_tiling_keys": packing_bound,
            "rooted_tiling_keys": len(rooted_keys),
            "unrooted_tiling_keys": len(unrooted_keys),
            "tiling_data": len(tiling_data),
            "tiling_fields": len(tiling_fields),
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
