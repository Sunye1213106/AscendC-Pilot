# -*- coding: utf-8 -*-
"""让求解器自己吐出维度之间的排除规则, 写成 derived_rules.yaml。

覆盖运行需要知道哪些 TilingKey 可以放弃。这些排除条件原先是手写的 ——
`replay_verdict.py` 的 `UNREACHABLE` / `UNREACHABLE_COMBOS`、`replay/constraints.py`
的 `RULES` —— 每一条都是一次人读源码的结论, 没有机器复核过, 也没人说得清那张表
全不全。

可是同样的事实推导里已经有了: 19 个维度都是 host 状态上的表达式, 问「这两个维度
取值能不能同时成立」就是一次 UNSAT 查询。这个脚本把这些查询全问一遍。

只用 UNSAT 那一侧 —— 那是求解器唯一可信的方向。SAT 可能来自过近似维度放进来的
不可能状态, 所以 `unknown` 绝不会变成规则, 只会记进 undecided。

    python scripts/_probe_derived_rules.py                    # 全量
    python scripts/_probe_derived_rules.py --no-pairs         # 只问单值, 快
    python scripts/_probe_derived_rules.py --dims IsNzOut SplitAxis IsTndSwizzle

先跑 `scripts/_probe_derive.py`, 本脚本读它留在 `.probe_cache/` 的结果。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "scripts"))

CACHE = ROOT / ".probe_cache"
DERIVE = CACHE / "fag_derive.json"


def _identities() -> dict[str, str]:
    """What each bound variable denotes, from the operator's binding table.

    Empty rather than fatal when the table is missing: without it the solver
    isolates more than it needs to, which loses conflicts but invents none.
    """
    from replay import runner as R
    from replay.bridge_spec import BridgeSpec

    path = R.default().manifest.package / "bridge_spec.yaml"
    if not path.is_file():
        print(f"no binding table at {path}; variables stay isolated")
        return {}
    return BridgeSpec.load(path).identities()


def _observations(glob: str):
    """Every replayed case as `dimension -> value`, from the wide tables."""
    import csv

    from replay import runner as R

    for path in sorted(R.CACHE.glob(glob)):
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("ok") != "1":
                    continue  # a refused case ran no tiling, so it saw nothing
                got = {
                    k[len("dim_"):]: v
                    for k, v in row.items()
                    if k.startswith("dim_") and v not in (None, "")
                }
                if got:
                    yield got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dims", nargs="*", default=[], help="只问这几维")
    ap.add_argument("--no-pairs", action="store_true", help="跳过成对扫描")
    ap.add_argument("--no-implications", action="store_true", help="不折叠蕴含")
    ap.add_argument("--timeout", type=int, default=5000, help="每次查询的求解毫秒")
    # Default resolved from the replay runner rather than spelled out, because
    # the reader (`rule_engine.default_book`) resolves it the same way. Written
    # to `.probe_cache/` while read from `.probe_cache/replay/`, the solver's
    # rules were produced every time and consumed never.
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--witness", default="*key_cases*.csv",
        help="拿来反驳规则的回放语料 glob; 空字符串跳过这道门",
    )
    ap.add_argument("--slice", type=int, default=0,
                    help="成对扫描的第几片 (0..slices-1)")
    ap.add_argument("--slices", type=int, default=1,
                    help="把成对扫描拆成几片; >1 时配合 --slice 与 --merge-out")
    ap.add_argument("--merge-out", type=Path, default=None,
                    help="把本片的成对规则追加合并进这个 yaml (跨片累积)")
    args = ap.parse_args()

    import yaml

    import _probe_reach as probe
    from replay import runner as R

    if args.out is None:
        args.out = R.CACHE / "derived_rules.yaml"
    if args.slices > 1 and args.merge_out is None:
        args.merge_out = R.CACHE / "derived_rules_pairs.yaml"

    pair_slice = (args.slice, args.slices) if args.slices > 1 else None

    from uo_init import key_reachability as kr
    from uo_init.derived_rules import (
        KIND_IMPLICATION,
        KIND_PAIR,
        KIND_VALUE,
        derive_rules,
        refute,
        source_hash,
    )
    from uo_init.key_reachability import KeyReachability

    doc, var_model, schema, _binding = probe.load()
    print("building the solver context...", flush=True)
    t0 = time.time()
    # The binding table doubles as proof of what a variable denotes. Without
    # it every shape variable is isolated per dimension, and no conflict that
    # rests on one tensor having one shape can be found -- which is most of
    # them.
    identities = _identities()
    reach = KeyReachability.from_derivation(
        doc,
        var_model,
        timeout_ms=args.timeout,
        rlimit=kr.DEFAULT_RLIMIT,
        hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
        identities=identities,
    )
    built = time.time() - t0
    summary = reach.summary()
    print(
        f"built in {built:.1f}s  "
        f"compiled {summary['dimensions_compiled']}/{summary['dimensions_total']}  "
        f"exact {summary['dimensions_exact']}  "
        f"shared {len(summary['identity_shared'])} "
        f"isolated {len(summary['identity_isolated'])}"
        f"  (bindings vouched for {len(identities)})",
        flush=True,
    )

    # The declared value domain is the template's business, not the engine's;
    # pass it in rather than letting the rule pass guess what a dimension holds.
    candidates = {
        dim.name: dim.value_domain
        for dim in schema.dims
        if not args.dims or dim.name in args.dims
    }

    state = {"phase": "", "at": 0.0}

    def on_progress(phase: str, index: int, total: int) -> None:
        now = time.time()
        if phase != state["phase"]:
            state["phase"] = phase
            state["at"] = 0.0
            print(f"\n{phase}: {total} queries", flush=True)
        if now - state["at"] < 15 and index + 1 != total:
            return
        state["at"] = now
        print(f"  {index + 1}/{total}  {(now - t0):.0f}s elapsed", flush=True)

    t1 = time.time()
    out = derive_rules(
        reach,
        candidates,
        pairs=not args.no_pairs,
        implications=not args.no_implications,
        on_progress=on_progress,
        pair_slice=pair_slice,
    )
    solved = time.time() - t1

    # Nothing leaves here without facing the replays. A derived rule says the
    # host cannot do something; a recorded run that did it settles that against
    # the solver, and the rule has to be pulled rather than published.
    refuted: list = []
    if args.witness:
        rows = list(_observations(args.witness))
        if rows:
            refuted = refute(out.rules, rows)
            wrong = {id(r) for r, _ in refuted}
            out.rules = [r for r in out.rules if id(r) not in wrong]
            out.stats["refuted_by_replay"] = len(refuted)
            out.stats["observations"] = len(rows)

    provenance = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "operator": str(getattr(doc, "op_name", "") or ""),
        "arch": str(getattr(doc, "architecture", "") or ""),
        # Rules outlive the derivation that proved them only by accident, so
        # anything reading these back must be able to tell they went stale.
        "source_hash": source_hash(DERIVE.read_bytes()) if DERIVE.is_file() else "",
        "solver": {
            "dimensions_total": summary["dimensions_total"],
            "dimensions_compiled": summary["dimensions_compiled"],
            "dimensions_exact": summary["dimensions_exact"],
            "timeout_ms": args.timeout,
            "build_seconds": round(built, 1),
            "solve_seconds": round(solved, 1),
        },
    }
    doc = out.to_dict(provenance=provenance)
    if refuted:
        # Kept in the artifact, not just the terminal: each one is a derivation
        # defect with a reproducer attached, and that is the thing worth fixing.
        doc["refuted_by_replay"] = [
            {**rule.to_dict(), "counterexample": evidence} for rule, evidence in refuted
        ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )

    if args.merge_out is not None:
        # Accumulate slices into one document shaped exactly like a whole-scan
        # result, so the reader cannot tell a sliced scan from an unsliced one.
        # `statement` is the identity: it is `describe()`, which spells out the
        # dimensions and values a rule excludes and so is unique per rule.
        # A rule that survived the refute gate here is kept; one refuted in any
        # slice is dropped from the accumulation too, because the gate's
        # verdict is about the derivation, not about this slice.
        existing: dict = {}
        if args.merge_out.is_file():
            existing = yaml.safe_load(
                args.merge_out.read_text(encoding="utf-8")) or {}
        refuted_statements = {r.describe() for r, _ in refuted}
        keep = [r for r in (existing.get("rules") or [])
                if r.get("statement") not in refuted_statements]
        by_statement = {r.get("statement"): i for i, r in enumerate(keep)}
        for rule in out.rules:
            rd = rule.to_dict()
            if rd["statement"] in by_statement:
                keep[by_statement[rd["statement"]]] = rd
            else:
                by_statement[rd["statement"]] = len(keep)
                keep.append(rd)
        merged = dict(doc)
        merged["rules"] = keep
        merged["counts"] = {**(doc.get("counts") or {}), "rules": len(keep)}
        merged["slices_done"] = sorted(
            set(existing.get("slices_done") or ()) | {args.slice})
        args.merge_out.parent.mkdir(parents=True, exist_ok=True)
        args.merge_out.write_text(
            yaml.safe_dump(merged, sort_keys=False, allow_unicode=True,
                           width=100), encoding="utf-8")
        print(f"merged slice {args.slice}/{args.slices}: "
              f"{len(out.rules)} rules this slice -> {args.merge_out} "
              f"(total {len(keep)}, slices done "
              f"{merged['slices_done']})", flush=True)

    print(f"\n{out.queries} queries in {solved:.0f}s -> {args.out}")
    for kind in (KIND_VALUE, KIND_PAIR, KIND_IMPLICATION):
        rules = out.of_kind(kind)
        print(f"\n{kind}: {len(rules)}")
        for rule in rules[:40]:
            print(f"  {rule.describe()}")
        if len(rules) > 40:
            print(f"  ... {len(rules) - 40} more")
    print(f"\nundecided (not excluded, not shown reachable): {len(out.undecided)}")
    if out.skipped:
        print(f"skipped dimensions: {out.skipped}")

    if refuted:
        print(f"\nREFUTED BY REPLAY: {len(refuted)} rule(s) the host contradicts")
        for rule, evidence in refuted:
            print(f"    {rule.describe()}")
            print(f"        but a real run produced {evidence}")
        print(
            "\n求解器证出了 host 做得到的事不可能, 说明那一维的表达式与 host 不符 —— "
            "是推导缺陷, 不是回放噪声。规则已从产物里撤下。"
        )
    print(
        "\n每一条都要回到源码核对。规则会让覆盖运行放弃整批 key, 一条错的比没有更糟。"
    )
    return 1 if refuted else 0


if __name__ == "__main__":
    raise SystemExit(main())
