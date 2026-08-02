# -*- coding: utf-8 -*-
"""给输入赋具体值, 直接算出每一维取什么 —— 不用求解器。

反向问「这 19 维能否同时成立」要把整棵树交给 Z3, 而树里全是整数除和取模, 属于
不可判定的片段, 求解器经常只能超时。正向走一遍则完全没有这个问题: 叶子一旦有
具体数, `d % 16`、`CeilDiv(s2, s2Inner)` 都是算术, 算出来就是了。「复合比较」
这个障碍只存在于符号世界。

求值本身在 `uo_init.concrete_eval`, 这里只负责取数据和排版。

    python scripts/_probe_eval.py                 # 逐维列出可达取值与表大小
    python scripts/_probe_eval.py --dim OutDType  # 一维的完整判定表
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import (  # noqa: E402
    Premises,
    domains_of,
    enumerate_cells,
)


def _domains() -> tuple[dict, dict]:
    """What each input may be, and the integers the code's names stand for."""
    path = CACHE / "fag_bundle.pkl"
    if not path.is_file():
        print("（没有 fag_bundle.pkl, 代表值只按阈值切, 可能取到非法输入）\n")
        return {}, {}
    with path.open("rb") as fh:
        return domains_of(pickle.load(fh)["var_model"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dim", help="只看这一维")
    ap.add_argument("--cap", type=int, default=2_000_000, help="单维格子上限")
    ap.add_argument("--no-premises", action="store_true", help="忽略输入合法性前提")
    ap.add_argument("--show-premises", action="store_true", help="列出每条前提")
    args = ap.parse_args()

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    fields = doc["fields"]
    raw_premises = (doc.get("host_derivation") or {}).get("premises") or []
    domains, constants = _domains()
    premises = None if args.no_premises else Premises(raw_premises)
    if premises is not None:
        print(
            f"输入合法性前提 {len(premises.trees)} 条可用, "
            f"{len(premises.dropped)} 条读不了"
        )
        if args.show_premises:
            for p in raw_premises:
                mark = "用" if p.get("usable") else f"弃({p.get('why')})"
                print(f"  [{mark}] {p['function']}:{p['line']}  {p['text'][:110]}")
        print()

    print(
        f"{'维度':<16} {'分级':<18} {'变量':>4} {'格子':>14}"
        f" {'算不出':>8} {'非法':>8}  可达取值"
    )
    print("-" * 110)
    for f in fields:
        if args.dim and f["name"] != args.dim:
            continue
        out = enumerate_cells(
            f.get("value_expr"),
            cap=args.cap,
            domains=domains,
            constants=constants,
            premises=premises,
        )
        if out["skipped"]:
            print(
                f"  {f['name']:<14} {f['exactness']:<18} {out['vars']:>4}"
                f" {out['cells']:>14,}  —— 超上限, 需分层连接"
            )
            continue
        vals = sorted(out["values"], key=str)
        print(
            f"  {f['name']:<14} {f['exactness']:<18} {out['vars']:>4}"
            f" {out['cells']:>14,} {out['unknown']:>8} {out['refused']:>8}  {vals}"
        )
        if args.dim:
            print(f"\n{args.dim} 的一组见证输入:")
            for value, env in sorted(out["values"].items(), key=lambda kv: str(kv[0])):
                shown = {k: v for k, v in env.items() if v not in (0, 1, False)}
                print(f"  = {value!r:8} 当 {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
