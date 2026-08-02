# -*- coding: utf-8 -*-
"""Which branch does each of the 4 variables actually pick?

Structural companion to the sampling probes. For every `if_then_else` whose
condition mentions one of the 4 variables, this reports whether the two arms
are the same tree (the variable is dead at that site whatever it holds) and,
when they differ, the literal values each arm can produce.

Everything is memoised on node identity: the expression is a DAG with heavy
sharing, and walking it as a tree does not terminate in useful time.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"

TARGETS = {
    "VAR_LOOPELEM_INVALIDS1ARRAY_344A1EAA60F0": "invalidS1Array[j] (A)",
    "VAR_LOOPELEM_INVALIDS1ARRAY_A62F1BECD415": "invalidS1Array[j] (B)",
    "VAR_LOOPELEM_PARSEINFO_7555587D750D": "parseInfo[s2Outer-1][LEN]",
    "VAR_SCHED_COREIDX": "coreIdx",
}
DIMS = ["SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle"]


class Dag:
    def __init__(self, blob):
        if isinstance(blob, dict) and blob.get("$dag"):
            self.defs = blob.get("defs") or {}
            self.root = blob.get("root")
        else:
            self.defs, self.root = {}, blob
        self._m: dict[int, frozenset] = {}
        self._h: dict[int, int] = {}
        self._l: dict[int, frozenset] = {}
        self._keep = []

    def deref(self, n):
        k = 0
        while isinstance(n, dict) and "$ref" in n:
            n = self.defs.get(n["$ref"])
            k += 1
            if k > 1000:
                return None
        return n

    def mentions(self, node) -> frozenset:
        node = self.deref(node)
        key = id(node)
        got = self._m.get(key)
        if got is not None:
            return got
        self._m[key] = frozenset()
        self._keep.append(node)
        out: set = set()
        if isinstance(node, list):
            for x in node:
                out |= self.mentions(x)
        elif isinstance(node, dict):
            v = node.get("var")
            if v in TARGETS:
                out.add(v)
            for k, sub in node.items():
                if k not in ("op", "var", "root"):
                    out |= self.mentions(sub)
        res = frozenset(out)
        self._m[key] = res
        return res

    def shape(self, node) -> int:
        """Structural hash: equal hashes mean the two arms are the same tree."""
        node = self.deref(node)
        key = id(node)
        got = self._h.get(key)
        if got is not None:
            return got
        self._h[key] = 0
        self._keep.append(node)
        if isinstance(node, list):
            h = hash(("L",) + tuple(self.shape(x) for x in node))
        elif isinstance(node, dict):
            h = hash(("D",) + tuple(
                (k, self.shape(v) if isinstance(v, (dict, list)) else hash(repr(v)))
                for k, v in sorted(node.items())))
        else:
            h = hash(("A", repr(node)))
        self._h[key] = h
        return h

    def leaves(self, node) -> frozenset:
        node = self.deref(node)
        key = id(node)
        got = self._l.get(key)
        if got is not None:
            return got
        self._l[key] = frozenset()
        self._keep.append(node)
        out: set = set()
        if isinstance(node, list):
            for x in node:
                out |= self.leaves(x)
        elif isinstance(node, dict):
            if "lit" in node and len(node) == 1:
                out.add(str(node["lit"]))
            elif node.get("op") == "if_then_else":
                out |= self.leaves(node.get("then"))
                out |= self.leaves(node.get("else"))
            elif "var" in node and node.get("op") is None:
                out.add("<" + node["var"] + ">")
            else:
                out.add("<" + str(node.get("op")) + ">")
        elif isinstance(node, (int, str, bool)):
            out.add(str(node))
        res = frozenset(out)
        self._l[key] = res
        return res


def main() -> int:
    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    sys.setrecursionlimit(100000)
    for f in doc["fields"]:
        if f["name"] not in DIMS:
            continue
        dag = Dag(f.get("value_expr"))
        sites = defaultdict(list)
        seen: set[int] = set()
        stack = [dag.root]
        while stack:
            node = dag.deref(stack.pop())
            if id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            if node.get("op") == "if_then_else":
                hit = dag.mentions(node.get("condition"))
                if hit:
                    same = dag.shape(node.get("then")) == dag.shape(node.get("else"))
                    sites[hit].append((same,
                                       sorted(dag.leaves(node.get("then")), key=str),
                                       sorted(dag.leaves(node.get("else")), key=str)))
            for k, sub in node.items():
                if k not in ("op", "var", "root"):
                    stack.append(sub)

        print(f"=== {f['name']} ===   ({len(seen)} distinct nodes)")
        if not sites:
            print("  no if_then_else branches on any of the 4")
        for key in sorted(sites, key=lambda s: sorted(s)):
            rows = sites[key]
            dead = sum(1 for s, _, _ in rows if s)
            names = ", ".join(TARGETS[v] for v in sorted(key))
            print(f"  branch on [{names}]: {len(rows)} site(s),"
                  f" {dead} with identical arms")
            shown = 0
            for same, a, b in rows:
                if same or shown >= 3:
                    continue
                shown += 1
                print(f"      then -> {a}")
                print(f"      else -> {b}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
