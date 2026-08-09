# -*- coding: utf-8 -*-
"""CLI entry for the TilingKey closure workflow.

    python -m testcase_agent.closure.cli rebuild
    python -m testcase_agent.closure.cli apply-rules
    python -m testcase_agent.closure.cli report
    python -m testcase_agent.closure.cli residual
    python -m testcase_agent.closure.cli mine
    python -m testcase_agent.closure.cli assess
    python -m testcase_agent.closure.cli fit
    python -m testcase_agent.closure.cli generate
    python -m testcase_agent.closure.cli replay
    python -m testcase_agent.closure.cli commit
    python -m testcase_agent.closure.cli construct
    python -m testcase_agent.closure.cli explain
    python -m testcase_agent.closure.cli cold-start
    python -m testcase_agent.closure.cli lemma-evidence --combo Dim=Val
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
    ap.add_argument("--root", default=None, help="operator / project root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("rebuild", help="recompute R from raw artefacts")
    sub.add_parser("apply-rules", help="apply proof rules → E_sound")
    sub.add_parser("report", help="per-key closure report")
    p_res = sub.add_parser("residual", help="distance of open keys from witnesses")
    p_res.add_argument(
        "--rows",
        default="50",
        help="number of sample rows to print; use 'all' for the full residue",
    )
    sub.add_parser("mine", help="pair + triple lemma leads")
    sub.add_parser("state", help="print D/R/E/gap counts")
    sub.add_parser("assess", help="sklearn usability report for hard dims")
    sub.add_parser("blocker-model", help="observation-only sklearn blocker report")
    sub.add_parser("corpus", help="corpus summary")
    sub.add_parser("route", help="residual router reason code")
    p_round = sub.add_parser("search-round", help="one bounded directed-search round")
    p_round.add_argument("--budget", type=int, default=64)
    p_round.add_argument("--seed", type=int, default=0)
    p_round.add_argument("--stub", action="store_true", help="use StubOracle (no NPU)")

    sub.add_parser("fit", help="fit surrogate models on current corpus")
    p_gen = sub.add_parser("generate", help="sample a candidate pool")
    p_gen.add_argument("-n", type=int, default=32)
    p_gen.add_argument("--seed", type=int, default=0)
    p_rep = sub.add_parser("replay", help="replay cases via HostOracle (needs NPU)")
    p_rep.add_argument("-n", type=int, default=8)
    p_rep.add_argument("--seed", type=int, default=0)
    p_rep.add_argument("--tag", default="cli_replay")
    p_commit = sub.add_parser("commit", help="commit judged rows into corpus")
    p_commit.add_argument("--csv", required=True, help="path to judged wide CSV")
    p_cons = sub.add_parser("construct", help="build cases for distance-1 open keys")
    p_cons.add_argument("--limit", type=int, default=32)
    p_exp = sub.add_parser("explain", help="explain disagreements on open keys")
    p_exp.add_argument("--open-limit", type=int, default=60)
    p_exp.add_argument("--per-target", type=int, default=24)
    p_exp.add_argument("--dry-run", action="store_true",
                       help="list targets without host replay")
    p_cold = sub.add_parser("cold-start", help="clear R/E/lemmas; stamp cold_start.yaml")
    p_cold.add_argument(
        "--keep-rounds",
        action="store_true",
        help="do not clear rounds/ budget / oracle_suspect",
    )
    p_ev = sub.add_parser("lemma-evidence", help="collect source evidence for a combo")
    p_ev.add_argument(
        "--combo",
        required=True,
        help="Dim=Val[,Dim=Val...] for the lemma under review",
    )
    sub.add_parser("kernel-coverage", help="compute R_kernel from views/kernel.yaml")
    sub.add_parser("tilingdata-coverage", help="tilingdata probe + static over-approx")

    args = ap.parse_args(argv)
    ws = W.default_workspace(args.root).ensure()

    if args.cmd == "cold-start":
        from testcase_agent.closure import cold_start as CS

        return _print(CS.cold_start(ws, clear_rounds=not args.keep_rounds))
    if args.cmd == "lemma-evidence":
        from testcase_agent.closure import lemma_evidence as LE

        try:
            out = LE.collect(args.combo, ws=ws)
        except ValueError as exc:
            return _print({"ok": False, "error": str(exc)})
        # Drop full pack from stdout for readability; paths + ids remain.
        slim = {k: v for k, v in out.items() if k != "pack"}
        return _print(slim)
    if args.cmd == "kernel-coverage":
        from testcase_agent.closure import kernel_domain as KD

        return _print(KD.compute_r_kernel(ws))
    if args.cmd == "tilingdata-coverage":
        from testcase_agent.closure import tilingdata_domain as TD

        return _print(TD.compute_tilingdata_coverage(ws))
    if args.cmd == "rebuild":
        return _print(ledger.rebuild(ws))
    if args.cmd == "apply-rules":
        return _print(lemma.apply_rules(ws))
    if args.cmd == "report":
        return _print(report.report(ws))
    if args.cmd == "residual":
        if str(args.rows).lower() == "all":
            max_rows = None
        else:
            try:
                max_rows = max(0, int(args.rows))
            except ValueError:
                return _print({"ok": False, "error": "--rows must be an integer or 'all'"})
        return _print({"ok": True, **residual.analyse(ws, max_rows=max_rows)})
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
    if args.cmd == "blocker-model":
        df = corpus.dedup(corpus.load(ws))
        return _print({"ok": True, "report": models.write_blocker_model(df, ws)})
    if args.cmd == "corpus":
        return _print({"ok": True, **corpus.summary(ws)})
    if args.cmd == "route":
        from testcase_agent.closure import search_round

        return _print({"ok": True, **search_round.route(ws)})
    if args.cmd == "search-round":
        from testcase_agent.closure import search_round
        from testcase_agent.closure.oracle import StubOracle

        oracle = StubOracle() if args.stub else None
        return _print(search_round.run_round(
            ws, budget=args.budget, seed=args.seed, oracle=oracle,
        ))
    if args.cmd == "fit":
        df = corpus.dedup(corpus.load(ws))
        if df is None or df.empty:
            return _print({"ok": False, "error": "empty corpus"})
        assessment = models.assess(df)
        models.fit(df)
        models_dir = ws.state / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        try:
            import yaml

            (models_dir / "assessment.yaml").write_text(
                yaml.safe_dump(assessment, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        gap = models.write_parent_gap(df, ws) if hasattr(models, "write_parent_gap") else {}
        return _print({"ok": True, "dims": len(assessment), "parent_gap": gap})
    if args.cmd == "generate":
        from testcase_agent.closure import generate as G

        cases, frame = G.pool(n=args.n, seed=args.seed)
        return _print({
            "ok": True,
            "n": len(cases),
            "columns": list(frame.columns) if frame is not None else [],
        })
    if args.cmd == "replay":
        from testcase_agent.closure import generate as G
        from testcase_agent.closure.oracle import HostOracle

        cases, _ = G.pool(n=args.n, seed=args.seed)
        verdicts = HostOracle().judge(cases, tag=args.tag)
        return _print({
            "ok": True,
            "sent": len(cases),
            "judged": sum(1 for v in verdicts if v.verdict),
            "accepted": sum(1 for v in verdicts if v.ok),
            "keys": [v.key for v in verdicts if v.ok],
        })
    if args.cmd == "commit":
        import pandas as pd

        path = args.csv
        frame = pd.read_csv(path)
        out = corpus.commit(frame, ws)
        recheck = lemma.reverify_active(ws) if hasattr(lemma, "reverify_active") else {}
        return _print({"ok": True, "path": str(out), "reverify": recheck})
    if args.cmd == "construct":
        from testcase_agent.closure import construct

        analysis = residual.analyse(ws)
        targets = residual.distance_one_targets(analysis)[: args.limit]
        built = 0
        n_cases = 0
        for t in targets:
            try:
                inst = W.decode(int(t["key"]))
                cs = construct.build(inst)
                n_cases += len(cs)
                built += 1
            except Exception:
                continue
        return _print({
            "ok": True,
            "targets": len(targets),
            "built": built,
            "cases": n_cases,
        })
    if args.cmd == "explain":
        from testcase_agent.closure import construct
        from testcase_agent.closure import explain

        if args.dry_run:
            analysis = residual.analyse(ws)
            return _print({
                "ok": True,
                "dry_run": True,
                "open": analysis.get("open"),
                "distance_1": len(residual.distance_one_targets(analysis)),
            })
        out = explain.run_explain(
            construct.build,
            open_limit=args.open_limit,
            per_target=args.per_target,
            ws=ws,
        )
        return _print({"ok": True, **out})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
