# -*- coding: utf-8 -*-
"""Deterministic CodeMap passes.

Pass order (canonical):
  BuildVariant → Clang → Reachability → CoreCodeMap → CompileTime →
  Template → Dataflow → Tiling → Kernel → HostKernelBind
"""

from uo_init.passes.manager import PassManager, run_analyze_passes

__all__ = ["PassManager", "run_analyze_passes"]
