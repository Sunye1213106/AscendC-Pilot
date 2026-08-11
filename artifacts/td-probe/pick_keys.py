# -*- coding: utf-8 -*-
"""Pick a spread of representative TilingKeys from the CodeMap's legal index.

Spread rather than random: the point of the pilot is to see how the branch count
per key varies, so the sample has to include the shapes that switch whole code
paths in or out -- empty tensor, the three SplitAxis routes, each DeterType, TND
with and without swizzle, rope, NZ out.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.store.reader import load_view_blob  # noqa: E402

uo = Path(sys.argv[1])
idx = load_view_blob(uo, "tiling/legal_key_index.jsonl")
rows = list(idx["rows"])
print(f"legal keys: {len(rows)}")

#: Each wanted trait is a predicate on the decoded dims. One key per trait, and
#: a key already picked for an earlier trait is not reused, so the sample stays
#: spread instead of collapsing onto whichever key satisfies everything.
WANT = [
    ("empty_tensor", lambda d: d["IsEmptyTensor"] == "1"),
    ("bn2gs1s2_plain", lambda d: d["SplitAxis"] == "0" and d["DeterType"] == "0"
     and d["IsTnd"] == "0" and d["IsDrop"] == "0" and d["IsPse"] == "0"),
    ("bn2_multiblk", lambda d: d["SplitAxis"] == "1" and d["IsBn2MultiBlk"] == "1"),
    ("bn2s2", lambda d: d["SplitAxis"] == "5"),
    ("drop_pse_mask", lambda d: d["IsDrop"] == "1" and d["IsPse"] == "1"
     and d["IsAttenMask"] == "1"),
    ("deter_old", lambda d: d["DeterType"] == "1"),
    ("deter_new_dense", lambda d: d["DeterType"] == "2"),
    ("deter_band_nequal", lambda d: d["DeterType"] == "4" and d["IsNEqual"] == "1"),
    ("tnd_plain", lambda d: d["IsTnd"] == "1" and d["IsTndSwizzle"] == "0"
     and d["DeterType"] == "0"),
    ("tnd_swizzle", lambda d: d["IsTndSwizzle"] == "1"),
    ("rope", lambda d: d["IsRope"] == "1"),
    ("nz_out", lambda d: d["IsNzOut"] == "1"),
    ("fp32", lambda d: d["InputDType"] == "1"),
    ("bf16", lambda d: d["InputDType"] == "2"),
]

picked: dict[str, dict] = {}
used: set[int] = set()
for name, pred in WANT:
    for r in rows:
        if r["tiling_key"] in used:
            continue
        try:
            if pred(r["dims"]):
                picked[name] = r
                used.add(r["tiling_key"])
                break
        except KeyError:
            continue
    if name not in picked:
        print(f"  no legal key for trait {name}")

out = Path(__file__).parent / "picked_keys.json"
out.write_text(json.dumps(picked, indent=1), encoding="utf-8")
print(f"\npicked {len(picked)} keys -> {out}\n")
dims_of_interest = ["IsEmptyTensor", "SplitAxis", "InputDType", "IsTnd", "IsDrop",
                    "IsPse", "IsAttenMask", "DTemplateNum", "DeterType", "IsNEqual",
                    "IsBn2MultiBlk", "IsRope", "IsNzOut", "IsTndSwizzle"]
print(f"{'trait':20s} {'key':>20s}  " + " ".join(d[:7] for d in dims_of_interest))
for name, r in picked.items():
    d = r["dims"]
    print(f"{name:20s} {r['tiling_key']:>20d}  "
          + " ".join(f"{d.get(k,''):>7s}" for k in dims_of_interest))
