# -*- coding: utf-8 -*-
"""PassManager — run deterministic CodeMap analyze passes in order."""

from __future__ import annotations

from typing import Any, Callable

from uo_init.ir.codemap import CodeMap
from uo_init.passes import (
    compile_time,
    dataflow,
    host_kernel,
    input_root,
    kernel,
    macro,
    reachability,
    symbol,
    template,
    tiling,
)

PassFn = Callable[..., CodeMap]

# Canonical analyze order (after BuildVariant + Clang frontend).
ANALYZE_PASSES: list[tuple[str, PassFn]] = [
    ("reachability", reachability.run),
    ("core_codemap", symbol.run),
    ("compile_time", compile_time.run),
    ("macro", macro.run),
    ("template", template.run),
    ("dataflow", dataflow.run),
    ("input_root", input_root.run),
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
