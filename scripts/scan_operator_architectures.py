#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Developer/agent helper: fast operator layout + arch* scan.

Prefer the installed CLI::

    acp scan-architectures --project <operator-dir>

This script is a thin wrapper around the same intake API for local debugging
without PATH setup.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan op_host/op_kernel layout and arch* options for a operator package"
    )
    parser.add_argument(
        "--project",
        type=Path,
        required=True,
        help="Operator package root (must contain op_host and/or op_kernel)",
    )
    args = parser.parse_args(argv)

    repo_pilot = Path(__file__).resolve().parents[1] / "pilot"
    if str(repo_pilot) not in sys.path:
        sys.path.insert(0, str(repo_pilot))

    from ascendc_pilot.intake import scan_operator_directory

    result = scan_operator_directory(args.project)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
