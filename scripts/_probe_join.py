# -*- coding: utf-8 -*-
"""判定可达性靠查表, 不靠求解器。

每个 key 问一次 Z3 是行不通的: 树里全是整数除和取模, 属于不可判定的片段, 单次
查询就撞满 5 秒预算, 8705 个 key 要跑几个小时。但反过来算是廉价的 ——
`_probe_eval.py` 用 5.7 秒枚举完了 14 个维度的等价类。

所以改成先建表:

  1. 一个变量在所有维度里被比较的阈值合起来切段, 每段取一个代表值 —— 全局统一,
     否则两维对同一个变量取不同代表值, 结果无法拼。
  2. 维度按"共享变量"连成分量。不同分量没有共同变量, 取值互不牵制, 可以分开算。
  3. 每个分量枚举一次自己的格子, 记下内部维度真正同时出现过的值组合。

之后判一个 key: 把它在每个分量上的投影拿去查表。全部命中就是可达 —— 而且手里
就有那组具体输入。有一个分量枚举过却查不到, 就是不可达, 证据是"完整枚举里从未
出现"。分量太大枚举不了, 那一段才是 unknown。

    python scripts/_probe_join.py            # 分量结构与格子数
    python scripts/_probe_join.py --build     # 建表并判定 8705 个 key
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "scripts"))

from _probe_eval import (  # noqa: E402
    Expr,
    Premises,
    Unknown,
    _domain_for,
    _domains,
    samples,
)


def _fmt(n: float) -> str:
    return f"{n:,}" if n < 10**15 else f"{n:.3g}"


class Plan:
    """维度、变量、代表值, 以及由共享变量切出的分量。"""

    def __init__(self, cap: int, wide: int = 0) -> None:
        blob = json.loads((CACHE / "fag_derive.json").read_text("utf-8"))
        self.premises = Premises(blob.get("premises") or [])
        self.domains, self.constants = _domains()

        self.trees: dict[str, Expr] = {}
        self.vars: dict[str, set[str]] = {}
        cuts: dict[str, set] = defaultdict(set)
        for fld in blob.get("fields", []):
            expr = fld.get("value_expr")
            if not expr:
                continue
            name = str(fld["name"])
            tree = Expr(expr)
            got, names = tree.cuts()
            self.trees[name] = tree
            self.vars[name] = names
            for k, v in got.items():
                cuts[k] |= v
        for k, v in self.premises.cuts.items():
            cuts[k] |= v
        self.cuts = cuts

        # 代表值全局统一: 同一个变量在每个维度里取同一组值, 否则分量之间拼不起来。
        every = set(cuts) | {v for vs in self.vars.values() for v in vs} | self.premises.vars
        self.reps: dict[str, list[Any]] = {
            v: samples(v, cuts.get(v, set()), _domain_for(v, self.domains), self.constants)
            for v in sorted(every)
        }

        self.groups = self._components()
        self.cap = cap

    def _components(self) -> list[list[str]]:
        """共享变量的维度必须一起枚举; 不共享的可以分开。

        前提也参与连接: 一条前提只有在它读的变量都落在同一分量里时才能在那里检验,
        否则就只能忽略, 而忽略前提会把被算子拒绝的输入当成可达。
        """
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for name, names in self.vars.items():
            find(f"dim:{name}")
            for v in names:
                union(f"dim:{name}", f"var:{v}")
        for tree in self.premises.trees:
            _, names = tree.cuts()
            names = [v for v in names if v in self.reps]
            for v in names[1:]:
                union(f"var:{names[0]}", f"var:{v}")

        out: dict[str, list[str]] = defaultdict(list)
        for name in self.vars:
            out[find(f"dim:{name}")].append(name)
        return sorted((sorted(g) for g in out.values()), key=len, reverse=True)

    def group_vars(self, group: list[str]) -> list[str]:
        got: set[str] = set()
        for name in group:
            got |= self.vars[name]
        return sorted(v for v in got if v in self.reps)

    def cells(self, group: list[str]) -> int:
        total = 1
        for v in self.group_vars(group):
            total *= max(1, len(self.reps[v]))
        return total


def show(plan: Plan) -> None:
    print(f"维度 {len(plan.trees)} 个, 变量 {len(plan.reps)} 个, 分量 {len(plan.groups)} 个\n")
    doable = 0
    for i, group in enumerate(plan.groups):
        n = plan.cells(group)
        mark = "可枚举" if n <= plan.cap else "超上限"
        if n <= plan.cap:
            doable += len(group)
        print(f"[{i}] {len(group)} 维 / {len(plan.group_vars(group))} 变量 / {_fmt(n)} 格  {mark}")
        print(f"     {', '.join(group)}")
    print(f"\n可枚举的维度: {doable}/{len(plan.trees)}")


def build(plan: Plan) -> dict[int, Any]:
    """逐分量枚举, 记下内部维度同时出现过的值组合。"""
    tables: dict[int, Any] = {}
    for i, group in enumerate(plan.groups):
        n = plan.cells(group)
        if n > plan.cap:
            print(f"[{i}] {len(group)} 维 {_fmt(n)} 格 —— 跳过, 这些维度判 unknown")
            tables[i] = None
            continue
        names = plan.group_vars(group)
        axes = [plan.reps[v] for v in names]
        seen: dict[tuple, dict[str, Any]] = {}
        started = time.time()
        unknown = refused = 0
        for combo in itertools.product(*axes):
            env = dict(zip(names, combo))
            if plan.premises.rejects(env):
                refused += 1
                continue
            row = []
            for dim in group:
                try:
                    row.append(plan.trees[dim].value(env))
                except Unknown:
                    row.append(None)
                    unknown += 1
            key = tuple(row)
            # 第一个见证就留着: 判定说"可达"时要拿得出具体输入。
            seen.setdefault(key, env)
        tables[i] = {"dims": group, "combos": seen}
        print(
            f"[{i}] {len(group)} 维 {_fmt(n)} 格 -> {len(seen)} 个组合"
            f"  ({time.time() - started:.1f}s, 拒 {refused}, 算不出 {unknown})"
        )
    return tables


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", action="store_true", help="建表")
    ap.add_argument("--cap", type=int, default=4_000_000, help="单个分量的格子上限")
    args = ap.parse_args()

    plan = Plan(args.cap)
    show(plan)
    if args.build:
        print()
        build(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
