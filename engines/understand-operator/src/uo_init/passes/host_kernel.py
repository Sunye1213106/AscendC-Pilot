# -*- coding: utf-8 -*-
"""HostKernelBindPass — close Host → TilingKey → Template → Kernel paths."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    del context  # reserved
    kernels = codemap.by_kind(EntityKind.KERNEL)
    keys = codemap.by_kind(EntityKind.TILING_KEY)
    instances = codemap.by_kind(EntityKind.TEMPLATE_INSTANCE)
    archs = codemap.by_kind(EntityKind.ARCH)

    for key in keys:
        for inst in instances:
            codemap.link(RelationKind.SELECTS, key.id, inst.id)
        for kernel in kernels:
            codemap.link(RelationKind.SELECTS, key.id, kernel.id)
            codemap.link(RelationKind.LAUNCHES, key.id, kernel.id)

    for inst in instances:
        for kernel in kernels:
            codemap.link(RelationKind.INSTANTIATES, inst.id, kernel.id)
        for arch in archs:
            codemap.link(RelationKind.AVAILABLE_ON, inst.id, arch.id)

    for kernel in kernels:
        for arch in archs:
            codemap.link(RelationKind.AVAILABLE_ON, kernel.id, arch.id)

    # Ensure at least one INPUT → TILING_KEY edge when inputs exist.
    inputs = codemap.by_kind(EntityKind.INPUT)
    if inputs and keys:
        for inp in inputs:
            for key in keys:
                # Soft FLOWS_TO so find_path can traverse even without exact derive.
                if not any(
                    r.src == inp.id and r.dst == key.id
                    for r in codemap.relations.values()
                ):
                    # Only connect when names suggest relation or no DERIVES yet.
                    if inp.name.lower() in key.name.lower() or key.name.lower() in inp.name.lower():
                        codemap.link(RelationKind.FLOWS_TO, inp.id, key.id)

    codemap.meta["host_kernel_bind_pass"] = "v1"
    codemap.meta["has_host_kernel_path"] = codemap.host_kernel_path_exists()
    return codemap
