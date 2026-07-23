"""Validate / apply LLM extract_plan against candidates (closure check)."""
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
from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates


def apply_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    plan: dict[str, Any] | None = None,
    plan_path: Path | None = None,
    check_only: bool = False,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    cand_path = uo_root / "ir" / "extract_plan_candidates.yaml"
    if not cand_path.is_file():
        return {
            "ok": False,
            "rejected_count": 1,
            "rejected": [{"reason": "extract_plan_candidates.yaml missing"}],
        }
    candidates = read_yaml(cand_path)
    if plan is None:
        src = plan_path or (uo_root / "ir" / "extract_plan.yaml")
        if not Path(src).is_file():
            return {
                "ok": False,
                "rejected_count": 1,
                "rejected": [{"reason": f"extract_plan missing: {src}"}],
            }
        plan = read_yaml(Path(src))
    if not isinstance(plan, dict):
        return {"ok": False, "rejected_count": 1, "rejected": [{"reason": "plan not a mapping"}]}

    # Normalize optional empty lists
    plan.setdefault("version", 1)
    plan.setdefault("confirmed_by", "llm")
    plan.setdefault("writers", [])
    plan.setdefault("receivers", [])
    plan.setdefault("aliases", [])
    plan.setdefault("non_sink_roots", [])
    plan.setdefault("extra_host_entries", [])
    plan.setdefault("derived_roots", [])

    errors = validate_extract_plan_against_candidates(plan, candidates if isinstance(candidates, dict) else {})
    if errors:
        return {
            "ok": False,
            "rejected_count": len(errors),
            "rejected": [{"reason": e} for e in errors],
        }

    result = {
        "ok": True,
        "rejected_count": 0,
        "rejected": [],
        "writers": len(plan.get("writers") or []),
        "receivers": len(plan.get("receivers") or []),
        "aliases": len(plan.get("aliases") or []),
    }
    if not check_only:
        write_yaml(uo_root / "ir" / "extract_plan.yaml", plan)
        result["written"] = str(uo_root / "ir" / "extract_plan.yaml")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate/apply extract_plan.yaml against candidates")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--plan", default="", help="Path to plan YAML (default: ir/extract_plan.yaml)")
    parser.add_argument("--check", action="store_true", help="Validate only, do not write")
    parser.add_argument("--write", action="store_true", help="Write validated plan to ir/extract_plan.yaml")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    plan_path = Path(args.plan) if args.plan else None
    check_only = bool(args.check) and not bool(args.write)
    if not args.check and not args.write:
        check_only = True
    result = apply_extract_plan(
        repo_root,
        op_name,
        plan_path=plan_path,
        check_only=check_only,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
