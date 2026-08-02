# -*- coding: utf-8 -*-
"""Why `fBaseParams.d` stays a surface leaf inside a classifier comparison."""
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.derive_key_fields import (  # noqa: E402
    KeyFieldDeriver,
    _pretty_dag,
    _walk_dag,
    _DRIVABLE_ROOTS,
    dotted_path,
    parse_expr,
)
from uo_init.expr_ir import Call, Ref, Unknown  # noqa: E402

bundle = pickle.load((ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb"))
kd = KeyFieldDeriver(
    host_ir=bundle["host_ir"],
    resolver=bundle["resolver"],
    var_model=bundle["var_model"],
)

FN = "GetDTemplateType"
e = parse_expr("fBaseParams.d")

print("classifier_operand:", kd._classifier_operand(e, FN))
print("writes_are_self_routing:", kd._writes_are_self_routing("fBaseParams.d", FN))

deep = kd._expand(e, FN, 0)
print("nodes used:", kd._nodes)
print("reduces_to_inputs:", kd._reduces_to_inputs(deep, FN))

names = set()
for node in _walk_dag(deep):
    if isinstance(node, Unknown):
        print("  UNKNOWN node:", node)
    if isinstance(node, Ref):
        names.add((node.symbol, node.scope or FN))
    elif isinstance(node, Call):
        p = dotted_path(node)
        if p is not None:
            names.add((p, FN))

print(f"\n{len(names)} names in the expansion:")
for name, scope in sorted(names):
    res = kd._scope(scope).resolve(name)
    ok = res.closed and res.roots and all(r in _DRIVABLE_ROOTS for r in res.roots)
    print(f"  {'ok ' if ok else 'NO '} {name:<40} closed={res.closed} roots={res.roots}")
print("\ndrivable roots:", _DRIVABLE_ROOTS)
