# -*- coding: utf-8 -*-
"""Close bn2gs1s2_plain to gap=0 (FAG fixture driver).

New work should use ``testcase_agent.closure.branch_outcome`` /
``field_pins`` under plan level L3 — this script is a regression harness over
artifacts/td-probe fixtures, not a Pilot skill.

Construct the three open Trues, lemma the rest.

The open set from the last multicase is:
  block_vec.h:263        dropoutIsDivisibleBy8 == 0   want True
  entry_regbase.h:238    sinkOptional                 want True
  kernel_base.h:457      sparseType == BAND           want True

sink is an input the grid never tried. The other two never moved under this
key's dims across 45 observations, so they are lemma candidates once sink is
settled and a last construct pass has failed to move them.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from branch_eval import Env, evaluate  # noqa: E402
from run_pilot import (ENUMS, PARAM_TO_DIM, decode, load_derived,  # noqa: E402
                       load_pinned, owner_of_leaf, replay)
from run_multicase import state_of, variants  # noqa: E402
from replay import inputs as I  # noqa: E402

TRAIT = "bn2gs1s2_plain"
OPEN = [
    ("flash_attention_score_grad_block_vec.h", 263, True,
     "dropoutIsDivisibleBy8 == 0"),
    ("flash_attention_score_grad_entry_regbase.h", 238, True, "sinkOptional"),
    ("flash_attention_score_grad_kernel_base.h", 457, True,
     "sparseType == BAND"),
]


def targeted(base) -> dict:
    """Cases aimed at the three open outcomes, still under this key's dims."""
    out = {}
    # Grid first: a crashing sink case used to take the whole batch with it.
    out.update(variants(base))
    # sparseType BAND probes (IsAttenMask=0 → host forces DENSE; kept so the
    # lemma can still be refuted if the host ever changes).
    for sm, pre, nxt in ((4, 128, 128), (4, 256, 256), (3, 128, 0),
                         (2, 128, 0), (1, 65536, 0), (0, 128, 128)):
        out[f"sparse_{sm}_{pre}_{nxt}"] = replace(
            base, sparse_mode=sm, pre_tokens=pre, next_tokens=nxt,
            tag=f"sm={sm}").normalised()
    # dropoutIsDivisibleBy8==0 under IsDrop=0: keep_prob stays 1.
    for s in (65, 66, 70, 72, 96, 100, 127):
        out[f"s_odd_{s}"] = replace(base, s1=s, s2=s, tag=f"s={s}").normalised()
    # sinkOptional: ProcessSinkInfo only accepts rank-1 shape [n1].
    out["sink_n1"] = replace(base, sink="n1", tag="sink=n1").normalised()
    out["sink_b32"] = replace(base, sink="n1", b=32, s1=1024, s2=1024,
                              tag="sink+b32").normalised()
    return out


def main() -> None:
    picked = json.loads((HERE / "picked_keys.json").read_text(encoding="utf-8"))
    layouts = json.loads((HERE / "layout.json").read_text(encoding="utf-8"))
    branches = json.loads((HERE / "steerable_branches.json").read_text(encoding="utf-8"))
    by_size = {lay["size"]: (n, lay) for n, lay in layouts.items()}
    owner = owner_of_leaf(layouts)
    row = picked[TRAIT]
    target = row["tiling_key"]
    base = I.construct_case(row["dims"])[0]
    cases = targeted(base)
    print(f"key={target}  candidates={len(cases)}")
    results = replay(cases)
    on_key = {cid: r for cid, r in results.items()
              if r.get("ok") and r.get("key") == target and r.get("td")}
    print(f"on key: {len(on_key)}/{len(cases)}")

    # Field movement under this key.
    from collections import Counter
    want_fields = ["dropoutIsDivisibleBy8", "sinkOptional", "sparseType"]
    seen = {f: Counter() for f in want_fields}
    for r in on_key.values():
        if len(r["td"]) not in by_size:
            continue
        fields = decode(r["td"], by_size[len(r["td"])][1])
        for f in want_fields:
            if f in fields:
                seen[f][str(fields[f])] += 1
    print("\n== field values on this key ==")
    for f, c in seen.items():
        print(f"  {f}: {dict(c)}")

    live, covered, excluded = set(), set(), set()
    dims = {k: int(v) for k, v in row["dims"].items()
            if str(v).lstrip("-").isdigit()}
    idt = str(row["dims"].get("InputDType"))
    enums = dict(ENUMS)
    enums.update({
        "__is_same_T1_float": idt == "1", "__is_same_T_float": idt == "1",
        "__is_same_T1_half": idt == "3", "__is_same_T1_bfloat16_t": idt == "2",
        "__is_same_INPUT_TYPE_float": idt == "1",
    })
    pinned = load_pinned(row["dims"])
    derived = load_derived()
    growth = []
    for cid, r in on_key.items():
        if len(r["td"]) not in by_size:
            continue
        _, layout = by_size[len(r["td"])]
        absent = set(layout.get("absent_members") or [])
        present = {f["path"].rsplit(".", 1)[-1]
                   for f in layout["fields"] if f["code"]}
        env = Env(fields=decode(r["td"], layout), dims=dims,
                  param_to_dim=PARAM_TO_DIM, enums=enums,
                  block_num=int(r.get("block_num") or 0),
                  derived=derived, pinned=pinned)
        gained = 0
        for b in branches:
            site = (b["file"], b["line"])
            state, outs, excl = state_of(b, env, layout, owner, absent, present)
            if state == "unreachable":
                continue
            live.add(site)
            if state == "undecided":
                continue
            for o in excl:
                excluded.add((site, o))
            for o in outs:
                if (site, o) not in covered:
                    covered.add((site, o))
                    gained += 1
        if gained:
            growth.append((cid, gained, len(covered)))

    goal = {(s, o) for s in live for o in (True, False)}
    excluded -= covered
    open_set = sorted(goal - covered - excluded)
    print(f"\nlive={len(live)} goal={len(goal)} R={len(covered)} "
          f"E={len(excluded)} gap={len(open_set)}")
    print("\n== cases that added coverage ==")
    for cid, g, t in growth:
        print(f"  +{g:3d} -> {t:3d}  {cid}")
    print("\n== open ==")
    for (f, ln), o in open_set:
        cond = next((b["condition"] for b in branches
                     if b["file"] == f and b["line"] == ln), "")
        print(f"  {f}:{ln} want={o}  {cond[:90]}")

    # Propose lemmas for fields that never left their default under this key.
    print("\n== lemma proposals (fields stuck under this key's dims) ==")
    for f, c in seen.items():
        if len(c) == 1:
            only = next(iter(c))
            print(f"  pin {f} = {only}  when dims match this key "
                  f"(observed {c[only]} times, never otherwise)")

    out = {
        "trait": TRAIT, "key": target,
        "on_key": len(on_key), "live": len(live), "goal": len(goal),
        "covered": len(covered), "excluded": len(excluded),
        "gap": len(open_set),
        "open_list": [(f"{f}:{ln}", str(o)) for (f, ln), o in open_set],
        "field_values": {f: dict(c) for f, c in seen.items()},
        "growth": growth,
    }
    path = HERE / f"close_{TRAIT}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwrote {path}")
    if out["gap"] == 0:
        print("\n*** GAP = 0 for this key ***")


if __name__ == "__main__":
    main()
