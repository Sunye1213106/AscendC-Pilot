# -*- coding: utf-8 -*-
"""Replay stand-in for `pilot_cli inspect yaml`.

Runs the same parser/restorer the finalizer uses, so "inspect ok" means the same thing
inside the replay as it does in a real run.

Usage: python evals/tg_init/inspect_part.py <parts/xxx.yaml>
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "engines" / "testcase-generation"))

from testcase_agent import bind_parts as BP  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: inspect_part.py <parts/xxx.yaml>")
        return 2
    target = Path(argv[0]).resolve()
    if not target.is_file():
        print(f"not ok: {target} does not exist")
        return 1
    try:
        doc = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"not ok: YAML parse failed: {exc}")
        return 1
    if not isinstance(doc, dict):
        print("not ok: top level is not a mapping")
        return 1

    axis = "harness" if target.stem.startswith("harness") else "bind"
    owned_path = target.parent / ".engine" / f"{axis}.owned.yaml"
    owned = {}
    if owned_path.is_file():
        loaded = yaml.safe_load(owned_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            owned = loaded

    if axis == "harness":
        _, errors = BP.restore_harness(doc, owned)
    else:
        _, errors = BP.restore_bind(doc, owned)

    if errors:
        print(f"not ok: {len(errors)} error(s)")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
