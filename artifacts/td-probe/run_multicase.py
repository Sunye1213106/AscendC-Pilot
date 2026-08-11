# -*- coding: utf-8 -*-
"""How many cases one TilingKey needs before its branch outcomes are covered.

Same key, different inputs: the key fixes the compile-time shape of the kernel,
but the tiling data it is handed still varies with layout, batch, sequence and
sparse mode, and that is what steers the runtime branches. This walks a grid of
such inputs, keeps the ones that still land on the target key, and reports the
outcome set growing case by case.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_pilot import (ENUMS, HERE as PH, PARAM_TO_DIM, decode,  # noqa: E402
                       load_derived, load_pinned, owner_of_leaf, replay)
from branch_eval import Env, evaluate  # noqa: E402
from replay import inputs as I  # noqa: E402

TARGET_TRAIT = sys.argv[1] if len(sys.argv) > 1 else "bn2gs1s2_plain"


def variants(base) -> dict[str, object]:
    """A grid over the inputs that change tiling data without changing the key.

    Layout is the interesting one: it is absent from the TilingKey entirely, yet
    the `layout` field it sets is read all over the kernel.
    """
    out: dict[str, object] = {}
    grid = [
        ("layout", ["BSND", "BSH", "SBH", "BNSD"]),
        ("b", [1, 2, 8, 32, 48]),
        ("s1", [64, 128, 256, 1024, 2048, 4096]),
        ("s2", [64, 128, 256, 1024, 2048, 4096]),
        ("n2", [1, 2, 5, 8]),
        ("g", [1, 2, 4]),
        ("sparse_mode", [0, 1, 2, 3, 4]),
        ("pre_tokens", [0, 128, 1024, 65536]),
        ("next_tokens", [0, 128, 1024, 65536]),
    ]
    for name, values in grid:
        for v in values:
            c = replace(base, **{name: v}, tag=f"{name}={v}")
            out[f"{name}_{v}"] = c.normalised()
    # A few combinations, since single-knob moves leave the core split alone.
    combos = [
        dict(b=32, s1=2048, s2=2048, n2=8, g=1),
        dict(b=1, s1=64, s2=64, n2=1, g=1),
        dict(b=48, s1=128, s2=128, n2=1, g=1),
        dict(b=2, s1=4096, s2=4096, n2=2, g=2, sparse_mode=2, pre_tokens=128,
             next_tokens=0),
        dict(b=8, s1=1024, s2=2048, n2=4, g=1, sparse_mode=3, pre_tokens=1024,
             next_tokens=0),
        dict(layout="BNSD", b=16, s1=512, s2=512, n2=2, g=2),
        dict(layout="SBH", b=4, s1=256, s2=1024, n2=8, g=1, sparse_mode=4,
             pre_tokens=256, next_tokens=256),
    ]
    for i, kw in enumerate(combos):
        out[f"combo{i}"] = replace(base, **kw, tag=f"combo{i}").normalised()
    return out


def state_of(b, env, layout, owner, absent, present_leaves):
    """(state, observed outcomes, outcomes excluded for this key)."""
    gone = sorted({owner.get(f, "") for f in b["fields"]} & absent)
    unknown_fields = [f for f in b["fields"] if f not in present_leaves]
    if gone or (b["fields"] and len(unknown_fields) == len(b["fields"])):
        return "unreachable", (), ()
    oc = evaluate(b["condition"], env)
    if oc.both_ways:
        return "both", (True, False), ()
    if oc.value is None:
        return "undecided", (), ()
    # Decided without reading tiling data: the condition folded on the key, so
    # the opposite outcome cannot occur under it at all.
    excluded = (not oc.value,) if oc.key_determined else ()
    return ("true" if oc.value else "false"), (oc.value,), excluded


def run_one(trait: str, picked: dict, layouts: dict, branches: list,
            by_size: dict, owner: dict, *, quiet: bool = False) -> dict:
    row = picked[trait]
    target = row["tiling_key"]
    made = I.construct_case(row["dims"])
    if not made:
        return {"trait": trait, "status": "no case constructed"}
    cases = variants(made[0])
    results = replay(cases)
    on_key = {cid: r for cid, r in results.items()
              if r.get("ok") and r.get("key") == target and r.get("td")}

    live: set[tuple] = set()
    covered: set[tuple] = set()
    excluded: set[tuple] = set()
    undecided_sites: set[tuple] = set()
    order = []
    dims = {k: int(v) for k, v in row["dims"].items()
            if str(v).lstrip("-").isdigit()}
    idt = str(row["dims"].get("InputDType"))
    for cid, r in on_key.items():
        if len(r["td"]) not in by_size:
            continue
        variant, layout = by_size[len(r["td"])]
        absent = set(layout.get("absent_members") or [])
        present = {f["path"].rsplit(".", 1)[-1]
                   for f in layout["fields"] if f["code"]}
        enums = dict(ENUMS)
        enums.update({
            "__is_same_T1_float": idt == "1", "__is_same_T_float": idt == "1",
            "__is_same_T1_half": idt == "3", "__is_same_T1_bfloat16_t": idt == "2",
            "__is_same_INPUT_TYPE_float": idt == "1",
        })
        env = Env(fields=decode(r["td"], layout), dims=dims,
                  param_to_dim=PARAM_TO_DIM, enums=enums,
                  block_num=int(r.get("block_num") or 0),
                  derived=load_derived(),
                  pinned=load_pinned(row["dims"]))
        gained = 0
        for b in branches:
            site = (b["file"], b["line"])
            state, outs, excl = state_of(b, env, layout, owner, absent, present)
            if state == "unreachable":
                continue
            live.add(site)
            if state == "undecided":
                undecided_sites.add(site)
                continue
            for o in excl:
                excluded.add((site, o))
            for o in outs:
                if (site, o) not in covered:
                    covered.add((site, o))
                    gained += 1
        if gained:
            order.append((cid, gained, len(covered)))

    goal = {(s, o) for s in live for o in (True, False)}
    # An outcome cannot be both observed and excluded; observation wins, and a
    # clash would mean the key-determined judgement was wrong.
    excluded -= covered
    open_set = goal - covered - excluded
    return {
        "trait": trait, "key": target, "candidates": len(cases),
        "on_key": len(on_key), "live": len(live), "goal": len(goal),
        "covered": len(covered), "excluded": len(excluded),
        "open": len(open_set), "gap": len(open_set),
        "undecided_sites": len(undecided_sites),
        "cases_that_added": [c for c, _, _ in order],
        "growth": order,
        "excluded_list": sorted((f"{f}:{ln}", str(o)) for (f, ln), o in excluded),
        "open_list": sorted((f"{f}:{ln}", str(o)) for (f, ln), o in open_set),
    }


def main_batch(traits: list[str]) -> None:
    picked = json.loads((PH / "picked_keys.json").read_text(encoding="utf-8"))
    layouts = json.loads((PH / "layout.json").read_text(encoding="utf-8"))
    branches = json.loads((PH / "steerable_branches.json").read_text(encoding="utf-8"))
    by_size = {lay["size"]: (n, lay) for n, lay in layouts.items()}
    owner = owner_of_leaf(layouts)

    rows = []
    for t in traits:
        if t not in picked:
            continue
        print(f"-- {t} ...", flush=True)
        rows.append(run_one(t, picked, layouts, branches, by_size, owner))

    print(f"\n{'trait':20s} {'onkey':>6s} {'live':>5s} {'goal':>5s} "
          f"{'cov':>5s} {'open':>5s} {'cases':>6s} {'undec':>6s}")
    for r in rows:
        if r.get("status"):
            print(f"{r['trait']:20s} {r['status']}")
            continue
        print(f"{r['trait']:20s} {r['on_key']:6d} {r['live']:5d} {r['goal']:5d} "
              f"{r['covered']:5d} {r['open']:5d} "
              f"{len(r['cases_that_added']):6d} {r['undecided_sites']:6d}")
    out = PH / "multicase_all.json"
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")


def main() -> None:
    picked = json.loads((PH / "picked_keys.json").read_text(encoding="utf-8"))
    layouts = json.loads((PH / "layout.json").read_text(encoding="utf-8"))
    branches = json.loads((PH / "steerable_branches.json").read_text(encoding="utf-8"))
    by_size = {lay["size"]: (n, lay) for n, lay in layouts.items()}
    owner = owner_of_leaf(layouts)

    row = picked[TARGET_TRAIT]
    target = row["tiling_key"]
    base = I.construct_case(row["dims"])[0]
    print(f"target trait={TARGET_TRAIT} key={target}")
    print(f"dims={row['dims']}\n")

    cases = variants(base)
    print(f"generated {len(cases)} candidate inputs")
    results = replay(cases)

    on_key = {cid: r for cid, r in results.items()
              if r.get("ok") and r.get("key") == target and r.get("td")}
    print(f"landed on the target key: {len(on_key)}/{len(cases)}\n")

    # Which branches are live for this key at all: taken from any observation,
    # since reachability is a property of the key, not of the case.
    live: set[tuple] = set()
    covered: set[tuple] = set()
    excluded: set[tuple] = set()
    undecided_sites: set[tuple] = set()
    per_case = []

    for cid, r in on_key.items():
        variant, layout = by_size[len(r["td"])]
        absent = set(layout.get("absent_members") or [])
        present = {f["path"].rsplit(".", 1)[-1] for f in layout["fields"] if f["code"]}
        fields = decode(r["td"], layout)
        dims = {k: int(v) for k, v in row["dims"].items()
                if str(v).lstrip("-").isdigit()}
        idt = str(row["dims"].get("InputDType"))
        enums = dict(ENUMS)
        enums.update({
            "__is_same_T1_float": idt == "1", "__is_same_T_float": idt == "1",
            "__is_same_T1_half": idt == "3", "__is_same_T1_bfloat16_t": idt == "2",
            "__is_same_INPUT_TYPE_float": idt == "1",
        })
        env = Env(fields=fields, dims=dims, param_to_dim=PARAM_TO_DIM,
                  enums=enums, block_num=int(r.get("block_num") or 0),
                  derived=load_derived(),
                  pinned=load_pinned(row["dims"]))
        gained = 0
        for b in branches:
            site = (b["file"], b["line"])
            state, outs, excl = state_of(b, env, layout, owner, absent, present)
            if state == "unreachable":
                continue
            live.add(site)
            if state == "undecided":
                undecided_sites.add(site)
                continue
            for o in excl:
                excluded.add((site, o))
            for o in outs:
                if (site, o) not in covered:
                    covered.add((site, o))
                    gained += 1
        per_case.append((cid, gained, len(covered)))

    goal = {(s, o) for s in live for o in (True, False)}
    excluded -= covered
    missing = sorted(goal - covered - excluded)
    print(f"live branches for this key: {len(live)}")
    print(f"outcome targets (live x 2): {len(goal)}")
    print(f"observed  (R):              {len(covered)}")
    print(f"excluded  (E):              {len(excluded)}")
    print(f"gap       (D-R-E):          {len(missing)}")
    print(f"sites never decided:        {len(undecided_sites)}")

    if excluded:
        print("\n== excluded: condition folds on the key, other way impossible ==")
        for (f, ln), o in sorted(excluded):
            cond = next((b["condition"] for b in branches
                         if b["file"] == f and b["line"] == ln), "")
            print(f"  {f}:{ln} cannot be {o}   {cond[:80]}")

    print("\n== coverage growth, case by case (only cases that added) ==")
    for cid, gained, total in per_case:
        if gained:
            print(f"  +{gained:3d} -> {total:3d}   {cid}")

    print("\n== still-open outcomes ==")
    for (f, ln), o in missing:
        cond = next((b["condition"] for b in branches
                     if b["file"] == f and b["line"] == ln), "")
        tag = "undecided" if (f, ln) in undecided_sites else "not observed"
        print(f"  {f}:{ln} want={str(o):5s} [{tag}]  {cond[:88]}")

    out = PH / f"multicase_{TARGET_TRAIT}.json"
    out.write_text(json.dumps({
        "trait": TARGET_TRAIT, "key": target,
        "candidates": len(cases), "on_key": len(on_key),
        "live": len(live), "goal": len(goal), "covered": len(covered),
        "open": len(missing), "undecided_sites": len(undecided_sites),
        "minimal_cases": [c for c, g, _ in per_case if g],
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    if TARGET_TRAIT == "--all":
        picked_all = json.loads((PH / "picked_keys.json").read_text(encoding="utf-8"))
        main_batch(list(picked_all))
    else:
        main()
