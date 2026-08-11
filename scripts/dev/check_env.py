#!/usr/bin/env python3
"""Report the Python and native-tool prerequisites visible to this checkout."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "engines" / "understand-operator" / "src"),
    str(ROOT / "engines" / "common"),
    str(ROOT / "pilot"),
]


def check_import(name: str) -> None:
    try:
        module = __import__(name)
        print(f"OK import {name}: {getattr(module, '__file__', module)}")
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"FAIL import {name}: {exc}")


def main() -> int:
    print(f"repo={ROOT}")
    print(f"python={sys.version.split()[0]} executable={sys.executable}")
    for name in ("yaml", "jsonschema", "z3", "uo_init", "ascendc_pilot", "testcase_agent"):
        check_import(name)
    try:
        import clang.cindex as cindex

        print(f"OK import clang.cindex: {getattr(cindex, '__file__', '<builtin>')}")
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"FAIL import clang.cindex: {exc}")
    for name in ("clang", "cmake", "c++", "wsl"):
        print(f"tool {name}={shutil.which(name) or 'MISSING'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
