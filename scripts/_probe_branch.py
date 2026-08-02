# -*- coding: utf-8 -*-
"""把一维的 if-else 链拆开, 逐分支问「这条路的守卫本身可满足吗」。

`_probe_dimvals.py` 说某一维产不出某个值, 但只给出一个整体的 unsat。要修就得
知道是哪一条分支被掐死的: 表达式是 Ite 链, 一个取值对应若干条「守卫合取 → 该
值」的路径, 该取值不可达 ⟺ 每一条路径的守卫都不可满足。逐条问, 就能把矛盾缩
到具体某个守卫上, 再回源码看那个守卫是不是被推导写错了。

    python scripts/_probe_branch.py IsNzOut 1
    python scripts/_probe_branch.py DeterType 3 --max-paths 400
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"


def paths(node: Any, conds: list, out: list, cap: int) -> None:
    """每条 (守卫合取, 叶子值)。Ite 链是 DAG, 所以只能有上限地展开。"""
    if len(out) >= cap:
        return
    if isinstance(node, dict) and node.get("op") == "if_then_else":
        cond = node.get("condition")
        paths(node.get("then"), conds + [cond], out, cap)
        paths(node.get("else"), conds + [{"op": "not", "arg": cond}], out, cap)
        return
    out.append((conds, node))


def leaf_value(node: Any) -> Any:
    if isinstance(node, (int, bool)):
        return node
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        for k in ("lit", "value"):
            if k in node and not isinstance(node[k], (dict, list)):
                return node[k]
        return f"<{node.get('op') or node.get('var') or '?'}>"
    return node


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dim")
    ap.add_argument("value")
    ap.add_argument("--max-paths", type=int, default=200)
    ap.add_argument("--timeout", type=int, default=5000)
    ap.add_argument("--show", type=int, default=6, help="打印几条守卫全文")
    args = ap.parse_args()

    import _probe_reach as probe

    from uo_init import key_reachability as kr
    from uo_init.key_reachability import KeyReachability

    doc, var_model, schema, binding = probe.load()
    reach = KeyReachability.from_derivation(
        doc,
        var_model,
        timeout_ms=args.timeout,
        rlimit=kr.DEFAULT_RLIMIT,
        hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
    )
    backend = getattr(reach, "_backend", None)
    if backend is None:
        raise SystemExit("no solver backend")

    fields = {f["name"]: f for f in json.loads((CACHE / "fag_derive.json").read_text("utf-8"))["fields"]}
    fld = fields.get(args.dim)
    if fld is None:
        raise SystemExit(f"unknown dimension {args.dim}")

    out: list = []
    paths(fld.get("value_expr"), [], out, args.max_paths)
    print(f"{args.dim}: 展开出 {len(out)} 条路径" + (" (已达上限)" if len(out) >= args.max_paths else ""))

    want = str(args.value)
    mine = [(c, n) for c, n in out if str(leaf_value(n)) == want]
    print(f"其中产出 {args.dim}={want} 的有 {len(mine)} 条\n")
    if not mine:
        others = sorted({str(leaf_value(n)) for _, n in out})
        print(f"一条都没有 —— 这一维在展开到的范围内只能产出: {others}")
        return 0

    verdicts: dict[str, int] = {}
    shown = 0
    for conds, node in mine:
        expr = conds[0] if len(conds) == 1 else {"op": "and", "args": conds}
        hit = backend.solve_expr(expr, label="branch")
        status = str((hit or {}).get("status") or "?")
        verdicts[status] = verdicts.get(status, 0) + 1
        if status == "unsat" and shown < args.show:
            shown += 1
            print(f"[不可满足的守卫 #{shown}] 深度 {len(conds)}")
            core = (hit or {}).get("unsat_core") or ()
            if core:
                print(f"  core: {', '.join(str(c) for c in core[:6])}")
            for c in conds:
                print(f"  · {json.dumps(c, ensure_ascii=False)[:220]}")
            print()

    print("逐分支判决: " + ", ".join(f"{k}={v}" for k, v in sorted(verdicts.items())))
    if verdicts.get("sat"):
        print(
            f"\n有 {verdicts['sat']} 条守卫是可满足的 —— 那么 {args.dim}={want} 本该可达。\n"
            "整维却判 unsat, 说明矛盾来自守卫之外: 多半是链式覆盖(后写盖前写)或\n"
            "位置过滤把这条分支的写点摘掉了, 使它没能进入最终表达式。"
        )
    else:
        print(f"\n所有产出 {want} 的守卫都不可满足 —— 矛盾在守卫里, 按上面的 core 回源码核对。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
