# -*- coding: utf-8 -*-
"""Primitives shared by AscendC-Pilot engines.

Currently the solver stack: a constraint IR (`constraint_ir`) and the Z3
compiler/solver that consumes it (`z3_backend`). Both were extracted from the
testcase-generation engine so understand-operator can decide key reachability
with the exact same semantics TG uses to realize inputs — if the two engines
disagreed about what an expression means, a key "proven reachable" by one could
be unrealizable by the other.
"""
from __future__ import annotations

__all__ = ["constraint_ir", "z3_backend"]
