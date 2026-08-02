# -*- coding: utf-8 -*-
"""Where do the 4 blocking free vars actually appear inside value_expr?

For each of the 4 variables this probe walks every field's expression DAG and
prints the *enclosing operator* of each occurrence, plus the sibling operand.
That says whether the variable is used as a bare boolean, compared with a
constant, or fed into arithmetic -- which decides what a summary would have to
produce.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"

TARGETS = {
    "VAR_LOOPELEM_INVALIDS1ARRAY_344A1EAA60F0",
    "VAR_LOOPELEM_INVALIDS1ARRAY_A62F1BECD415",
    "VAR_LOOPELEM_PARSEINFO_7555587D750D",
    "VAR_SCHED_COREIDX",
}


def _short(node, depth=0):
    if depth > 2:
        return "..."
    if isinstance(node, dict):
        if "lit" in node and len(node) == 1:
            return repr(node["lit"])
        if "var" in node:
            return node["var"]
        op = node.get("op")
        kids = [k for k in node if k not in ("op", "root")]
        return f"({op} " + " ".join(f"{k}={_short(node[k], depth+1)}" for k in kids) + ")"
    if isinstance(node, list):
        return "[" + ",".join(_short(n, depth + 1) for n in node) + "]"
    return repr(node)


def walk(node, parent, key, out, seen):
    if isinstance(node, dict):
        v = node.get("var")
        if v in TARGETS:
            ctx = _short(parent) if parent is not None else "<root>"
            out[v].append((key, ctx))
            return
        for k, sub in node.items():
            if k in ("op", "root", "var"):
                continue
            walk(sub, node, k, out, seen)
    elif isinstance(node, list):
        for sub in node:
            walk(sub, parent, key, out, seen)


def main() -> int:
    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    for f in doc["fields"]:
        if not (set(f.get("free_vars") or []) & TARGETS):
            continue
        out = defaultdict(list)
        walk(f.get("value_expr"), None, "", out, set())
        print(f"=== {f['name']}  ({f['exactness']}) ===")
        for v in sorted(out):
            ctxs = Counter(c for _, c in out[v])
            print(f"  {v}: {len(out[v])} occurrences, {len(ctxs)} distinct contexts")
            for ctx, n in ctxs.most_common(6):
                print(f"      x{n:<5} {ctx[:150]}")
        print()

    # what does the model say about these vars
    print("=== var model entries ===")
    for f in doc["fields"]:
        for name, spec in (f.get("variables") or {}).items():
            if name in TARGETS:
                print(f"  {name}: {json.dumps(spec, ensure_ascii=False)[:400]}")
                TARGETS.discard(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
