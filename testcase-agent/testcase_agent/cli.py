from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .contract import TgContractError, tg_contract
from .init import TgInitError, tg_init_full
from .init_status import InitGateError, require_init_confirmed, require_kb
from .path_resolve import (
    infer_op_name,
    install_contract_into_project,
    resolve_operator_project_root,
    resolve_plan_paths,
)
from .planner import TgPlanError, tg_plan
from .solve import TgSolveError, tg_solve


def init_main(argv: list[str] | None = None) -> int:
    """tg-init: KB check + intake + contract + bind scaffolds; optional --confirm."""
    parser = argparse.ArgumentParser(
        description=(
            "tg-init: intake + CSV contract + binding scaffolds. "
            "KB defaults to <算子仓>/.understand-operator/<op>. Missing KB → uo_init_required."
        )
    )
    parser.add_argument("project_root", type=Path, nargs="?", default=None, help="算子仓")
    parser.add_argument("--op-name", default="", help="Optional if uniquely inferable")
    parser.add_argument(
        "--test-script-root",
        type=Path,
        default=None,
        help="测试工具 / CSV consumer root（绑定所需）",
    )
    parser.add_argument(
        "--csv-consumer-root",
        type=Path,
        default=None,
        help="--test-script-root 别名",
    )
    parser.add_argument("--kb-root", type=Path, default=None, help="Optional KB override (not required)")
    parser.add_argument("--lexicon-seed", type=Path, default=None)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="After merge passes domain symmetry, set init.status=confirmed",
    )
    parser.add_argument(
        "--merge-uo-resolve",
        action="store_true",
        help="Merge realization/uo_query_resolve/*.yaml into binding_lexicon + domain align",
    )
    parser.add_argument(
        "--verify-csv-closure",
        action="store_true",
        help="Strong gate: every closable mid-symbol must close to VAR_CSV_* (before audit/confirm)",
    )
    parser.add_argument(
        "--list-open-mids",
        action="store_true",
        help="Write/print realization/mid_symbol_queue.yaml for nested uo-query Tasks",
    )
    parser.add_argument("--notes", default="", help="Optional confirm notes")
    args = parser.parse_args(argv)

    try:
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

        if args.merge_uo_resolve:
            from .io import output_root
            from .uo_resolve_merge import UoMergeError, merge_uo_resolve

            out_root = output_root(project_root, op_name)
            try:
                report = merge_uo_resolve(out_root)
            except UoMergeError as exc:
                print(
                    json.dumps(
                        {"status": "fail", "ask": exc.ask, "message": str(exc), "report": exc.report},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    file=sys.stderr,
                )
                return 1
            print(json.dumps({"status": "ok", "op_name": op_name, "merge": report}, ensure_ascii=False, indent=2))
            return 0

        if args.verify_csv_closure or args.list_open_mids:
            from .io import output_root
            from .resolve_policy import require_full_csv_closure, write_mid_symbol_queue

            out_root = output_root(project_root, op_name)
            if args.list_open_mids and not args.verify_csv_closure:
                queue = write_mid_symbol_queue(out_root)
                print(json.dumps({"status": "ok", "op_name": op_name, "mid_symbol_queue": queue}, ensure_ascii=False, indent=2))
                return 0
            result = require_full_csv_closure(out_root)
            write_mid_symbol_queue(out_root)
            print(json.dumps({"status": result.get("status"), "op_name": op_name, "verify": result}, ensure_ascii=False, indent=2))
            return 0 if result.get("status") == "pass" else 1

        consumer = args.test_script_root or args.csv_consumer_root
        result = tg_init_full(
            project_root,
            op_name,
            test_script_root=consumer,
            kb_root=args.kb_root,
            lexicon_seed=args.lexicon_seed,
            confirm=bool(args.confirm),
            notes=args.notes or "",
        )
    except ValueError as exc:
        print(json.dumps({"status": "fail", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except InitGateError as exc:
        print(
            json.dumps({"status": "fail", "ask": exc.ask, "message": str(exc), **exc.payload}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        return 1
    except TgInitError as exc:
        payload: dict[str, Any] = {"status": "fail", "message": str(exc), "report": exc.report}
        if exc.ask:
            payload["ask"] = exc.ask
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
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
            "Build L0 / L1-branch / L1-reject / L2 coverage plans. "
            "Requires tg-init confirmed (binding done). --level L1 expands to both L1 suites."
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
    parser.add_argument(
        "--level",
        default="L1",
        help="Level(s): L0,L1-branch,L1-reject,L2 (L1→both branch+reject; all→all four). Legacy L3 needs --topic.",
    )
    parser.add_argument("--focus", default="")
    parser.add_argument("--topic", default="", help="Optional topic filter for L1 suites / L2 (and required for legacy L3)")
    parser.add_argument("--reuse-snapshot", action="store_true", help="Skip intake when snapshot hash still matches")
    parser.add_argument(
        "--csv-consumer-root",
        type=Path,
        default=None,
        help="可选：仅在未走 tg-init 的兼容路径下重建 contract（优先用 init 产物）。",
    )
    parser.add_argument(
        "--test-script-root",
        type=Path,
        default=None,
        help="--csv-consumer-root 别名。",
    )
    parser.add_argument(
        "--contract-root",
        type=Path,
        default=None,
        help="已有 contract 产物目录。init 完成后通常不需要。",
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
        help="Optional binding_lexicon.yaml seed (compat path only)",
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
        require_kb(paths.project_root, paths.op_name, kb_root=args.kb_root)
        require_init_confirmed(paths.project_root, paths.op_name)
        if paths.mode == "reuse_contract":
            assert paths.contract_root is not None
            install_contract_into_project(paths.project_root, paths.op_name, paths.contract_root)
    except InitGateError as exc:
        payload = {
            "status": "fail",
            "message": str(exc),
            "ask": exc.ask,
            **exc.payload,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except ValueError as exc:
        msg = str(exc)
        payload = {
            "status": "fail",
            "message": msg,
            "required": {
                "operator_root": "算子仓 project_root",
                "preferred": "tg-init confirmed → realization under .testcase-generator/<op>/",
                "compat": ["--test-script-root", "--contract-root"],
            },
            "examples": [
                'tg-init "<算子仓>" --op-name <op> --test-script-root "<测试工具>"',
                'tg-init "<算子仓>" --op-name <op> --confirm',
                'tg-plan "<算子仓>" --op-name <op> --level L0,L1,L2',
            ],
        }
        if "PLAN_INPUTS_REQUIRED" in msg or "OPERATOR_ROOT_REQUIRED" in msg:
            payload["ask"] = "init_required"
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    # Prefer init realization; only rebuild contract when explicitly asked via test-script on compat path.
    rebuild_consumer = paths.test_tool_root if paths.mode == "build_contract" else None

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
                    csv_consumer_root=rebuild_consumer,
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
                    "next": "Approve each requested level, then run tg-solve --level <L0|L1-BRANCH|L1-REJECT|L2>",
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
                "next": "AskQuestion approve|reject|suggest; approve only when Allow solve:yes then tg-solve",
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
    parser.add_argument("--level", default="", help="Level or comma-separated: L0,L1-BRANCH,L1-REJECT,L2 (L1→both)")
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
    """Parse --level. L1 expands to L1-BRANCH + L1-REJECT. Canonical names are uppercase."""
    allowed = {"L0", "L1", "L1-BRANCH", "L1-REJECT", "L2", "L3"}
    if str(raw or "").strip().lower() == "all":
        return ["L0", "L1-BRANCH", "L1-REJECT", "L2"]
    levels: list[str] = []
    for part in str(raw or "").replace(";", ",").split(","):
        token = part.strip().upper().replace("_", "-")
        if not token:
            continue
        # Accept L1BRANCH / L1REJECT spellings
        if token in {"L1BRANCH", "L1-BRANCH"}:
            token = "L1-BRANCH"
        elif token in {"L1REJECT", "L1-REJECT"}:
            token = "L1-REJECT"
        if token not in allowed:
            raise ValueError(
                f"Invalid --level {part!r}. Allowed: L0,L1,L1-branch,L1-reject,L2,L3,all "
                "(L1 expands to L1-branch + L1-reject)"
            )
        if token == "L1":
            for expanded in ("L1-BRANCH", "L1-REJECT"):
                if expanded not in levels:
                    levels.append(expanded)
            continue
        if token not in levels:
            levels.append(token)
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
