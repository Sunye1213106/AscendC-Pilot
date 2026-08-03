# -*- coding: utf-8 -*-
"""Compatibility shim: closure_gate was renamed runtime_counterexample_gate."""

from replay_runtime_counterexample_gate import (  # noqa: F401
    counters, excluded_by, load_declared, load_runtime, main, partition,
)

if __name__ == "__main__":
    raise SystemExit(main())
