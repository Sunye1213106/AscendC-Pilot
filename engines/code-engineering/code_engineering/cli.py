# -*- coding: utf-8 -*-
"""CLI for CE impact / regression."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from code_engineering.impact import impact_from_diff
from code_engineering.regress import regress_cases


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ce-impact")
    ap.add_argument("--diff", required=True, help="unified diff file or - for stdin")
    ap.add_argument("--root", default=".", help="AscendC-Pilot / operator root")
    ap.add_argument("--limit", type=int, default=64)
    args = ap.parse_args(argv)

    if args.diff == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.diff).read_text(encoding="utf-8", errors="replace")

    root = Path(args.root)
    impact = impact_from_diff(text, project_root=root, uo_root=root / ".ascendc-pilot" / "uo")
    regress = regress_cases(impact, project_root=root, limit=args.limit)
    doc = {"impact": impact.to_dict(), "regress": regress}
    out = root / ".ascendc-pilot" / "ce" / "impact.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return 0 if regress.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
