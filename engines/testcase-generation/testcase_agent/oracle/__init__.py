# -*- coding: utf-8 -*-
"""Host oracle: re-export the replay runner the closure drives.

The runner stays under `scripts/replay/` because twenty-odd scripts and its
own test suite import it from there, and the driver protocol is operator
plumbing rather than test generation. This package is the stable import path
for the closure modules and for CE once it needs to re-run cases.
"""

from __future__ import annotations

from testcase_agent.closure.workspace import replay_runner, schema, dim_names

__all__ = ["replay_runner", "schema", "dim_names", "CRASHED", "NOT_RUN", "Result"]


def __getattr__(name: str):
    runner_mod = _runner_mod()
    if name in ("CRASHED", "NOT_RUN", "Result", "ReplayRunner", "default",
                "wide_row", "SCHEMA"):
        return getattr(runner_mod, name)
    raise AttributeError(name)


def _runner_mod():
    from testcase_agent.closure import workspace as W
    return W._replay()
