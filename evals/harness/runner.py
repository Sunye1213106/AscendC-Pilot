"""Generic multi-run eval summarizer.

Extracted patterns from ``scripts/closure_acceptance_harness.py`` so other
suites (routing, skills) share the same metrics vocabulary:

- pass@1 / pass@k — at least one success in k runs
- pass^k — all k runs succeed (critical for false TilingKey conclusions)
- context_tokens / tool_calls / wall_time
- context_efficiency = verified_facts / input_tokens
"""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class RunResult:
    ok: bool
    name: str = ""
    context_tokens: int = 0
    tool_calls: int = 0
    wall_time_s: float = 0.0
    verified_facts: int = 0
    unsupported_claims: int = 0
    skipped: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def pass_at_k(oks: list[bool], k: int | None = None) -> float:
    """Probability that at least one of k runs succeeds (empirical on sample)."""
    if not oks:
        return 0.0
    sample = oks if k is None else oks[:k]
    return 1.0 if any(sample) else 0.0


def pass_hat_k(oks: list[bool], k: int | None = None) -> float:
    """Reliability: all of k runs must succeed (pass^k)."""
    if not oks:
        return 0.0
    sample = oks if k is None else oks[:k]
    return 1.0 if sample and all(sample) else 0.0


def context_efficiency(verified_facts: int, input_tokens: int) -> float:
    if input_tokens <= 0:
        return 0.0
    return round(verified_facts / input_tokens, 6)


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Distribution over runs — compatible with closure_acceptance_harness.summarize."""
    active = [r for r in runs if not r.get("skipped")]
    oks = [bool(r.get("ok")) for r in active]
    gaps = [int(r.get("final_gap") or 0) for r in active if "final_gap" in r]
    rounds = [int(r.get("rounds_used") or 0) for r in active if r.get("rounds_used")]
    failures: dict[str, int] = {}
    for r in runs:
        for f in r.get("gate_failures") or []:
            key = str(f).split(":")[0]
            failures[key] = failures.get(key, 0) + 1
    passed = sum(1 for ok in oks if ok)
    n = len(oks)
    out: dict[str, Any] = {
        "runs": len(runs),
        "active_runs": n,
        "passed": passed,
        "pass_rate": round(passed / n, 3) if n else 0.0,
        "pass@1": pass_at_k(oks, 1),
        "pass^k": pass_hat_k(oks),
        "gate_failure_counts": failures,
    }
    tokens = [int(r.get("context_tokens") or 0) for r in active if r.get("context_tokens")]
    if tokens:
        out["context_tokens"] = {
            "min": min(tokens),
            "max": max(tokens),
            "mean": round(statistics.fmean(tokens), 1),
        }
    tools = [int(r.get("tool_calls") or 0) for r in active if "tool_calls" in r]
    if tools:
        out["tool_calls"] = {
            "min": min(tools),
            "max": max(tools),
            "mean": round(statistics.fmean(tools), 2),
        }
    walls = [float(r.get("wall_time_s") or 0) for r in active if r.get("wall_time_s")]
    if walls:
        out["wall_time_s"] = {
            "min": round(min(walls), 3),
            "max": round(max(walls), 3),
            "mean": round(statistics.fmean(walls), 3),
        }
    facts = sum(int(r.get("verified_facts") or 0) for r in active)
    tok_sum = sum(int(r.get("context_tokens") or 0) for r in active)
    if tok_sum:
        out["context_efficiency"] = context_efficiency(facts, tok_sum)
    unsupported = sum(int(r.get("unsupported_claims") or 0) for r in active)
    if n:
        out["unsupported_claim_rate"] = round(unsupported / n, 3)
    if gaps:
        out["final_gap"] = {
            "min": min(gaps),
            "max": max(gaps),
            "mean": round(statistics.fmean(gaps), 2),
        }
    if rounds:
        out["rounds_used"] = {
            "min": min(rounds),
            "max": max(rounds),
            "mean": round(statistics.fmean(rounds), 2),
        }
    return out


# Alias used by closure harness re-export.
aggregate_metrics = summarize_runs


def run_repeated(
    fn: Callable[[int], RunResult | dict[str, Any]],
    *,
    runs: int = 1,
) -> dict[str, Any]:
    """Execute ``fn(seed_i)`` ``runs`` times and summarize."""
    results: list[dict[str, Any]] = []
    for i in range(max(1, runs)):
        t0 = time.perf_counter()
        raw = fn(i)
        elapsed = time.perf_counter() - t0
        if isinstance(raw, RunResult):
            d = raw.to_dict()
        else:
            d = dict(raw)
        d.setdefault("wall_time_s", round(elapsed, 4))
        results.append(d)
    return {"summary": summarize_runs(results), "runs": results}
