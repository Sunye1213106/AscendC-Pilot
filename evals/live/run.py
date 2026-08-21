#!/usr/bin/env python3
"""Live skill eval harness.

Fixed YAML cases live in ``evals/live/cases.yaml`` (~20). CI must not score
these as pass@k. Without an explicit live flag + model host (and without a
``.uo`` product when a case needs one), the run is skipped and labeled skip.

Enable a real live run with::

    ASCENDC_PILOT_LIVE_EVAL=1
    ASCENDC_LIVE_EVAL_CMD='…command that receives --query and --skill…'
    ASCENDC_LIVE_PRODUCT=/path/to/operator   # required for requires_uo cases
    ASCENDC_LIVE_NPU=1                       # only if a case sets requires_npu

    python evals/live/run.py
    python evals/skills/run_skill_eval.py --skill uo-query --live
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[2]

SKIP_MESSAGES = {
    "no_model": (
        "live eval skipped: no model host "
        "(set ASCENDC_PILOT_LIVE_EVAL=1 and ASCENDC_LIVE_EVAL_CMD)"
    ),
    "no_product": (
        "live eval skipped: no .uo product "
        "(set ASCENDC_LIVE_PRODUCT to an operator tree that contains a CodeMap)"
    ),
    "no_npu": "live eval skipped: NPU required but not available (ASCENDC_LIVE_NPU or npu-smi)",
    "missing_cases": "live eval skipped: cases.yaml missing or PyYAML unavailable",
}


def _ensure_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def live_eval_enabled() -> bool:
    return os.environ.get("ASCENDC_PILOT_LIVE_EVAL", "").strip().lower() in {"1", "true", "yes"}


def live_eval_cmd() -> str:
    """Invocable live runner. A model *name* is not enough — we must not fake scores."""
    return os.environ.get("ASCENDC_LIVE_EVAL_CMD", "").strip()


def has_npu() -> bool:
    if os.environ.get("ASCENDC_LIVE_NPU", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return shutil.which("npu-smi") is not None


def has_uo_product(root: Path | None) -> bool:
    if root is None or not root.is_dir():
        return False
    if any(root.glob("*.uo")):
        return True
    agent = root / ".ascendc-pilot"
    if not agent.is_dir():
        return False
    for pattern in ("*/*.uo", "*/uo/*.uo", "*/*.*.uo"):
        if any(agent.glob(pattern)):
            return True
    return False


def load_cases(repo: Path) -> list[dict[str, Any]]:
    path = repo / "evals" / "live" / "cases.yaml"
    if yaml is None or not path.is_file():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = list(doc.get("cases") or [])
    return [c for c in cases if isinstance(c, dict)]


def _product_root() -> Path | None:
    raw = os.environ.get("ASCENDC_LIVE_PRODUCT", "").strip()
    return Path(raw) if raw else None


def detect_global_skip(cases: list[dict[str, Any]]) -> str | None:
    if not cases:
        return "missing_cases"
    if not live_eval_enabled() or not live_eval_cmd():
        return "no_model"
    if any(c.get("requires_npu") for c in cases) and not has_npu():
        if all(c.get("requires_npu") for c in cases):
            return "no_npu"
    needs_uo = [c for c in cases if c.get("requires_uo")]
    if needs_uo and not has_uo_product(_product_root()):
        if len(needs_uo) == len(cases):
            return "no_product"
    return None


def _skip_record(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": case.get("id"),
        "ok": False,
        "skipped": True,
        "skip_reason": reason,
        "query": case.get("query"),
        "skill": case.get("skill") or case.get("expect_skill"),
    }


def _skipped_suite(cases: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    return {
        "ok": True,
        "skipped": True,
        "skip_reason": reason,
        "message": SKIP_MESSAGES.get(reason, reason),
        "n_cases": len(cases),
        "runs": [_skip_record(c, reason) for c in cases],
        # Must not pretend the suite passed. Callers must not treat these as scores.
        "pass@k": None,
        "pass@1": None,
        "pass^k": None,
        "pass_rate": None,
    }


def _run_live_case(case: dict[str, Any]) -> dict[str, Any]:
    cmd = live_eval_cmd()
    query = str(case.get("query") or "")
    skill = str(case.get("skill") or case.get("expect_skill") or "")
    product = _product_root()
    argv = cmd.split()
    argv.extend(["--query", query, "--skill", skill])
    if product is not None:
        argv.extend(["--product", str(product)])
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(os.environ.get("ASCENDC_LIVE_CASE_TIMEOUT", "120")),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # noqa: BLE001
        return {
            "id": case.get("id"),
            "ok": False,
            "skipped": False,
            "error": type(exc).__name__,
            "detail": str(exc)[:400],
        }
    stdout = proc.stdout or ""
    expect = str(case.get("expect_substr") or "").strip()
    ok = proc.returncode == 0 and (not expect or expect in stdout)
    return {
        "id": case.get("id"),
        "ok": ok,
        "skipped": False,
        "returncode": proc.returncode,
        "stdout_tail": stdout[-800:],
        "stderr_tail": (proc.stderr or "")[-400:],
    }


def evaluate_live(repo: Path, *, skill: str | None = None) -> dict[str, Any]:
    """Run or skip the fixed live suite. Never invents pass@k on skip."""
    _ensure_path(repo)
    cases = load_cases(repo)
    if skill:
        want = str(skill).strip()
        cases = [
            c
            for c in cases
            if str(c.get("skill") or "") == want or str(c.get("expect_skill") or "") == want
        ]
    skip = detect_global_skip(cases)
    if skip:
        return _skipped_suite(cases, skip)

    runs: list[dict[str, Any]] = []
    for case in cases:
        if case.get("requires_npu") and not has_npu():
            runs.append(_skip_record(case, "no_npu"))
            continue
        if case.get("requires_uo") and not has_uo_product(_product_root()):
            runs.append(_skip_record(case, "no_product"))
            continue
        runs.append(_run_live_case(case))

    active = [r for r in runs if not r.get("skipped")]
    if not active:
        reason = "no_product" if any(r.get("skip_reason") == "no_product" for r in runs) else "no_npu"
        out = _skipped_suite(cases, reason)
        out["runs"] = runs
        return out

    from evals.harness.runner import summarize_runs

    summary = summarize_runs(active)
    return {
        "ok": bool(summary.get("pass_rate", 0) == 1.0),
        "skipped": False,
        "n_cases": len(cases),
        "n_active": len(active),
        "n_skipped": len(runs) - len(active),
        "summary": summary,
        "runs": runs,
        "pass@k": summary.get("pass@1"),
        "pass@1": summary.get("pass@1"),
        "pass^k": summary.get("pass^k"),
        "pass_rate": summary.get("pass_rate"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--skill", default="", help="Optional skill filter")
    args = ap.parse_args(argv)
    skill = str(args.skill or "").strip() or None
    doc = evaluate_live(args.repo, skill=skill)
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    if doc.get("skipped"):
        return 0
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
