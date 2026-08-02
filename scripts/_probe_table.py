# -*- coding: utf-8 -*-
"""每一维的判定表有多大 —— 决定这条路是直接枚举还是要分层连接。

`_probe_atoms.py` 说全 19 维只问了输入 95 个原子判断。那么输入空间对这些维度
而言只有有限个等价类, 每一维在类内取值恒定, 于是「这一维能取什么值」可以列成
一张表, 而不必每个 key 现算一次。

能不能直接列, 取决于每一维实际依赖几个变量: 依赖 3 个变量、每个切 6 段, 就是
216 行, 枚举即可; 依赖 20 个就得按共享变量做连接。这个脚本量的就是这件事。

    python scripts/_probe_table.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"

_CMP = ("eq", "ne", "lt", "le", "gt", "ge")


def scan(node: Any, seen: set[int], vars_: set[str], cuts: dict[str, set], opaque: list[str]) -> None:
    if isinstance(node, list):
        for x in node:
            scan(x, seen, vars_, cuts, opaque)
        return
    if not isinstance(node, dict) or id(node) in seen:
        return
    seen.add(id(node))
    op = node.get("op")
    name = node.get("var")
    if isinstance(name, str):
        vars_.add(name)
    if op in _CMP:
        value = node.get("value")
        if isinstance(name, str) and not isinstance(value, (dict, list)):
            cuts.setdefault(name, set()).add(value)
        elif "lhs" in node or "rhs" in node:
            opaque.append(str(op))
    for v in node.values():
        scan(v, seen, vars_, cuts, opaque)


def main() -> int:
    fields = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))["fields"]

    rows = []
    shared: dict[str, set[str]] = defaultdict(set)
    for f in fields:
        vars_: set[str] = set()
        cuts: dict[str, set] = {}
        opaque: list[str] = []
        scan(f.get("value_expr"), set(), vars_, cuts, opaque)
        cells = 1
        for name in vars_:
            cells *= len(cuts.get(name, ())) + 1
        for name in vars_:
            shared[name].add(f["name"])
        rows.append(
            {
                "name": f["name"],
                "exactness": f["exactness"],
                "vars": len(vars_),
                "cut_vars": len(cuts),
                "cells": cells,
                "opaque": len(opaque),
                "names": sorted(vars_),
            }
        )

    print(f"{'维度':<16} {'分级':<18} {'变量':>4} {'切段变量':>8} {'格子数':>12} {'复合比较':>8}")
    print("-" * 82)
    for r in sorted(rows, key=lambda r: r["cells"]):
        print(
            f"  {r['name']:<14} {r['exactness']:<18} {r['vars']:>4} {r['cut_vars']:>8}"
            f" {r['cells']:>12,} {r['opaque']:>8}"
        )

    clean = [r for r in rows if not r["opaque"]]
    dirty = [r for r in rows if r["opaque"]]
    print(f"\n只用纯比较的维度 {len(clean)} 个, 最大格子数 {max((r['cells'] for r in clean), default=0):,}")
    print(f"含复合比较的维度 {len(dirty)} 个: {', '.join(r['name'] for r in dirty)}")

    print("\n被多维共用的变量 (连接就靠它们):")
    for name, dims in sorted(shared.items(), key=lambda kv: -len(kv[1])):
        if len(dims) < 2:
            continue
        print(f"  {name:<42} {len(dims):2} 维")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
