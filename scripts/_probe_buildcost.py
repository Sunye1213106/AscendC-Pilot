# -*- coding: utf-8 -*-
"""求解上下文的固定成本拆开看: 改写(Python) 和 编译(Z3) 各占多少。

每个用求解器的脚本都要先付这笔钱, 一次一两分钟。分清是哪一半决定怎么省:
改写的产物是纯 JSON, 可以落盘复用; Z3 表达式不能序列化, 只能靠少问来摊薄。

    python scripts/_probe_buildcost.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    import _probe_reach as probe

    from uo_init import key_reachability as kr

    t0 = time.time()
    doc, var_model, schema, _binding = probe.load()
    print(f"load cache            {time.time() - t0:>7.1f}s")

    # Mirror `from_derivation` phase by phase, timing each, so the split between
    # the Python rewrite and the Z3 compile is visible.
    fields = list(doc.fields)
    symbols = kr._Symbols(kr._named_constants(var_model))

    t1 = time.time()
    domains = kr._Domains()
    trees = []
    for fld in fields:
        tree = getattr(fld, "value_expr", None)
        if tree is None:
            continue
        rename = kr._Isolator(fld.name, var_model, {})
        domains.read(tree, rename)
        trees.append((fld.name, fld, tree, rename))
    domains.resolve(symbols)
    print(f"read domains          {time.time() - t1:>7.1f}s   ({len(trees)} trees)")

    t2 = time.time()
    variables = [{"id": kr.TRUE_VAR, "type": "bool"}]
    constraints = [
        {"id": "const_true", "expr": {"op": "eq", "var": kr.TRUE_VAR, "value": True}}
    ]
    per_dim: list[tuple[str, float, int]] = []
    for name, fld, tree, rename in trees:
        t = time.time()
        rewrite = kr._Rewrite(symbols, rename, domains)
        try:
            adapted = rewrite.run(tree)
        except kr._Unadaptable as exc:
            per_dim.append((name + " (omitted)", time.time() - t, 0))
            continue
        found = sorted(kr._collect_vars(adapted))
        for var_id in found:
            if var_id == kr.TRUE_VAR:
                continue
            variables.append(
                kr._declare(var_id, rename.origin_of(var_id), rewrite.nulls)
            )
        variables.append(
            {
                "id": kr.DIM_PREFIX + name,
                "type": "bool" if kr._is_bool_expr(adapted) else "int",
                "derived": True,
                "definition": adapted,
            }
        )
        per_dim.append((name, time.time() - t, len(found)))
    rewrite_total = time.time() - t2
    print(f"rewrite (python)      {rewrite_total:>7.1f}s")
    for name, seconds, nvars in sorted(per_dim, key=lambda r: -r[1])[:6]:
        print(f"    {name:<20}{seconds:>7.1f}s  {nvars:>4} vars")

    variables = kr._dedupe(variables)
    ir = {"variables": variables, "constraints": constraints}

    t3 = time.time()
    import json

    blob = json.dumps(ir)
    print(f"ir is json-serialisable  {len(blob) / 1e6:>5.1f} MB in "
          f"{time.time() - t3:.1f}s")

    t4 = time.time()
    from acp_common.z3_backend import SolveConfig, Z3Backend

    Z3Backend(
        ir,
        SolveConfig(
            timeout_ms=5000,
            rlimit=kr.DEFAULT_RLIMIT,
            hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
        ),
    )
    compile_total = time.time() - t4
    print(f"z3 compile + assert   {compile_total:>7.1f}s")

    print(
        f"\nfixed cost {rewrite_total + compile_total:.0f}s = "
        f"rewrite {rewrite_total:.0f}s (cacheable, pure json) + "
        f"z3 {compile_total:.0f}s (not serialisable)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
