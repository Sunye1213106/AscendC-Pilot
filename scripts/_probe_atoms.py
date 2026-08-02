# -*- coding: utf-8 -*-
"""这 19 维一共问了输入多少个「是不是」的问题。

判一个 key 现在要把 19 棵大树整棵交给 Z3 联合求解一次, 8705 次。但树再大, 它
问输入的其实只是有限个原子判断: `d > 64`、`layout == 'TND'`、`d % 16 == 0`。
把这些原子摊平, 每一维就退化成「原子的真值组合 → 该维取值」的一张表, 拼接 19
维变成查表求交, 不必逐 key 跑求解器。

这个脚本量的是那张表可不可行: 全局有多少个原子、压在多少个变量上、每个变量被
切成几段, 以及有多少原子不是纯比较(除法/取模/变量间比较) —— 后者不能直接切成
区间, 是这条路上唯一要单独处理的东西。

    python scripts/_probe_atoms.py
    python scripts/_probe_atoms.py --dim IsNzOut   # 只看一维, 列出它的原子
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"

_CMP = ("eq", "ne", "lt", "le", "gt", "ge")
_NONLINEAR = ("div", "mod", "mul")


class Scan:
    def __init__(self) -> None:
        # (var, op, value) -> 出现在哪些维度
        self.atoms: dict[tuple[str, str, Any], set[str]] = defaultdict(set)
        # 不是「变量 op 常量」的比较: 两边都是表达式
        self.opaque: dict[str, set[str]] = defaultdict(set)
        # 非线性节点出现在哪些维度
        self.nonlinear: dict[str, set[str]] = defaultdict(set)

    def walk(self, node: Any, dim: str, seen: set[int]) -> None:
        if isinstance(node, list):
            for x in node:
                self.walk(x, dim, seen)
            return
        if not isinstance(node, dict):
            return
        if id(node) in seen:
            return
        seen.add(id(node))
        op = node.get("op")
        if op in _CMP:
            var, value = node.get("var"), node.get("value")
            if isinstance(var, str) and not isinstance(value, (dict, list)):
                self.atoms[(var, op, value)].add(dim)
            else:
                self.opaque[_shape_of(node)].add(dim)
        elif op in _NONLINEAR:
            self.nonlinear[op].add(dim)
        for v in node.values():
            self.walk(v, dim, seen)


def _shape_of(node: dict) -> str:
    """A short label for a comparison whose sides are not var-vs-constant."""
    def side(x: Any) -> str:
        if isinstance(x, dict):
            return str(x.get("op") or x.get("var") or "?")
        return type(x).__name__
    return f"{node.get('op')}({side(node.get('lhs'))},{side(node.get('rhs'))})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dim", help="只看这一维")
    args = ap.parse_args()

    fields = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))["fields"]
    scan = Scan()
    per_dim: dict[str, int] = {}
    for f in fields:
        name = f["name"]
        if args.dim and name != args.dim:
            continue
        before = len(scan.atoms)
        scan.walk(f.get("value_expr"), name, set())
        per_dim[name] = len(scan.atoms) - before

    by_var: dict[str, set[tuple[str, Any]]] = defaultdict(set)
    for (var, op, value) in scan.atoms:
        by_var[var].add((op, value))

    print(f"原子判断 {len(scan.atoms)} 个, 压在 {len(by_var)} 个变量上\n")
    print(f"{'变量':<40} 切成几段  阈值")
    print("-" * 96)
    for var, cuts in sorted(by_var.items(), key=lambda kv: -len(kv[1])):
        vals = sorted({str(v) for _, v in cuts})
        print(f"  {var:<38} {len(cuts):3}     {', '.join(vals[:12])}")

    if args.dim:
        print(f"\n{args.dim} 的原子:")
        for (var, op, value), dims in sorted(scan.atoms.items()):
            print(f"  {var} {op} {value}")

    print("\n不是「变量 op 常量」的比较 (要单独处理):")
    if scan.opaque:
        for shape, dims in sorted(scan.opaque.items(), key=lambda kv: -len(kv[1])):
            print(f"  {shape:34} 出现在 {len(dims)} 维: {', '.join(sorted(dims)[:6])}")
    else:
        print("  无")

    print("\n非线性运算:")
    for op, dims in sorted(scan.nonlinear.items()):
        print(f"  {op:6} 出现在 {len(dims)} 维: {', '.join(sorted(dims)[:8])}")

    space = 1
    for cuts in by_var.values():
        space *= max(len(cuts) + 1, 2)
    print(f"\n每维贡献的新原子: " + ", ".join(f"{k}={v}" for k, v in sorted(per_dim.items(), key=lambda kv: -kv[1])[:8]))
    print(f"朴素格子数上界 {space:.3g} —— 只作参考, 真正要枚举的是各维实际用到的那一小撮")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
