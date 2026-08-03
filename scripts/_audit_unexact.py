# -*- coding: utf-8 -*-
"""Audit what makes each overapprox field inexact, using only fag_derive.json."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from uo_init.derive_key_fields import (
    decode_expr_dag,
    has_constant_dead_arm,
    _smt_children,
    _is_expr_container,
)

ROOT = Path(__file__).resolve().parents[1]
DERIVE = ROOT / ".probe_cache" / "fag_derive.json"

OVERAPPROX_PREFIXES = (
    "VAR_UNDECIDED_",
    "VAR_SCHED_",
    "VAR_REACHED_",
    "VAR_INIT_",
    "VAR_LOOPELEM_",
)


def _lit_guard_shapes(expr):
    """Classify guard-position lit shapes without provenance."""
    expr = decode_expr_dag(expr) if isinstance(expr, dict) and "$dag" in expr else expr
    shapes = Counter()
    stack = [(expr, False)]
    seen = set()
    while stack:
        node, in_guard = stack.pop()
        if not _is_expr_container(node):
            continue
        key = (id(node), in_guard)
        if key in seen:
            continue
        seen.add(key)
        if isinstance(node, dict):
            op = node.get("op")
            if op == "lit" and in_guard:
                shapes[f"lit:{node.get('value')}"] += 1
            if op == "if_then_else":
                c = node.get("condition")
                if isinstance(c, dict) and c.get("op") == "lit":
                    shapes[f"ite_cond_lit:{c.get('value')}"] += 1
                if _is_expr_container(c):
                    stack.append((c, True))
                for arm in (node.get("then"), node.get("else")):
                    if _is_expr_container(arm):
                        stack.append((arm, False))
                continue
            if op in ("and", "or", "not"):
                for ch in _smt_children(node):
                    stack.append((ch, True))
                continue
        for ch in _smt_children(node):
            stack.append((ch, in_guard))
    return shapes


def main() -> None:
    doc = json.loads(DERIVE.read_text(encoding="utf-8"))
    fields = (doc.get("host_derivation") or doc)["fields"]
    print("=== overapprox / non-exact fields ===\n")
    for f in fields:
        ex = f.get("exactness")
        if ex in ("exact", "constant"):
            continue
        name = f["name"]
        free = f.get("free_vars") or []
        by_pref = Counter()
        for v in free:
            for p in OVERAPPROX_PREFIXES:
                if v.startswith(p):
                    by_pref[p] += 1
                    break
            else:
                by_pref["other"] += 1
        undec = f.get("undecided_guards") or []
        impl = f.get("implicit_defaults") or []
        unres = f.get("unresolved") or []
        ve = f.get("value_expr")
        dead = has_constant_dead_arm(ve) if isinstance(ve, dict) else False
        shapes = _lit_guard_shapes(ve) if isinstance(ve, dict) else Counter()
        print(f"## {name}  exactness={ex}  input_derivable={f.get('input_derivable')}")
        print(f"   leaves={f.get('value_leaves')}  free={len(free)}  vars={len(f.get('variables') or [])}")
        print(f"   free_by_prefix={dict(by_pref)}")
        print(f"   free_sample={free[:8]}")
        print(f"   undecided_guards={len(undec)}  implicit_defaults={len(impl)}  unresolved={len(unres)}")
        if undec[:2]:
            print(f"   undecided_sample={undec[:2]}")
        if impl[:2]:
            print(f"   implicit_sample={impl[:2]}")
        if unres[:2]:
            print(f"   unresolved_sample={unres[:2]}")
        print(f"   has_constant_dead_arm={dead}  lit_guard_shapes={dict(shapes)}")
        print(f"   note={f.get('note')!r}")
        print(f"   input_roots={f.get('input_roots')}")
        # variables that are input-like vs soft
        vs = f.get("variables") or []
        soft = [v for v in vs if v.startswith(OVERAPPROX_PREFIXES)]
        hard = [v for v in vs if not v.startswith(OVERAPPROX_PREFIXES)]
        print(f"   hard_vars={len(hard)} soft_in_variables={len(soft)}")
        print()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
    main()
