"""Shared eval harness primitives (pass@k / pass^k / token metrics)."""

from evals.harness.runner import (
    RunResult,
    aggregate_metrics,
    context_efficiency,
    pass_at_k,
    pass_hat_k,
    summarize_runs,
)

__all__ = [
    "RunResult",
    "aggregate_metrics",
    "context_efficiency",
    "pass_at_k",
    "pass_hat_k",
    "summarize_runs",
]
