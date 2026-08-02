# -*- coding: utf-8 -*-
"""Can a dimension still notice that an optional tensor was not passed?

The absent-tensor branch is selected by a rank of zero, so this evaluates the
derived trees at exactly that point and at its neighbours, and reports whether
the input-legality premises accept the assignment.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import Premises, Unknown, ValueTree, domains_of, samples  # noqa: E402

CASES = [
    ("IsPse", "VAR_OPT_PSE_SHIFT", "VAR_SHAPE_PSE_SHIFT"),
    ("IsAttenMask", "VAR_OPT_ATTEN_MASK", "VAR_SHAPE_ATTEN_MASK"),
    ("IsRope", "VAR_OPT_QUERY_ROPE_IDX", "VAR_SHAPE_QUERY_ROPE_IDX"),
]


def main() -> None:
    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    fields = {f["name"]: f for f in doc["fields"]}
    raw = (doc.get("host_derivation") or {}).get("premises") or []
    premises = Premises(raw)
    usable = [p for p in raw if p.get("usable") and p.get("expr")]
    with (CACHE / "fag_bundle.pkl").open("rb") as fh:
        model = pickle.load(fh)["var_model"]
    domains, _constants = domains_of(model)

    for name, opt, shape in CASES:
        f = fields[name]
        tree = ValueTree(f["value_expr"])
        base = {v: True if v.startswith("VAR_OPT_") else 4 for v in tree.variables()}
        print(f"\n=== {name}  (declared domain {f['domain']}) ===")
        spec = model.get(shape)
        print(f"  {shape}: {'lo=' + str(spec.domain.lo) if spec else 'not in bundle model'}"
              f"  sampled with rank threshold 0 -> "
              f"{samples({0}, spec.domain if spec else None)}")
        for label, env in (
            ("tensor present, rank 4", {**base, opt: True, shape: 4}),
            ("tensor passed but empty (rank 0)", {**base, opt: True, shape: 0}),
            ("tensor not passed", {**base, opt: False, shape: 0}),
            ("not passed, rank left legal", {**base, opt: False, shape: 4}),
        ):
            try:
                value = tree.value(env)
            except Unknown as exc:
                value = f"<unknown: {exc}>"
            blockers = []
            for p, tree_p in zip(usable, premises.trees):
                try:
                    if not tree_p.value(env):
                        blockers.append(f"{p['function']}:{p['line']} {p['text'][:70]}")
                except Unknown:
                    continue
            print(f"  {label:<34} -> {value}   rejected_by={blockers or '-'}")


if __name__ == "__main__":
    main()
