# -*- coding: utf-8 -*-
"""Does vouching for variable identities change what the solver can prove?

Compiles the same few dimensions twice, once with the binding table's
identities and once without, and asks the same questions of both. The
dimensions here read the same tensor axes, so if isolation is costing
conflicts this is where it shows: `query` cannot have one D for one
dimension and another for the next.

    python scripts/_probe_identity_share.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

#: The dimensions behind the value pairs no witness has ever carried together.
DIMS = ["IsDNoEqual", "DTemplateNum", "IsTnd", "IsRope", "IsBn2MultiBlk"]

#: Exactly those pairs, worst first, with the count of unknown keys each
#: blocks. A pair the solver calls unreachable retires that many keys; one it
#: calls reachable is a target the search has to construct.
QUESTIONS = [
    {"IsBn2MultiBlk": 1, "IsDNoEqual": 1},      # 192 keys
    {"IsTnd": 1, "IsBn2MultiBlk": 1},           # 192
    {"DTemplateNum": 192, "IsBn2MultiBlk": 1},  # 128
    {"DTemplateNum": 128, "IsBn2MultiBlk": 1},  # 64
    {"IsDNoEqual": 0, "IsRope": 1},             # 64
    {"IsBn2MultiBlk": 1, "IsRope": 1},          # 64
    {"DTemplateNum": 256, "IsBn2MultiBlk": 1},  # 64
]


def main() -> int:
    import _probe_derived_rules as drv
    import _probe_reach as probe
    from uo_init import key_reachability as kr
    from uo_init.key_reachability import KeyReachability

    doc, var_model, _schema, _binding = probe.load()
    identities = drv._identities()
    print(f"binding table vouches for {len(identities)} variables\n")

    results = {}
    for label, ids in (("isolated (before)", None), ("vouched (after)", identities)):
        t0 = time.time()
        reach = KeyReachability.from_derivation(
            doc, var_model, timeout_ms=5000, rlimit=kr.DEFAULT_RLIMIT,
            hard_timeout_ms=kr.DEFAULT_HARD_TIMEOUT_MS,
            only=DIMS, identities=ids,
        )
        s = reach.summary()
        print(f"--- {label}: built {time.time() - t0:.1f}s  "
              f"compiled {s['dimensions_compiled']}  exact {s['dimensions_exact']}  "
              f"shared {len(s['identity_shared'])}  "
              f"isolated {len(s['identity_isolated'])}  "
              f"groups {[len(g) for g in s['groups']]}")
        answers = []
        for q in QUESTIONS:
            v = reach.joint_verdict(q)
            answers.append(v.status)
            print(f"      {v.status:<12} {q}")
        results[label] = answers

    before, after = results["isolated (before)"], results["vouched (after)"]
    changed = [(q, b, a) for q, b, a in zip(QUESTIONS, before, after) if b != a]
    print(f"\n{len(changed)} of {len(QUESTIONS)} answers changed")
    for q, b, a in changed:
        print(f"  {b} -> {a}   {q}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
