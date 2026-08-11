# -*- coding: utf-8 -*-
"""Try to refute every lemma against every observation on record.

A lemma claims a field is pinned under some keys. Any replayed case that matches
the `when` clause and shows a different value refutes it outright. Surviving a
sweep is not a proof, but a refuted rule is certainly wrong, and running this
before the rules are used keeps a bad exclusion from closing a gap that is real.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_pilot import (ENUMS, PARAM_TO_DIM, decode, load_derived,  # noqa: E402
                       owner_of_leaf, replay)
from replay import inputs as I  # noqa: E402
from run_multicase import variants  # noqa: E402


def matches(when: dict, dims: dict) -> bool:
    return all(str(dims.get(k)) == str(v) for k, v in (when or {}).items())


def same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


def main() -> None:
    rules = yaml.safe_load((HERE / "lemmas.yaml").read_text(encoding="utf-8"))["rules"]
    picked = json.loads((HERE / "picked_keys.json").read_text(encoding="utf-8"))
    layouts = json.loads((HERE / "layout.json").read_text(encoding="utf-8"))
    by_size = {lay["size"]: (n, lay) for n, lay in layouts.items()}

    print(f"rules: {len(rules)}")
    checked = Counter()
    refuted: dict[str, list] = {}

    # Every trait, and for each a spread of inputs: a rule is only tested where
    # its `when` holds, so the sweep has to cover keys that satisfy it.
    for trait, row in picked.items():
        made = I.construct_case(row["dims"])
        if not made:
            continue
        cases = variants(made[0])
        results = replay(cases)
        for cid, r in results.items():
            if not (r.get("ok") and r.get("td")):
                continue
            if len(r["td"]) not in by_size:
                continue
            _, layout = by_size[len(r["td"])]
            fields = decode(r["td"], layout)
            # The observed key, not the intended one: a rewritten case is still
            # a real observation, it is just about a different key.
            got_key = r.get("key")
            dims = None
            for other in picked.values():
                if other["tiling_key"] == got_key:
                    dims = other["dims"]
                    break
            if dims is None:
                dims = row["dims"] if got_key == row["tiling_key"] else None
            if dims is None:
                continue
            for rule in rules:
                fname = rule["field"]
                if fname not in fields or not matches(rule.get("when"), dims):
                    continue
                checked[rule["id"]] += 1
                if not same(fields[fname], rule["value"]):
                    refuted.setdefault(rule["id"], []).append(
                        {"case": cid, "trait": trait, "key": got_key,
                         "observed": fields[fname], "claimed": rule["value"]})

    print(f"\n{'rule':34s} {'tested':>7s}  verdict")
    ok = True
    for rule in rules:
        rid = rule["id"]
        n = checked.get(rid, 0)
        bad = refuted.get(rid) or []
        if bad:
            ok = False
            verdict = f"REFUTED by {len(bad)} (e.g. {bad[0]['observed']} != {bad[0]['claimed']})"
        elif n == 0:
            verdict = "NOT TESTED - no observation matched `when`"
        else:
            verdict = "survived"
        print(f"{rid:34s} {n:7d}  {verdict}")

    out = HERE / "lemma_check.json"
    out.write_text(json.dumps(
        {"tested": dict(checked), "refuted": refuted,
         "usable": [r["id"] for r in rules
                    if checked.get(r["id"], 0) > 0 and not refuted.get(r["id"])]},
        indent=1, default=str), encoding="utf-8")
    print(f"\nwrote {out}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
