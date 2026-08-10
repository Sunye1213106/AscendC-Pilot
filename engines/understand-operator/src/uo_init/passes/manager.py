# -*- coding: utf-8 -*-
"""PassManager — run deterministic structural CodeMap analyze passes in order."""

from __future__ import annotations

from typing import Any, Callable

from uo_init.ir.codemap import CodeMap
from uo_init.passes import (
    compile_time,
    dataflow,
    host_kernel,
    kernel,
    macro,
    reachability,
    symbol,
    template,
    tiling,
)

PassFn = Callable[..., CodeMap]

# Canonical structural analyze order (after BuildVariant + Clang frontend).
# Host API→packed-key roots are recovered later from *current source* by
# host_tiling_key + host_defuse. The retired ``input_root`` pass consumed
# derive_key_fields/host_derivation and therefore has no place in the new UO
# product pipeline.
ANALYZE_PASSES: list[tuple[str, PassFn]] = [
    ("reachability", reachability.run),
    ("core_codemap", symbol.run),
    ("compile_time", compile_time.run),
    ("macro", macro.run),
    ("template", template.run),
    ("dataflow", dataflow.run),
    ("tiling", tiling.run),
    ("kernel", kernel.run),
    ("host_kernel_bind", host_kernel.run),
]


class PassManager:
    def __init__(self, passes: list[tuple[str, PassFn]] | None = None) -> None:
        self.passes = list(passes or ANALYZE_PASSES)

    def run(self, codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
        ctx = dict(context or {})
        ran: list[str] = []
        for name, fn in self.passes:
            codemap = fn(codemap, context=ctx)
            ran.append(name)
        codemap.meta["passes_run"] = ran
        return codemap


def run_analyze_passes(
    codemap: CodeMap,
    *,
    context: dict[str, Any] | None = None,
) -> CodeMap:
    return PassManager().run(codemap, context=context)
