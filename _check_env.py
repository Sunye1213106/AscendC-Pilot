#!/usr/bin/env python3
import sys
from pathlib import Path

repo = Path("/mnt/d/TEST/AscendC-Pilot")
sys.path[:0] = [
    str(repo / "engines/understand-operator/src"),
    str(repo / "engines/common"),
    str(repo / "pilot"),
]

for name in ("yaml", "z3", "uo_init", "ascendc_pilot"):
    try:
        mod = __import__(name)
        print(f"OK {name}: {getattr(mod, '__file__', mod)}")
    except Exception as exc:
        print(f"FAIL {name}: {exc}")

try:
    import clang.cindex as ci
    print("OK clang.cindex")
except Exception as exc:
    print(f"FAIL clang: {exc}")
