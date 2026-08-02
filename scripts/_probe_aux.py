# -*- coding: utf-8 -*-
"""What the cycle cuts turned into, one dimension at a time.

    python scripts/_probe_aux.py IsBn2MultiBlk

Prints the auxiliaries a dimension's derivation introduced, whether each one
came back closed, and what it closed onto. The question it answers is whether
the `blockOuter` cycle was ever a real one.
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.host_derivation import derive_host_fields  # noqa: E402


def main() -> int:
    names = sys.argv[1:] or ["IsBn2MultiBlk"]
    with (ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb") as fh:
        bundle = pickle.load(fh)
    started = time.time()
    doc = derive_host_fields(bundle, isolate=False, only=names)
    print(f"{round(time.time() - started, 1)}s\n")
    for f in doc.fields:
        print(f"{f.name}  {f.exactness}  {f.input_closure}")
        print(f"  roots     {f.root_vars}")
        print(f"  free      {f.free_vars}")
        print(f"  aux       {sorted(f.aux_targets)}")
        print(f"  note      {f.note[:300]}")
    for var_id, aux in sorted(doc.auxiliaries.items()):
        print(f"\nAUX {var_id}  <- {aux.host_expr!r}")
        print(f"  {aux.status} / {aux.exactness} / {aux.input_closure}  "
              f"{aux.expanded_chars} chars  {aux.seconds}s")
        print(f"  roots     {aux.root_vars}")
        print(f"  free      {aux.free_vars}")
        print(f"  aux       {sorted(aux.aux_targets)}")
        print(f"  note      {aux.note[:300]}")
        print(f"  unresolved {aux.unresolved[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
