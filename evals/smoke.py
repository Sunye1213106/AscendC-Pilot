#!/usr/bin/env python3
"""CI smoke for deterministic/runtime evals (dry only, no LLM / NPU).

Natural-language routing/skill-ranking evals are intentionally not part of
this smoke suite. Free-form NL belongs to Primary; CI validates deterministic
workflow contracts, product closure, examples and harness behavior instead.

L0 entry:
1. harness metric self-check
2. closure acceptance harness (1 dry run)
3. skill architecture + instruction ownership + operator independence lints
4. shared-reference projection check
5. worked-example layout check
6. harness E2E authorize scenarios (no LLM)
7. live eval skip contract (no model → skip, never fake pass@k)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
        "ok": proc.returncode == 0,
    }


def main() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    from evals.harness.runner import pass_at_k, pass_hat_k, summarize_runs

    assert pass_at_k([False, True, False], 3) == 1.0
    assert pass_hat_k([True, True, True], 3) == 1.0
    assert pass_hat_k([True, False, True], 3) == 0.0
    s = summarize_runs(
        [
            {"ok": True, "context_tokens": 100, "verified_facts": 5, "tool_calls": 2, "wall_time_s": 0.1},
            {"ok": True, "context_tokens": 120, "verified_facts": 6, "tool_calls": 3, "wall_time_s": 0.2},
        ]
    )
    assert s["pass^k"] == 1.0
    assert s["pass_rate"] == 1.0

    results = []
    env = os.environ.copy()
    sep = ";" if os.name == "nt" else ":"
    env["PYTHONPATH"] = sep.join(
        [
            str(REPO),
            str(REPO / "engines" / "testcase-generation"),
            str(REPO / "scripts"),
            str(REPO / "engines" / "understand-operator" / "src"),
            str(REPO / "pilot"),
        ]
    )
    results.append(
        _run(
            [sys.executable, str(REPO / "scripts" / "closure_acceptance_harness.py"), "--runs", "1"],
            env=env,
        )
    )
    results.append(_run([sys.executable, str(REPO / "scripts" / "check_skill_architecture.py")]))
    results.append(_run([sys.executable, str(REPO / "scripts" / "check_instruction_ownership.py")]))
    results.append(_run([sys.executable, str(REPO / "scripts" / "check_operator_independence.py")]))
    results.append(_run([sys.executable, "-m", "evals.run_example", "--all"]))
    results.append(
        _run([sys.executable, str(REPO / "evals" / "harness_e2e" / "run_harness_e2e.py")], env=env)
    )

    from evals.live.run import evaluate_live, load_cases

    live_cases = load_cases(REPO)
    live_doc = evaluate_live(REPO)
    live_ok = (
        18 <= len(live_cases) <= 24
        and live_doc.get("skipped") is True
        and live_doc.get("pass@k") is None
        and live_doc.get("pass_rate") is None
    )
    results.append(
        {
            "cmd": ["evals.live.run", "--skip-check"],
            "returncode": 0 if live_ok else 1,
            "stdout": json.dumps(
                {
                    "n_cases": len(live_cases),
                    "skipped": live_doc.get("skipped"),
                    "skip_reason": live_doc.get("skip_reason"),
                    "pass@k": live_doc.get("pass@k"),
                },
                ensure_ascii=False,
            ),
            "stderr": "" if live_ok else "live skip contract failed (must not fake pass@k)",
            "ok": live_ok,
        }
    )

    ok = all(r["ok"] for r in results)
    print(
        json.dumps(
            {
                "ok": ok,
                "results": [
                    {"cmd": r["cmd"], "ok": r["ok"], "returncode": r["returncode"]} for r in results
                ],
            },
            indent=2,
        )
    )
    if not ok:
        for r in results:
            if not r["ok"]:
                print("--- FAIL ---", r["cmd"], file=sys.stderr)
                print(r.get("stdout", ""), file=sys.stderr)
                print(r.get("stderr", ""), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
