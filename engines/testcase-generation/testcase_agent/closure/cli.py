# -*- coding: utf-8 -*-
"""CLI entry for the TilingKey closure workflow.

    python -m testcase_agent.closure.cli rebuild
    python -m testcase_agent.closure.cli apply-rules
    python -m testcase_agent.closure.cli report
    python -m testcase_agent.closure.cli residual
    python -m testcase_agent.closure.cli mine
    python -m testcase_agent.closure.cli assess
"""

from __future__ import annotations

import argparse
import json
import sys

from testcase_agent.closure import corpus
from testcase_agent.closure import ledger
from testcase_agent.closure import lemma
from testcase_agent.closure import mine
from testcase_agent.closure import models
from testcase_agent.closure import report
from testcase_agent.closure import residual
from testcase_agent.closure import workspace as W


def _print(doc: dict) -> int:
    print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    return 0 if doc.get("ok", True) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tg-closure")
    ap.add_argument("--root", default=None, help="AscendC-Pilot repo root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("rebuild", help="recompute R from raw artefacts")
    sub.add_parser("apply-rules", help="apply proof rules → E_sound")
    sub.add_parser("report", help="per-key closure report")
    sub.add_parser("residual", help="distance of open keys from witnesses")
    sub.add_parser("mine", help="pair + triple lemma leads")
    sub.add_parser("state", help="print D/R/E/gap counts")
    sub.add_parser("assess", help="sklearn usability report for hard dims")
    sub.add_parser("corpus", help="corpus summary")

    args = ap.parse_args(argv)
    ws = W.default_workspace(args.root).ensure()

    if args.cmd == "rebuild":
        return _print(ledger.rebuild(ws))
    if args.cmd == "apply-rules":
        return _print(lemma.apply_rules(ws))
    if args.cmd == "report":
        return _print(report.report(ws))
    if args.cmd == "residual":
        return _print({"ok": True, **residual.analyse(ws)})
    if args.cmd == "mine":
        pairs = mine.mine_pairs(ws, top=30)
        triples = mine.mine_triples(ws, top=30)
        return _print({
            "ok": True,
            "pairs": len(pairs),
            "triples": len(triples),
            "top_pairs": pairs[:5],
            "top_triples": triples[:5],
        })
    if args.cmd == "state":
        return _print({"ok": True, **ledger.state(ws)})
    if args.cmd == "assess":
        df = corpus.dedup(corpus.load(ws))
        return _print({"ok": True, "nodes": models.assess(df)})
    if args.cmd == "corpus":
        return _print({"ok": True, **corpus.summary(ws)})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
