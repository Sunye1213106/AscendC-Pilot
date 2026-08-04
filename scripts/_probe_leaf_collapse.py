# -*- coding: utf-8 -*-
"""Which dimensions lost value-arms between expansion and normalisation.

`value_leaves` on a field is the union of two readings: the constants the
*expanded* expression could reach, and the constants the normalised SMT form
can reach. Storing only the union hides the interesting case -- when the second
set is strictly smaller, normalisation folded away arms the source can take,
and the field now claims fewer outcomes than the code has.

That is under-approximation, the one direction the derivation is not allowed to
move in, and it is invisible to every existing check: `free_vars` is empty
because the folded arms took their variables with them, and `domain_violations`
only looks for leaves *outside* the declared set, never for declared values the
expression can no longer produce.

DeterType is the case this was written for: five writes, five declared values,
and an SMT form that can only ever return 0 or 2.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

DERIVE = ROOT / ".probe_cache" / "fag_derive.json"


def _as_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def main() -> int:
    from uo_init.derive_key_fields import smt_value_leaves

    doc = json.load(DERIVE.open(encoding="utf-8"))["host_derivation"]
    rows = []
    for f in doc["fields"]:
        expr = f.get("value_expr")
        if expr is None:
            continue
        reachable = {
            n for n in (_as_int(v) for v in smt_value_leaves(expr)) if n is not None
        }
        recorded = {
            n for n in (_as_int(v) for v in f.get("value_leaves") or ()) if n is not None
        }
        domain = {
            n for n in (_as_int(v) for v in f.get("domain") or ()) if n is not None
        }
        lost_vs_expansion = recorded - reachable
        lost_vs_domain = domain - reachable if domain else set()
        rows.append((f["name"], f["exactness"], len(f.get("free_vars") or ()),
                     sorted(reachable), sorted(lost_vs_expansion),
                     sorted(lost_vs_domain)))

    print(f"{'dimension':<16}{'exactness':<20}{'free':>5}  "
          f"{'SMT can return':<22}{'lost vs expansion':<20}lost vs domain")
    collapsed, review = [], []
    for name, ex, free, reach, lost_e, lost_d in rows:
        flag = ""
        # Two signals of different strength, and conflating them makes the
        # check useless.
        #
        # Losing a value the *expansion* reached is the hard one: the same
        # derivation, one pass earlier, said the field could return it. Nothing
        # about the operator can explain that away -- normalisation dropped a
        # live arm. With no free variable left to stand for what was dropped,
        # the field is now claiming exact knowledge of a value set it shrank.
        #
        # Losing a value only against the *template* is weaker. It can equally
        # mean the value is genuinely dead (IsRegbase=0 does not exist on
        # arch35) or that another dimension short-circuits it (S1/S2TemplateNum
        # read 0 when IsEmptyTensor=1, which this field's own expression is
        # never asked about). Those need a witness or a human, not a failure.
        if free == 0 and lost_e:
            flag = "  <-- COLLAPSED"
            collapsed.append((name, lost_e))
        elif free == 0 and lost_d:
            flag = "  (review)"
            review.append((name, lost_d))
        print(f"{name:<16}{ex:<20}{free:>5}  "
              f"{str(reach):<22}{str(lost_e):<20}{str(lost_d)}{flag}")

    print()
    for name, lost in review:
        print(f"review {name}: template declares {lost} which the expression "
              f"cannot return -- dead value, or another dimension decides it")
    if collapsed:
        print()
        for name, lost in collapsed:
            print(f"LEAF_COLLAPSE {name}: normalisation dropped {lost}; graded "
                  f"exact with no free variable to stand for them")
        return 1
    print("no dimension lost value arms during normalisation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
