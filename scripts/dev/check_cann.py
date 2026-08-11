#!/usr/bin/env python3
from pathlib import Path
import os
import sys

sys.path.insert(0, "/mnt/d/TEST/AscendC-Pilot/engines/understand-operator/src")
from uo_init.paths import cann_root, ops_root, explain, _looks_like_cann, _cann_candidates

print("env:")
for k in ("UO_CANN_ROOT", "ASCEND_CANN_PACKAGE_PATH", "CANN_ROOT", "ASCEND_HOME"):
    print(f"  {k}={os.environ.get(k)!r}")

print("cann_root() =>", cann_root())
print("ops_root()  =>", ops_root())
print("candidates:")
for c in _cann_candidates():
    print(f"  {c} exists={c.is_dir()} looks={_looks_like_cann(c)}")

for p in (
    Path("/usr/local/Ascend/cann"),
    Path("/mnt/d/TEST/_cann/pkg"),
    Path("/mnt/d/TEST/_cann/slim"),
):
    print(f"\n== {p} ==")
    print("  exists", p.is_dir(), "looks_like_cann", _looks_like_cann(p))
    if p.is_dir():
        kids = sorted(x.name for x in p.iterdir())[:30]
        print("  children:", kids)

print("\nexplain:\n", explain())
