#!/usr/bin/env python3
"""CI smoke for evals (dry only, no LLM / NPU).

Runs:
1. harness metric self-check
2. routing dry eval
3. skill dry eval (all four cognitive skills)
4. closure acceptance harness via shared summarize (1 dry run)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_COGNITIVE_SKILLS = (
    "operator-analysis",
    "testcase-generation",
    "source-proof",
    "code-review",
)


def _run(cmd: list[str]) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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
    results.append(
        _run([sys.executable, str(REPO / "evals" / "routing" / "run_routing_eval.py"), "--repo", str(REPO)])
    )
    for skill in _COGNITIVE_SKILLS:
        results.append(
            _run(
                [
                    sys.executable,
                    str(REPO / "evals" / "skills" / "run_skill_eval.py"),
                    "--repo",
                    str(REPO),
                    "--skill",
                    skill,
                ]
            )
        )
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
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "closure_acceptance_harness.py"), "--runs", "1"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    results.append(
        {
            "cmd": ["closure_acceptance_harness.py", "--runs", "1"],
            "returncode": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-1000:],
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
