"""Validate / apply extract_plan via input-rooted Relation Graph pipeline.

Legacy decision_report path is removed. Canonical path:
  candidates → observations → relations → materialize → slim IR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.semantic_pipeline import apply_semantic_extract_plan


def apply_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    plan: dict[str, Any] | None = None,
    plan_path: Path | None = None,
    staging_path: Path | None = None,
    check_only: bool = False,
    worklist_path: Path | None = None,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply extract_plan using Relation Graph materializer.

    ``plan`` / ``worklist_path`` are ignored (kept for call-site compatibility).
    When ``staging_path`` is under an action dir, relation parts are merged.
    """
    _ = plan, plan_path, worklist_path
    action_dir = None
    if staging_path is not None:
        stage = Path(staging_path)
        if stage.is_dir() and stage.name == "staging":
            action_dir = stage.parent
        elif stage.name == "staging" or stage.parent.name == "staging":
            action_dir = stage.parent if stage.name == "staging" else stage.parent.parent
        elif (stage.parent / "inputs").is_dir():
            action_dir = stage.parent
        elif (stage.parent.parent / "inputs").is_dir():
            action_dir = stage.parent.parent
        elif stage.is_dir() and (stage / "semantic_relations.yaml").is_file():
            action_dir = stage.parent if stage.name == "staging" else stage

    return apply_semantic_extract_plan(
        Path(repo_root),
        op_name,
        action_dir=action_dir,
        check_only=check_only,
        identity=dict(identity or {}),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Apply extract_plan from relation graph")
    p.add_argument("--repo-root", type=Path, required=True)
    p.add_argument("--op-name", required=True)
    p.add_argument("--staging", type=Path, default=None)
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args(argv)
    result = apply_extract_plan(
        args.repo_root,
        safe_op_name(args.op_name),
        staging_path=args.staging,
        check_only=args.check_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
