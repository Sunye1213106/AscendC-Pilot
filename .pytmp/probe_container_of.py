# -*- coding: utf-8 -*-
import pickle
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"d:\PR-review\AscendC-Pilot")
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

from uo_init.derive_key_fields import _container_of, _walk_dag
from uo_init.expr_ir import Select, Ref, Call
from uo_init.source_resolver import dotted_path

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"
TARGETS = (
    "invalidS1Array",
    "parseInfo",
    "actualSeqQlen",
    "actualSeqKvlen",
    "qValue",
    "kvValue",
    "inputLayout",
)


def arr_label(node):
    co = _container_of(node.array)
    dp = dotted_path(node.array)
    sym = ""
    cur = node.array
    parts = []
    while cur is not None:
        if isinstance(cur, Ref):
            parts.append(cur.symbol)
            break
        if isinstance(cur, Call) and cur.func.startswith("field:"):
            parts.append(cur.func[len("field:") :])
            cur = cur.args[0] if cur.args else None
        elif isinstance(cur, Select):
            cur = cur.array
        else:
            break
    sym = ".".join(reversed(parts)) if parts else "?"
    return sym, co, dp


def main():
    bundle = pickle.loads(BUNDLE.read_bytes())
    ir = bundle["host_ir"]
    resolver = bundle["resolver"]
    scope_for = getattr(resolver, "scope_for", None) or (lambda s: resolver)

    rows = []
    for fn_name, fn in (ir.functions or {}).items():
        body = getattr(fn, "body", None) or getattr(fn, "sites", None) or []
        items = body if isinstance(body, list) else []
        for site in items:
            expr = getattr(site, "expr", None) or getattr(site, "rhs", None) or getattr(site, "value", None)
            if expr is None:
                continue
            for node in _walk_dag(expr):
                if not isinstance(node, Select):
                    continue
                sym, co, dp = arr_label(node)
                if not any(t in sym or t in (co or "") or t in (dp or "") for t in TARGETS):
                    continue
                scope = getattr(node, "scope", fn_name)
                res = scope_for(scope).resolve(co or sym)
                atoms = [a for a in (res.atoms if res else []) if a.root and a.root != "CONSTANT"]
                rows.append(
                    {
                        "fn": fn_name,
                        "sym": sym,
                        "co": co,
                        "dp": dp,
                        "scope": scope,
                        "has_root": bool(atoms),
                        "root": atoms[0].root if atoms else None,
                        "idx_type": type(node.index).__name__,
                    }
                )

    print(f"Select hits: {len(rows)}")
    grp = Counter((r["sym"], r["co"], r["dp"], r["has_root"], r["root"]) for r in rows)
    for key, n in grp.most_common(30):
        sym, co, dp, has_root, root = key
        print(f"  x{n} sym={sym!r} co={co!r} dp={dp!r} root={root if has_root else 'NONE'}")


if __name__ == "__main__":
    main()
