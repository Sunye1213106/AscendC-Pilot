#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed Workflow Spec model checker CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pilot"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args(argv)
    del args  # repo reserved for future path-based overlays

    from ascendc_pilot.workflows.model_checker import check_all_models

    errors = check_all_models()
    if errors:
        print(f"workflow-model: {len(errors)} issue(s)")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("workflow-model: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
