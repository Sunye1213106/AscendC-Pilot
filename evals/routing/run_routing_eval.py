#!/usr/bin/env python3
"""Dry skill-routing eval: description keyword overlap as a router proxy.

This does not call an LLM. It measures whether skill ``description`` frontmatter
is a good routing condition (precision / recall over should_trigger sets).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[2]


def _load_skill_descriptions(repo: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in (repo / "skills" / "workflows", repo / "skills" / "domain"):
        if not root.is_dir():
            continue
        for skill in root.glob("*/SKILL.md"):
            text = skill.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            parts = text.split("---", 2)
            if len(parts) < 3 or yaml is None:
                continue
            meta = yaml.safe_load(parts[1]) or {}
            name = str(meta.get("name") or skill.parent.name)
            desc = str(meta.get("description") or "")
            out[name] = desc
    return out


def _tokenize(text: str) -> set[str]:
    # Split on non-alnum / CJK boundary kept as chars of length >= 2 for CJK runs.
    parts = re.findall(r"[A-Za-z0-9_\.]+|[\u4e00-\u9fff]{2,}", text.lower())
    tokens: set[str] = set()
    for p in parts:
        if re.fullmatch(r"[\u4e00-\u9fff]+", p) and len(p) > 2:
            # Add bigrams for CJK.
            for i in range(len(p) - 1):
                tokens.add(p[i : i + 2])
        tokens.add(p)
    return tokens


def rank_skills(query: str, descriptions: dict[str, str], *, top_k: int = 5) -> list[tuple[str, float]]:
    q = _tokenize(query)
    if not q:
        return []
    scored: list[tuple[str, float]] = []
    for name, desc in descriptions.items():
        d = _tokenize(desc)
        if not d:
            continue
        overlap = len(q & d)
        score = overlap / max(1, len(q))
        # Small boost when skill name tokens appear in query.
        name_tok = _tokenize(name.replace("-", " "))
        score += 0.15 * len(q & name_tok)
        scored.append((name, round(score, 4)))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:top_k]


def evaluate(repo: Path, cases_path: Path) -> dict[str, Any]:
    if yaml is None:
        return {"ok": False, "error": "PyYAML required"}
    cases_doc = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or {}
    cases = list(cases_doc.get("cases") or [])
    descriptions = _load_skill_descriptions(repo)
    results: list[dict[str, Any]] = []
    tp = fp = fn = 0
    for case in cases:
        cid = str(case.get("id") or "")
        query = str(case.get("query") or "")
        should = [str(x) for x in (case.get("should_trigger") or [])]
        should_not = [str(x) for x in (case.get("should_not_trigger") or [])]
        ranked = rank_skills(query, descriptions, top_k=5)
        winners = {name for name, score in ranked if score > 0}
        # Take top-3 as "triggered".
        triggered = {name for name, _ in ranked[:3]}
        hit = [s for s in should if s in triggered]
        miss = [s for s in should if s not in triggered]
        false_pos = [s for s in should_not if s in triggered]
        tp += len(hit)
        fn += len(miss)
        fp += len(false_pos)
        results.append(
            {
                "id": cid,
                "ok": not miss and not false_pos,
                "triggered": list(triggered),
                "hit": hit,
                "miss": miss,
                "false_pos": false_pos,
                "ranked": ranked,
            }
        )
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    passed = sum(1 for r in results if r["ok"])
    return {
        "ok": passed == len(results),
        "summary": {
            "cases": len(results),
            "passed": passed,
            "pass_rate": round(passed / len(results), 3) if results else 0.0,
            "trigger_precision": round(precision, 3),
            "trigger_recall": round(recall, 3),
            "trigger_f1": round(f1, 3),
            "skills_indexed": len(descriptions),
        },
        "runs": results,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--cases", type=Path, default=None)
    args = ap.parse_args(argv)
    cases = args.cases or (args.repo / "evals" / "routing" / "cases.yaml")
    if str(args.repo) not in sys.path:
        sys.path.insert(0, str(args.repo))
    doc = evaluate(args.repo, cases)
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
