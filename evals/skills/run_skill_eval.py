#!/usr/bin/env python3
"""Dry skill eval: with_skill vs without_skill routing + asset presence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[2]


def _ensure_path(repo: Path) -> None:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))


def _skill_dir(repo: Path, skill: str) -> Path | None:
    d = repo / "skills" / skill
    if (d / "SKILL.md").is_file():
        return d
    return None


def evaluate_skill(repo: Path, skill_dir: Path) -> dict[str, Any]:
    _ensure_path(repo)
    from evals.harness.runner import summarize_runs
    from evals.routing.run_routing_eval import rank_skills, _load_skill_descriptions

    cases_path = skill_dir / "cases.yaml"
    expected_path = skill_dir / "expected.yaml"
    if yaml is None or not cases_path.is_file():
        return {"ok": False, "error": "missing cases.yaml or PyYAML"}
    cases_doc = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or {}
    expected = yaml.safe_load(expected_path.read_text(encoding="utf-8")) if expected_path.is_file() else {}
    skill = str(cases_doc.get("skill") or skill_dir.name)
    sd = _skill_dir(repo, skill)
    descriptions = _load_skill_descriptions(repo)
    # without_skill: blank out this skill's description
    without = dict(descriptions)
    without[skill] = ""

    runs: list[dict[str, Any]] = []
    for case in cases_doc.get("cases") or []:
        query = str(case.get("query") or "")
        expect = str(case.get("expect_skill") or skill)
        forbid = str(case.get("forbid_skill") or "")
        with_rank = rank_skills(query, descriptions, top_k=5)
        without_rank = rank_skills(query, without, top_k=5)
        with_top = {n for n, _ in with_rank[:3]}
        without_top = {n for n, _ in without_rank[:3]}
        ok_with = expect in with_top
        ok_without_worse = expect not in without_top or (
            with_rank and without_rank and with_rank[0][0] == expect and without_rank[0][0] != expect
        )
        forbid_ok = (not forbid) or (forbid not in with_top)
        refs_ok = True
        for rel in case.get("expect_references") or []:
            if sd is None or not (sd / rel).is_file():
                # Allow pending gotchas until P4 lands; record but don't fail dry smoke hard
                # unless expected.yaml requires it.
                if expected.get("require_gotchas") and "gotchas" in str(rel):
                    refs_ok = (sd / rel).is_file() if sd else False
                else:
                    refs_ok = refs_ok and (sd is not None and (sd / rel).is_file())
        ok = ok_with and forbid_ok
        # Skill utility signal: with_skill beats without_skill when expected is specific.
        utility = 1 if ok_with and ok_without_worse else 0
        runs.append(
            {
                "id": case.get("id"),
                "ok": ok and (refs_ok or not expected.get("require_gotchas")),
                "ok_with_skill": ok_with,
                "utility_gain": utility,
                "forbid_ok": forbid_ok,
                "refs_ok": refs_ok,
                "with_top": list(with_top),
                "without_top": list(without_top),
                "context_tokens": 0,
                "tool_calls": 0,
                "verified_facts": int(ok_with),
            }
        )
    summary = summarize_runs(runs)
    skill_file_ok = sd is not None and (sd / "SKILL.md").is_file()
    if expected.get("require_skill_file") and not skill_file_ok:
        summary["skill_file_missing"] = True
    min_rate = float(expected.get("min_pass_rate") or 0.0)
    ok = summary.get("pass_rate", 0) >= min_rate and skill_file_ok
    return {"ok": ok, "skill": skill, "summary": summary, "runs": runs}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--skill", default="operator-analysis")
    args = ap.parse_args(argv)
    skill_dir = args.repo / "evals" / "skills" / args.skill
    doc = evaluate_skill(args.repo, skill_dir)
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
