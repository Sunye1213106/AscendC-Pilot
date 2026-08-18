#!/usr/bin/env python3
"""Report CANN, ops-transformer and replay environment resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.paths import (
    _cann_candidates,
    _looks_like_cann,
    cann_layout_issues,
    cann_root,
    explain,
    ops_root,
    repo_root,
)


def main() -> int:
    print(f"repo={ROOT}")
    print(f"default extract dest={repo_root() / '_cann' / 'pkg'}")
    print("environment:")
    for name in (
        "UO_CANN_ROOT",
        "ASCEND_CANN_PACKAGE_PATH",
        "CANN_ROOT",
        "UO_OPS_ROOT",
        "OPS_TRANSFORMER_ROOT",
        "OPS_ROOT",
        "CANN_SET_ENV",
        "ASCEND_HOME_PATH",
        "UO_REPLAY_HOST",
        "UO_REPLAY_DISTRO",
    ):
        print(f"  {name}={os.environ.get(name)!r}")
    root = cann_root()
    print(f"cann_root() => {root}")
    print(f"ops_root()  => {ops_root()}")
    print("CANN candidates:")
    for candidate in _cann_candidates():
        print(f"  {candidate} exists={candidate.is_dir()} looks_like_cann={_looks_like_cann(candidate)}")
    issues = cann_layout_issues(root)
    if root is not None and not issues:
        print("cann_layout=ok")
        try:
            sys.path.insert(0, str(ROOT / "pilot"))
            from ascendc_pilot.paths import write_opencode_cann_root

            write_opencode_cann_root(root)
        except Exception:  # noqa: BLE001
            pass
    else:
        print("cann_layout_issues:")
        for item in issues:
            print(f"  {item}")
    print("resolution:")
    print(explain())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
