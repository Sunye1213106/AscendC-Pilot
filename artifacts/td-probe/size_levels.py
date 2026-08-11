# -*- coding: utf-8 -*-
"""Natural cut points for a coverage ladder, measured rather than chosen.

A level is only useful if its size falls out of a property of the operator --
one case per compiled template block, one per value pair, one per legal key --
because then the number moves with the operator instead of with a constant
somebody picked.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.harness import sample_instances  # noqa: E402
from uo_init.store.reader import load_view_blob  # noqa: E402
from uo_init.tpl_dsl import parse_file  # noqa: E402
from uo_init import paths  # noqa: E402

uo = Path(sys.argv[1])
space = load_view_blob(uo, "tiling/exhaustive_key_space.yaml")
index = load_view_blob(uo, "tiling/legal_key_index.jsonl")
rows = list(index["rows"])
blocks = list(space.get("template_blocks") or [])

print(f"legal keys (D)               : {space.get('legal_key_count')}")
print(f"ARGS_SEL template blocks     : {len(blocks)}")
print(f"sum of block product_count   : {sum(int(b.get('product_count') or 0) for b in blocks)}")

# --- what varies inside a block, and what is fixed across all of them ------
dim_values: dict[str, set] = {}
for r in rows:
    for k, v in r["dims"].items():
        dim_values.setdefault(k, set()).add(v)
print("\n== dimension value domains over legal keys ==")
for k, vs in dim_values.items():
    print(f"   {k:18s} {len(vs):2d}  {sorted(vs)}")

single = [k for k, vs in dim_values.items() if len(vs) == 1]
print(f"\ndimensions with one value only: {single}")

# --- pairwise over the real schema ----------------------------------------
op_dir = paths.op_dir(relative="attention/flash_attention_score_grad")
hdr = (Path(op_dir) / "op_kernel/arch35"
       / "flash_attention_score_grad_template_tiling_key.h")
schema = parse_file(hdr)
for strategy in ("pairwise", "per_value"):
    got = sample_instances(schema, strategy=strategy)
    print(f"sample_instances({strategy:9s}) -> {len(got)}")

# --- the branch equivalence class of a key -------------------------------
#: Measured in the pilot: the live branch set moves with these dimensions only.
CLASS_DIMS = ["IsEmptyTensor", "SplitAxis", "IsTnd", "IsTndSwizzle", "DeterType",
              "IsDrop", "InputDType"]
classes = Counter()
for r in rows:
    classes[tuple(r["dims"].get(d, "") for d in CLASS_DIMS)] += 1
print(f"\nbranch-equivalence classes over {CLASS_DIMS}")
print(f"   distinct classes: {len(classes)}")
print(f"   largest class   : {classes.most_common(1)[0][1]} keys")

for subset in (
    ["IsEmptyTensor", "SplitAxis", "DeterType", "IsTnd", "IsTndSwizzle"],
    ["IsEmptyTensor", "SplitAxis", "DeterType", "IsTnd", "IsTndSwizzle", "InputDType"],
    ["IsEmptyTensor", "SplitAxis", "DeterType", "IsTnd", "IsTndSwizzle",
     "InputDType", "IsDrop", "IsPse", "IsAttenMask"],
):
    c = {tuple(r["dims"].get(d, "") for d in subset) for r in rows}
    print(f"   {len(c):5d} classes over {subset}")

# --- how many keys the last full run actually reached --------------------
r_txt = ROOT / "artifacts" / "fa-pr13" / "host_replay_details.jsonl"
if r_txt.is_file():
    hit = 0
    total = 0
    for line in r_txt.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        rec = json.loads(line)
        if rec.get("verdict") == "HIT":
            hit += 1
    print(f"\nlast full run: {hit} of {total} keys reached by host replay")
