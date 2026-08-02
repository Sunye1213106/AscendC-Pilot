# -*- coding: utf-8 -*-
"""逐维问求解器: 这一维单独拿出来, 每个声明取值到底能不能达到。

`_probe_unreach.py` 显示大多数 unsat 的 core 里只有**一个**维度的定义, 加上它
自己的取值断言。那不是「多维互斥」, 而是「这一维的表达式产不出这个值」—— 一个
维度的某个取值一旦这样被判死, 所有含它的 key 全都跟着死, 一条能杀几百上千个。

所以先把每一维单独钉住、其余维度全放开, 逐个取值问一遍。得到的是一张最小的
证据表: 哪些取值确实产不出来。真产不出来是好事(声明域比实现宽是常态), 但如果
一个明显该有的取值被判死, 那就是推导收缩了可行域, 是 bug。

    python scripts/_probe_dimvals.py
    python scripts/_probe_dimvals.py DeterType IsNzOut   # 只看这几维
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dims", nargs="*", help="只问这几维")
    ap.add_argument("--timeout", type=int, default=5000)
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
    compiled = dict(getattr(reach, "_dims", {}))

    print(f"{'维度':<16} {'声明取值':<26} 判决")
    print("-" * 74)
    dead: list[tuple[str, str]] = []
    for dim in schema.dims:
        name = dim.name
        if args.dims and name not in args.dims:
            continue
        spec = compiled.get(name)
        if spec is None:
            print(f"{name:<16} {'—':<26} 未编译, 不参与求解")
            continue
        marks = []
        for raw in dim.value_domain:
            value = kr._target_value(raw)
            if value is None:
                marks.append(f"{raw}=?")
                continue
            if spec["bool"] and value not in (0, 1, True, False):
                marks.append(f"{raw}:域外")
                dead.append((name, str(raw)))
                continue
            hit = reach._solve_group(((name, value),))
            status = str((hit or {}).get("status") or "?")
            marks.append(f"{raw}:{ {'sat': '可达', 'unsat': '不可达'}.get(status, status) }")
            if status == "unsat":
                dead.append((name, str(raw)))
        exact = "exact" if spec.get("exact") else "过近似"
        print(f"{name:<16} {' '.join(marks):<26} [{exact}]")

    print(f"\n单维即判死的取值 {len(dead)} 个:")
    for name, value in dead:
        print(f"  {name}={value}")
    print(
        "\n每一条都要回到源码核对: 该取值真的产不出来, 还是推导把它排除掉了。\n"
        "一个维度的取值被判死, 含它的 key 会成百上千地跟着死。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
