# -*- coding: utf-8 -*-
"""变量身份有没有解析开: 一个名字底下是不是压着好几个不同的量。

handoff G.13 的结论是: `d`、`s1`、`s2` 在 IR 里全叫 `VAR_SHAPE_GETSTORAGESHAPE`,
于是一个 Z3 变量同时背着 `>64`、`<128`、`>=2048`、`<=512`, 必然 UNSAT —— 这不是
过近似, 是收缩, 会把真实可达的 key 判死。

这个脚本只看名字, 不跑求解器, 所以是秒级的:

    python scripts/_probe_identity_check.py
    python scripts/_probe_identity_check.py IsNzOut     # 只看这几维的读点
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

DERIVE = ROOT / ".probe_cache" / "fag_derive.json"

#: Names shaped like an accessor rather than a thing: whatever the expression
#: reads through them, they cannot tell two reads apart.
COLLAPSED = re.compile(r"_GET[A-Z]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dims", nargs="*", help="只看这几维")
    args = ap.parse_args()

    doc = json.loads(DERIVE.read_text(encoding="utf-8"))
    print(f"derived at {doc.get('timestamp')}\n")

    everywhere: Counter[str] = Counter()
    offenders: dict[str, list[str]] = {}
    for f in doc["fields"]:
        name = f["name"]
        if args.dims and name not in args.dims:
            continue
        merged = sorted(v for v in (f.get("variables") or []) if COLLAPSED.search(v))
        everywhere.update(merged)
        if merged:
            offenders[name] = merged

    print(f"{'dimension':<18}{'vars':>6}  accessor-shaped names")
    print("-" * 78)
    for f in doc["fields"]:
        name = f["name"]
        if args.dims and name not in args.dims:
            continue
        variables = f.get("variables") or []
        bad = offenders.get(name) or []
        mark = ", ".join(bad[:3]) + (f" +{len(bad) - 3}" if len(bad) > 3 else "")
        print(f"{name:<18}{len(variables):>6}  {mark or '-'}")

    print("-" * 78)
    if not everywhere:
        print("no accessor-shaped variable names: identities are resolved")
        return 0
    print(f"{sum(everywhere.values())} occurrences over {len(everywhere)} names:")
    for var, count in everywhere.most_common():
        print(f"  {var:<44}{count:>4} dimension(s)")
    print(
        "\n每一个这样的名字都可能把不同的量绑成同一个 Z3 变量, 造成假 UNSAT。"
        "\n参见 docs/debug/handoff.md G.13。"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
