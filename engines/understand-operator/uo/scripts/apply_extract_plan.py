"""Validate / apply extract_plan via Relation Graph pipeline."""
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
from uo.scripts.semantic_pipeline import apply_semantic_extract_plan


def apply_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    action_dir: Path | None = None,
    check_only: bool = False,
    identity: dict[str, Any] | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Apply extract_plan：只接受 Relation Graph 链路参数。"""
    _ = existing_operator_root  # 保持导入稳定
    return apply_semantic_extract_plan(
        Path(repo_root),
        op_name,
        action_dir=Path(action_dir) if action_dir is not None else None,
        check_only=check_only,
        identity=dict(identity or {}),
        progress=progress,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Apply extract_plan from relation graph")
    p.add_argument("--repo-root", type=Path, required=True)
    p.add_argument("--op-name", required=True)
    p.add_argument("--action-dir", type=Path, default=None)
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args(argv)
    result = apply_extract_plan(
        args.repo_root,
        safe_op_name(args.op_name),
        action_dir=args.action_dir,
        check_only=args.check_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
