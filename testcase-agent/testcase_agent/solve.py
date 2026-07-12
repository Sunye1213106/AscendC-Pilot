from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidates import build_candidate, dedupe_candidates, greedy_set_cover
from .constraint_ir import build_constraint_ir
from .io import ensure_output_dirs, output_root, read_json, read_yaml, write_yaml
from .z3_backend import SolveConfig, Z3Backend


class TgSolveError(RuntimeError):
    pass


def tg_solve(project_root: Path, op_name: str, *, timeout_ms: int = 5000) -> dict[str, Any]:
    project_root = project_root.resolve()
    out_root = output_root(project_root, op_name)
    ensure_output_dirs(out_root)
    snapshot_path = out_root / "snapshot" / "understand_contract.json"
    obligations_path = out_root / "plan" / "coverage_obligations.yaml"
    supplement_path = out_root / "plan" / "human_supplement.yaml"
    if not snapshot_path.exists():
        raise TgSolveError(f"Missing phase-one snapshot: {snapshot_path}")
    if not obligations_path.exists():
        raise TgSolveError(f"Missing phase-one coverage plan: {obligations_path}")
    if not supplement_path.exists():
        raise TgSolveError(f"Missing phase-one approval result: {supplement_path}")

    snapshot = read_json(snapshot_path)
    obligations_doc = read_yaml(obligations_path)
    supplement = read_yaml(supplement_path)
    _require_approval(supplement)

    result = solve_from_docs(snapshot, obligations_doc, supplement, timeout_ms=timeout_ms)
    write_solve_outputs(out_root, result)
    return result


def solve_from_docs(snapshot: dict[str, Any], obligations_doc: dict[str, Any], supplement: dict[str, Any], *, timeout_ms: int = 5000) -> dict[str, Any]:
    obligations = [item for item in obligations_doc.get("obligations", []) if isinstance(item, dict)]
    ir_result = build_constraint_ir(snapshot, obligations_doc, supplement)
    ir = ir_result.ir
    candidates: list[dict[str, Any]] = []
    solve_results: list[dict[str, Any]] = []
    unsat: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = list(ir_result.errors)

    if not ir_result.errors:
        backend = Z3Backend(ir, SolveConfig(timeout_ms=timeout_ms))
        for obligation in obligations:
            if obligation.get("status") in {"proof_required", "conflicting", "unresolved"}:
                solve_results.append({"obligation_id": obligation.get("id"), "status": "skipped", "model": {}, "reason": f"obligation status is {obligation.get('status')}"})
                continue
            result = backend.solve_one(obligation)
            solve_results.append(result)
            if result["status"] == "sat":
                candidates.append(build_candidate(obligation, result))
            elif result["status"] == "unsat":
                unsat.append(
                    {
                        "obligation_id": result["obligation_id"],
                        "kind": obligation.get("kind"),
                        "priority": obligation.get("priority"),
                        "target_refs": obligation.get("target_refs") or [],
                        "unsat_core": result.get("unsat_core") or [],
                        "reason": result.get("reason") or "unsat",
                    }
                )
            elif result["status"] == "unknown":
                unknown.append(
                    {
                        "obligation_id": result["obligation_id"],
                        "kind": obligation.get("kind"),
                        "priority": obligation.get("priority"),
                        "reason": result.get("reason") or "unknown",
                    }
                )
            elif result["status"] == "error":
                errors.append({"code": "OBLIGATION_SOLVE_ERROR", "obligation_id": str(result["obligation_id"]), "message": result.get("reason", "")})
    else:
        solve_results = [{"obligation_id": item.get("id"), "status": "skipped", "model": {}, "reason": "constraint IR has compile errors"} for item in obligations]

    deduped = dedupe_candidates(candidates)
    selected = greedy_set_cover(deduped, [item for item in obligations if item.get("status") == "pending"])
    report = build_solver_report(obligations, solve_results, candidates, deduped, selected, unsat, unknown, errors)
    return {
        "version": 1,
        "created_at": _now(),
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "constraint_ir": ir,
        "solve_results": solve_results,
        "candidates": candidates,
        "deduped_candidates": deduped,
        "selected_candidates": selected["selected_candidates"],
        "uncovered_obligations": selected["uncovered_obligations"],
        "unsat_obligations": unsat,
        "unknown_obligations": unknown,
        "errors": errors,
        "solver_report": report,
    }


def write_solve_outputs(out_root: Path, result: dict[str, Any]) -> None:
    solve_root = out_root / "solve"
    write_yaml(solve_root / "constraint_ir.yaml", result["constraint_ir"])
    write_yaml(
        solve_root / "candidates.yaml",
        {
            "version": 1,
            "snapshot_hash": result["snapshot_hash"],
            "raw_count": len(result["candidates"]),
            "deduped_count": len(result["deduped_candidates"]),
            "candidates": result["deduped_candidates"],
        },
    )
    write_yaml(
        solve_root / "selected_candidates.yaml",
        {
            "version": 1,
            "snapshot_hash": result["snapshot_hash"],
            "selected_count": len(result["selected_candidates"]),
            "selected_candidates": result["selected_candidates"],
            "uncovered_obligations": result["uncovered_obligations"],
        },
    )
    write_yaml(solve_root / "solver_report.yaml", result["solver_report"])
    write_yaml(
        solve_root / "unsat_obligations.yaml",
        {
            "version": 1,
            "snapshot_hash": result["snapshot_hash"],
            "unsat_obligations": result["unsat_obligations"],
            "unknown_obligations": result["unknown_obligations"],
            "errors": result["errors"],
        },
    )
    (solve_root / "solver_report.md").write_text(result["solver_report"]["chinese_report"], encoding="utf-8")


def build_solver_report(
    obligations: list[dict[str, Any]],
    solve_results: list[dict[str, Any]],
    raw_candidates: list[dict[str, Any]],
    deduped_candidates: list[dict[str, Any]],
    selected: dict[str, Any],
    unsat: list[dict[str, Any]],
    unknown: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = {
        "sat": len([item for item in solve_results if item.get("status") == "sat"]),
        "unsat": len([item for item in solve_results if item.get("status") == "unsat"]),
        "unknown": len([item for item in solve_results if item.get("status") == "unknown"]),
        "error": len([item for item in solve_results if item.get("status") == "error"]),
        "skipped": len([item for item in solve_results if item.get("status") == "skipped"]),
    }
    obligation_by_id = {str(item.get("id")): item for item in obligations}
    uncovered_hard = [
        item
        for item in selected["uncovered_obligations"]
        if obligation_by_id.get(str(item.get("id")), {}).get("priority") == "hard"
    ]
    lines = [
        "# TestAgent 阶段二求解报告",
        "",
        f"- 总 Obligation 数: {len(obligations)}",
        f"- SAT / UNSAT / UNKNOWN 数: {counts['sat']} / {counts['unsat']} / {counts['unknown']}",
        f"- 原始候选数: {len(raw_candidates)}",
        f"- 去重后候选数: {len(deduped_candidates)}",
        f"- Set Cover 后候选数: {len(selected['selected_candidates'])}",
        f"- 未覆盖 Hard Obligation: {len(uncovered_hard)}",
        f"- UNSAT 原因摘要: {', '.join(_summarize_unsat(unsat)) if unsat else '无'}",
        f"- Contract 中无法编译的表达式: {len(errors)}",
        "",
        "阶段二到此停止，不进入真实用例生成。",
    ]
    return {
        "version": 1,
        "status_counts": counts,
        "total_obligations": len(obligations),
        "raw_candidate_count": len(raw_candidates),
        "deduped_candidate_count": len(deduped_candidates),
        "selected_candidate_count": len(selected["selected_candidates"]),
        "uncovered_hard_obligations": uncovered_hard,
        "unsat_summary": _summarize_unsat(unsat),
        "compile_errors": errors,
        "chinese_report": "\n".join(lines) + "\n",
    }


def _require_approval(supplement: dict[str, Any]) -> None:
    decision = str(supplement.get("decision") or supplement.get("approval") or "").strip().lower()
    status = str(supplement.get("status") or "").strip().lower()
    approved = supplement.get("approved") is True
    if decision != "approve" and status not in {"approved", "approve"} and not approved:
        raise TgSolveError("Phase-one approval is required before tg-solve. Set plan/human_supplement.yaml decision: approve.")


def _summarize_unsat(unsat: list[dict[str, Any]]) -> list[str]:
    out = []
    for item in unsat[:5]:
        core = item.get("unsat_core") or []
        out.append(f"{item.get('obligation_id')}: {', '.join(core) if core else item.get('reason', 'unsat')}")
    return out


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
