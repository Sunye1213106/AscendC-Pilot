from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .contract import TgContractError, tg_contract
from .init import TgInitError, tg_init
from .path_resolve import (
    infer_op_name,
    install_contract_into_project,
    resolve_operator_project_root,
    resolve_plan_paths,
)
from .planner import TgPlanError, tg_plan
from .solve import TgSolveError, tg_solve


def init_main(argv: list[str] | None = None) -> int:
    """Deprecated: tg-init is folded into tg-plan. Kept as thin wrapper for compatibility."""
    parser = argparse.ArgumentParser(description="DEPRECATED: use tg-plan (intake is included). Thin wrapper around legacy intake.")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--op-name", required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            {
                "status": "deprecated",
                "message": "tg-init is deprecated; use tg-contract then tg-plan. Running legacy intake only.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )
    try:
        result = tg_init(args.project_root, args.op_name)
    except TgInitError as exc:
        print(json.dumps({"status": "fail", "message": str(exc), "report": exc.report}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"status": result["run"]["status"], "snapshot_hash": result["snapshot"]["snapshot_hash"]}, ensure_ascii=False, indent=2))
    return 0


def contract_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build CSV consumer evidence + realization map from test script root (before tg-plan)"
    )
    parser.add_argument("project_root", type=Path, nargs="?", default=None, help="Operator package or KB path")
    parser.add_argument("--op-name", default="", help="Optional if uniquely inferable")
    parser.add_argument(
        "--csv-consumer-root",
        type=Path,
        default=None,
        help="Test script / CSV consumer project root (e.g. TEST/fag_debug_tools)",
    )
    parser.add_argument(
        "--test-script-root",
        type=Path,
        default=None,
        help="Alias of --csv-consumer-root",
    )
    parser.add_argument("--kb-root", type=Path, default=None, help="Optional KB path for resolving op package")
    parser.add_argument("--reuse-snapshot", action="store_true")
    parser.add_argument(
        "--lexicon-seed",
        type=Path,
        default=None,
        help="Optional binding_lexicon.yaml seed (merged before evidence key_derivations)",
    )
    args = parser.parse_args(argv)
    try:
        consumer = args.csv_consumer_root or args.test_script_root
        if consumer is None:
            raise ValueError("CSV_CONSUMER_ROOT_REQUIRED: pass --csv-consumer-root / --test-script-root")
        raw_project = args.project_root or args.kb_root
        if raw_project is None:
            raise ValueError("OPERATOR_ROOT_REQUIRED: pass project_root (算子仓) or --kb-root")
        project_root = resolve_operator_project_root(raw_project)
        kb_hint = args.kb_root
        if kb_hint is None and (
            raw_project.expanduser().resolve().name == ".understand-operator"
            or raw_project.expanduser().resolve().parent.name == ".understand-operator"
        ):
            kb_hint = raw_project
        op_name = infer_op_name(project_root, explicit=args.op_name or None, kb_hint=kb_hint)
        result = tg_contract(
            project_root,
            op_name,
            csv_consumer_root=consumer,
            reuse_snapshot=args.reuse_snapshot,
            lexicon_seed=args.lexicon_seed,
        )
    except ValueError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except TgContractError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "snapshot_hash": result["snapshot_hash"],
                "evidence_hash": result["evidence_hash"],
                "contract_hash": result["contract_hash"],
                "consumer_root": result["consumer_root"],
                "csv_variables": len((result.get("realization_map") or {}).get("csv_variables") or []),
                "mapped_branches": len((result.get("realization_map") or {}).get("branch_mappings") or []),
                "abstract_branches": len((result.get("realization_map") or {}).get("abstract_branches") or []),
                "next": "tg-plan <算子仓> --op-name <op> --contract-root <realization> 或再带 --test-script-root",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def plan_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build L0–L3 coverage plan. Requires 算子仓 + (测试工具 OR contract产物). "
            "测试工具 → 自动 tg-contract；contract产物 → 直接复用。"
        )
    )
    parser.add_argument(
        "project_root",
        type=Path,
        nargs="?",
        default=None,
        help="算子仓（含 .understand-operator/）。也可传 KB 路径。",
    )
    parser.add_argument("--op-name", default="", help="Optional if uniquely inferable from KB / .understand-operator/")
    parser.add_argument("--level", default="L1", help="Level or comma-separated levels, e.g. L0,L1,L2")
    parser.add_argument("--focus", default="")
    parser.add_argument("--topic", default="", help="Required for L3 (e.g. determinism)")
    parser.add_argument("--reuse-snapshot", action="store_true", help="Skip intake when snapshot hash still matches")
    parser.add_argument(
        "--csv-consumer-root",
        type=Path,
        default=None,
        help="测试工具 / CSV consumer root。传入后自动执行 contract。",
    )
    parser.add_argument(
        "--test-script-root",
        type=Path,
        default=None,
        help="--csv-consumer-root 别名（对话里的「测试工具/测试脚本」）。",
    )
    parser.add_argument(
        "--contract-root",
        type=Path,
        default=None,
        help="已有 contract 产物目录（realization/ 或含 realization_map.yaml 的目录）。与测试工具二选一。",
    )
    parser.add_argument(
        "--kb-root",
        type=Path,
        default=None,
        help="Optional .understand-operator or .understand-operator/<op>. Used to resolve project_root/op-name.",
    )
    parser.add_argument(
        "--lexicon-seed",
        type=Path,
        default=None,
        help="Optional binding_lexicon.yaml seed passed through to embedded tg-contract",
    )
    args = parser.parse_args(argv)
    try:
        levels = _parse_levels(args.level)
    except ValueError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if not levels:
        print(json.dumps({"status": "fail", "message": "No valid levels requested"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if "L3" in levels and not str(args.topic or args.focus).strip():
        print(json.dumps({"status": "fail", "message": "L3 requires --topic"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    try:
        paths = resolve_plan_paths(
            project_root=args.project_root,
            op_name=args.op_name or None,
            csv_consumer_root=args.csv_consumer_root,
            test_script_root=args.test_script_root,
            kb_root=args.kb_root,
            contract_root=args.contract_root,
        )
        if paths.mode == "reuse_contract":
            assert paths.contract_root is not None
            install_contract_into_project(paths.project_root, paths.op_name, paths.contract_root)
    except ValueError as exc:
        msg = str(exc)
        payload: dict[str, Any] = {
            "status": "fail",
            "message": msg,
            "required": {
                "operator_root": "算子仓 project_root 或 --kb-root",
                "one_of": [
                    "--test-script-root / --csv-consumer-root  (测试工具 → 自动 contract)",
                    "--contract-root  (已有 realization 产物)",
                ],
            },
            "examples": [
                'tg-plan "<算子仓>" --op-name <op> --level L0,L1 --test-script-root "<测试工具>"',
                'tg-plan "<算子仓>" --op-name <op> --level L0,L1 --contract-root "<.../realization>"',
            ],
        }
        if "PLAN_INPUTS_REQUIRED" in msg or "OPERATOR_ROOT_REQUIRED" in msg:
            payload["ask"] = "missing_plan_inputs"
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []
    try:
        for idx, level in enumerate(levels):
            results.append(
                tg_plan(
                    paths.project_root,
                    paths.op_name,
                    level=level,
                    focus=args.focus,
                    topic=args.topic or "",
                    reuse_snapshot=args.reuse_snapshot or idx > 0,
                    csv_consumer_root=paths.test_tool_root,
                    lexicon_seed=args.lexicon_seed,
                )
            )
    except TgPlanError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    common = {
        "project_root": paths.project_root.as_posix(),
        "op_name": paths.op_name,
        "input_mode": paths.mode,
        "test_tool_root": paths.test_tool_root.as_posix() if paths.test_tool_root else "",
        "contract_root": paths.contract_root.as_posix() if paths.contract_root else "",
        "contract_embedded": paths.mode == "build_contract",
        "manual_gate": ["approve", "reject", "suggest"],
    }
    if len(results) > 1:
        print(
            json.dumps(
                {
                    **common,
                    "status": "ready_for_manual_review",
                    "levels": [_plan_summary(item) for item in results],
                    "next": "Approve each requested level, then run tg-solve --level <levels>",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    result = results[0]
    print(
        json.dumps(
            {
                **_plan_summary(result),
                **common,
                "csv_consumer_root": result.get("csv_consumer_root") or common["test_tool_root"],
                "realization_root": result.get("realization_root") or "",
                "next": "AskQuestion approve|reject|suggest; approve then immediately tg-solve",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def solve_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve approved plan with SMT and emit CSV from VAR_CSV_* models")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--level", default="", help="Level or comma-separated levels to solve from plan/levels/<level>.")
    parser.add_argument("--case-name", default="", help="CSV base name.")
    parser.add_argument("--dry-run", action="store_true", help="Solve abstract candidates only; do not write CSV")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress events on stderr")
    parser.add_argument("--jobs", type=int, default=1, help="Parallel fallback workers for hard-to-batch obligations")
    parser.add_argument("--batch-size", type=int, default=512, help="Max compatible obligations per batch solve")
    parser.add_argument(
        "--csv-consumer-root",
        type=Path,
        default=None,
        help="CSV consumer / test script root (optional if tg-contract already wrote realization/)",
    )
    parser.add_argument("--reuse-realization-map", action="store_true", help="Reuse existing realization/realization_map.yaml")
    parser.add_argument(
        "--allow-legacy-realization",
        action="store_true",
        help="Deprecated/no-op: FASG hardcoded emit and heuristic map fallback were removed",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Merge duplicate coverage signatures and run greedy set-cover. Default is no dedupe (keep one solution per SAT obligation).",
    )
    args = parser.parse_args(argv)

    try:
        levels = _parse_levels(args.level) if args.level else [""]
    except ValueError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if not levels:
        print(json.dumps({"status": "fail", "message": "No valid levels requested"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    def make_progress(level: str) -> Any:
        def progress(event: dict[str, Any]) -> None:
            payload = {"status": "progress", **event}
            if level:
                payload["level"] = level
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)

        return progress

    results: list[dict[str, Any]] = []
    try:
        for level in levels:
            case_name = args.case_name
            if len(levels) > 1 and level:
                case_name = f"{args.case_name}_{level}" if args.case_name else level
            results.append(
                tg_solve(
                    args.project_root,
                    args.op_name,
                    timeout_ms=args.timeout_ms,
                    dry_run=args.dry_run,
                    progress=None if args.quiet else make_progress(level),
                    level=level,
                    case_name=case_name,
                    jobs=args.jobs,
                    batch_size=args.batch_size,
                    csv_consumer_root=args.csv_consumer_root,
                    reuse_realization_map=args.reuse_realization_map,
                    allow_legacy_realization=args.allow_legacy_realization,
                    dedupe=bool(args.dedupe),
                )
            )
    except TgSolveError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if len(results) > 1:
        print(
            json.dumps(
                {
                    "status": "complete",
                    "levels": [_solve_summary(item, args.dry_run) for item in results],
                    "dry_run": bool(args.dry_run),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    result = results[0]
    print(json.dumps(_solve_summary(result, args.dry_run), ensure_ascii=False, indent=2))
    return 0


def _parse_levels(raw: str) -> list[str]:
    allowed = {"L0", "L1", "L2", "L3"}
    if str(raw or "").strip().lower() == "all":
        return ["L0", "L1", "L2", "L3"]
    levels: list[str] = []
    for part in str(raw or "").replace(";", ",").split(","):
        level = part.strip().upper()
        if not level:
            continue
        if level not in allowed:
            raise ValueError(f"Invalid --level {level!r}. Allowed: L0,L1,L2,L3,all")
        if level not in levels:
            levels.append(level)
    return levels


def _plan_summary(result: dict[str, Any]) -> dict[str, Any]:
    level = str(result["test_level"])
    csv_stats = (result.get("semantic_focus") or {}).get("csv_realization") or {}
    inventory = result.get("coverage_inventory") or {}
    return {
        "status": result["unresolved"]["status"],
        "test_level": level,
        "topic": result.get("topic") or "",
        "plan_hash": result["plan_hash"],
        "snapshot_hash": result.get("snapshot_hash"),
        "obligations": len(result["obligations"]),
        "pending": len([item for item in result["obligations"] if item.get("status") == "pending"]),
        "coverage_variables": inventory.get("variable_count", 0),
        "coverage_value_points": inventory.get("value_point_count", 0),
        "not_csv_realizable": csv_stats.get("not_csv_realizable_count", 0),
        "extract": result.get("extract"),
        "archive": f"plan/levels/{level}",
        "review": f"plan/levels/{level}/review.md",
        "coverage_inventory": f"plan/levels/{level}/coverage_inventory.yaml",
        "approval": (
            f"python -X utf8 -m testcase_agent.review_checkpoint <project_root> "
            f"--op-name <op_name> --level {level} --decision approve"
        ),
    }


def _solve_summary(result: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    report = result["solver_report"]
    realize = result.get("realize_report") or {}
    return {
        "status": "complete",
        "test_level": result.get("test_level") or "",
        "dedupe_enabled": bool(result.get("dedupe_enabled")),
        "sat": report["status_counts"]["sat"],
        "unsat": report["status_counts"]["unsat"],
        "unknown": report["status_counts"]["unknown"],
        "skipped": report["status_counts"].get("skipped", 0),
        "selected_candidates": report["selected_candidate_count"],
        "csv_path": realize.get("csv_path") or "",
        "realized_count": realize.get("realized_count", 0),
        "blocked_count": realize.get("blocked_count", 0),
        "dry_run": bool(dry_run),
    }


if __name__ == "__main__":
    raise SystemExit(plan_main())
