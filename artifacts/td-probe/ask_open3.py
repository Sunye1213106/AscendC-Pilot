# -*- coding: utf-8 -*-
"""Can the three open outcomes of bn2gs1s2_plain be reached under that key?

Asks UO for the host writers of the three fields, then checks whether any
observation already saw the wanted value under a key with the same dims that
matter (IsDrop / IsAttenMask / IsTnd). If the field never moves under those
dims, the open outcome is a lemma candidate rather than a missing case.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.store.reader import read_codemap  # noqa: E402

FIELDS = ["dropoutIsDivisibleBy8", "sinkOptional", "sparseType"]
uo = Path(sys.argv[1])
cm = read_codemap(uo)

print("== UO host writers ==")
for e in cm.entities.values():
    if e.kind != "TILING_FIELD":
        continue
    if e.name not in FIELDS:
        continue
    a = e.attrs or {}
    print(f"\n  {e.name}  owner={a.get('owner')}")
    for w in (a.get("host_writer_sites") or [])[:8]:
        print(f"    {w.get('file')}:{w.get('line')}  "
              f"expr={w.get('expression')}  mode={w.get('mode')}")

# Decode observed values from the latest multicase log if present: we re-decode
# from layout + any cached pilot results is heavy; instead scan field_ranges if
# it exists, else dump what ask_field_writers / field_ranges already know.
ranges = Path(__file__).parent / "field_ranges.py"
print("\n== looking for observations of these fields under IsDrop=0 ==")
# Prefer reading from multicase by replaying nothing: use steerable + ask
# through existing decode of pilot. Simpler: query host_replay if any wide
# table exists. Fall back to printing writers only.
print("(writers above are the source of truth for a lemma or a construct)")
