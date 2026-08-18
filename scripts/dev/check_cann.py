#!/usr/bin/env python3
"""Report CANN, ops-transformer and replay environment resolution.

Exit 0 only when ``require_cann_ready()`` would let prepare proceed. This is
the same gate as ``python -m ascendc_pilot doctor`` and prepare_layout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "pilot"))

from uo_init.paths import (
    _cann_candidates,
    _looks_like_cann,
    cann_root,
    explain,
    opencode_cann_root_cache_path,
    ops_root,
    read_cached_cann_root,
    repo_root,
    require_cann_ready,
)


def main() -> int:
    print(f"repo={ROOT}")
    print(f"default extract dest={repo_root() / '_cann' / 'pkg'}")
    print(f"opencode cann cache={opencode_cann_root_cache_path()}")
    print("environment:")
    for name in (
        "UO_CANN_ROOT",
        "ASCEND_CANN_PACKAGE_PATH",
        "CANN_ROOT",
        "ASCEND_HOME_PATH",
        "UO_OPS_ROOT",
        "OPS_TRANSFORMER_ROOT",
        "OPS_ROOT",
        "CANN_SET_ENV",
        "UO_REPLAY_HOST",
        "UO_REPLAY_DISTRO",
    ):
        print(f"  {name}={os.environ.get(name)!r}")
    print(f"read_cached_cann_root() => {read_cached_cann_root()}")
    discovered = cann_root()
    print(f"cann_root() => {discovered}")
    print(f"ops_root()  => {ops_root()}")
    print("CANN candidates:")
    for candidate in _cann_candidates():
        print(
            f"  {candidate} exists={candidate.is_dir()} "
            f"looks_like_cann={_looks_like_cann(candidate)}"
        )
    root, issues = require_cann_ready()
    if not issues:
        print("cann_layout=ok")
        try:
            from ascendc_pilot.paths import write_opencode_cann_root

            write_opencode_cann_root(root)
        except Exception:  # noqa: BLE001
            pass
        print("resolution:")
        print(explain())
        return 0
    print("cann_layout_issues:")
    for item in issues:
        print(f"  {item}")
    print("resolution:")
    print(explain())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
