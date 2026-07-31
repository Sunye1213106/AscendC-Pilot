# -*- coding: utf-8 -*-
"""Why LAST_PUSH_DOMINATES_BACK did or did not fire for one container."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

CONTAINER = sys.argv[1] if len(sys.argv) > 1 else "slicePrefix1"

with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
    ir = pickle.load(fh)["host_ir"]

print(f"== call sites whose receiver mentions {CONTAINER}")
for s in ir.call_sites:
    if CONTAINER in (s.receiver or "") or any(CONTAINER in (a or "") for a in s.args):
        print(
            f"  {s.caller}: {s.receiver}.{s.callee}(...) "
            f"@{Path(s.file).name}:{s.line}:{getattr(s, 'column', 0)} args={s.args}"
        )

print(f"\n== write events on {CONTAINER}")
for w in list(ir.writes) + list(ir.local_writes):
    if CONTAINER in w.path:
        print(
            f"  {w.function}: {w.path} kind={w.kind} rhs={w.rhs!r} "
            f"@{Path(w.file).name}:{w.line}:{getattr(w, 'column', 0)} "
            f"conds={[(c.kind, c.pretty()) for c in w.path_conditions]}"
        )

fns = sorted(
    {w.function for w in list(ir.writes) + list(ir.local_writes) if CONTAINER in w.path}
    | {s.caller for s in ir.call_sites if CONTAINER in (s.receiver or "")}
)
print(f"\n== per-function verdict")
for fn in fns:
    read = ir.sole_member_read(fn, CONTAINER, "back")
    evs = ir.container_events(CONTAINER, fn)
    print(f"  {fn}: sole_back_read={read and (read.line, read.column)} events={len(evs)}")
    for w in evs:
        print(f"      {w.kind:8s} @{w.line}:{getattr(w, 'column', 0)} rhs={w.rhs!r}")
