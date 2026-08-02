# -*- coding: utf-8 -*-
"""Why a name still looks circular, and what was known at the moment it did.

`_expand_name` calls a name circular when it meets itself part-way through its
own expansion. `_earlier_defs` is the second opinion: if the writes that close
the loop all sit below the point the name is being read, they had not run yet
and there is no cycle. When a dimension still reports `CYCLIC_DEFINITION`, one
of three things happened, and they want different fixes:

  no call at all     the read point never reached `_earlier_defs`, so the
                     recursion is on a path that does not set one
  read is None       expansion got there without a write to attribute it to
  kept == all        position does not separate them -- either a real cycle,
                     or the writes are in another function where line order
                     says nothing

Runs the derivation in-process, since the patch below would not survive the
fork that `isolate` does.

    python scripts/_probe_cycle.py                # every dimension that cycles
    python scripts/_probe_cycle.py DeterType      # just this one, in full
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CYCLING = ["SplitAxis", "DeterType", "IsBn2MultiBlk", "IsNzOut", "IsTndSwizzle"]


def short(path: str) -> str:
    return Path(path).name if path else "?"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("fields", nargs="*", help="dimensions to derive")
    ap.add_argument("--all-calls", action="store_true", help="every call, not a summary")
    args = ap.parse_args()
    only = args.fields or CYCLING

    import _probe_derive as probe  # the bundle loader, unchanged
    from uo_init.derive_key_fields import KeyFieldDeriver
    from uo_init.host_derivation import derive_host_fields

    seen: list[dict[str, Any]] = []
    original = KeyFieldDeriver._visible_defs

    def spy(self, sites):
        out = original(self, sites)
        read = self._read_at
        if len(out) != len(sites) or read is None:
            seen.append(
                {
                    "read": (short(read.file), read.line, read.function) if read else None,
                    "sites": [
                        (short(s.file), s.line, s.function, s.rhs[:48]) for s in sites
                    ],
                    "kept": None if len(out) == len(sites) else [
                        (short(s.file), s.line) for s in out
                    ],
                }
            )
        return out

    # Where a cycle is actually declared: the innermost expansion whose return
    # left a new name in `cycles`.
    declared: list[dict[str, Any]] = []
    expand = KeyFieldDeriver._expand_name

    def spy_expand(self, name, original_expr, fn, depth):
        before = set(self.cycles)
        out = expand(self, name, original_expr, fn, depth)
        fresh = self.cycles - before
        if fresh:
            read = self._read_at
            canon = self._canonical_name(name, fn)
            declared.append(
                {
                    "named": sorted(fresh),
                    "expanding": name,
                    "canon": canon,
                    "in": fn,
                    "read": (short(read.file), read.line, read.function) if read else None,
                    "sites": [
                        (short(s.file), s.line, s.function, s.rhs[:44])
                        for s in self._sites_for(name, canon, fn)
                    ],
                }
            )
        return out

    KeyFieldDeriver._visible_defs = spy
    KeyFieldDeriver._expand_name = spy_expand
    try:
        bundle = probe.load_bundle()
        doc = derive_host_fields(bundle, timeout=600, isolate=False, only=only)
    finally:
        KeyFieldDeriver._visible_defs = original
        KeyFieldDeriver._expand_name = expand

    # Innermost first: the last frame to add a name is the one that decided.
    print("\nwhere each cycle was declared (innermost first):")
    reported: set[str] = set()
    for rec in declared:
        fresh = [n for n in rec["named"] if n not in reported]
        if not fresh:
            continue
        reported.update(fresh)
        print(f"  {', '.join(fresh)}")
        print(f"      while expanding {rec['expanding']!r} (canon {rec['canon']!r}) in {rec['in']}")
        print(f"      read at {rec['read']}")
        for site in rec["sites"]:
            print(f"      write {site[0]}:{site[1]} in {site[2]}   {site[3]}")

    for f in doc.fields:
        print(f"{f.name:16} {f.exactness:18} {f.note or '-'}")

    print(f"\nlookups where position mattered or was unknown: {len(seen)}")
    if not seen:
        print("  none -- every lookup saw every write, and had a read point")
        return 0

    verdicts = Counter(
        "no read point, so nothing dropped" if c["read"] is None
        else "dropped a write not yet run"
        for c in seen
    )
    for name, count in verdicts.most_common():
        print(f"  {count:5}  {name}")

    print("\nlookups with no read point to judge by:")
    shown = 0
    for call in seen:
        if call["kept"] is not None:
            continue
        if not args.all_calls and shown >= 12:
            print("  ... (--all-calls for the rest)")
            break
        shown += 1
        print(f"  read at {call['read']}")
        for site in call["sites"]:
            print(f"      write {site[0]}:{site[1]} in {site[2]}   {site[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
