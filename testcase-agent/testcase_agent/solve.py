from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .candidates import CandidateError, build_candidate, dedupe_candidates, greedy_set_cover
from .composer import compose_global_legal, merge_composed_into_ir
from .constraint_ir import build_constraint_ir, compile_obligation_target
from .hashing import semantic_plan_hash, semantic_snapshot_hash
from .io import ensure_output_dirs, output_root, read_json, read_yaml, write_yaml
from .realization_contract import ContractError, load_contract, prepare_contract_inputs, realization_paths
from .realization_dsl import normalize_realization_map, realization_report
from .realization_map import build_realization_map
from .realization_schema import discover_consumer_root, extract_consumer_schema
from .realization_validation import ensure_valid_contract
from .realize import realize_candidates_to_csv
from .z3_backend import SolveConfig, Z3Backend


class TgSolveError(RuntimeError):
    pass


ProgressCallback = Callable[[dict[str, Any]], None]


def tg_solve(
    project_root: Path,
    op_name: str,
    *,
    timeout_ms: int = 5000,
    dry_run: bool = False,
    progress: ProgressCallback | None = None,
    level: str = "",
    case_name: str = "",
    jobs: int = 1,
    batch_size: int = 512,
    csv_consumer_root: Path | None = None,
    reuse_realization_map: bool = False,
    allow_legacy_realization: bool = False,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    out_root = output_root(project_root, op_name)
    ensure_output_dirs(out_root)
    snapshot_path = out_root / "snapshot" / "understand_contract.json"
    plan_dir = _plan_dir(out_root, level)
    obligations_path = plan_dir / "coverage_obligations.yaml"
    matrix_path = plan_dir / "coverage_matrix.yaml"
    unresolved_path = plan_dir / "unresolved.yaml"
    supplement_path = plan_dir / "human_supplement.yaml"
    semantic_focus_path = plan_dir / "semantic_focus.yaml"
    extract_path = out_root / "extract" / "generation_conditions.yaml"
    if not snapshot_path.exists():
        raise TgSolveError(f"Missing snapshot. Run tg-plan first: {snapshot_path}")
    if not obligations_path.exists():
        raise TgSolveError(f"Missing coverage plan. Run tg-plan first: {obligations_path}")
    if not matrix_path.exists():
        raise TgSolveError(f"Missing coverage matrix: {matrix_path}")
    if not unresolved_path.exists():
        raise TgSolveError(f"Missing unresolved report: {unresolved_path}")
    if not supplement_path.exists():
        raise TgSolveError(f"Missing approval file: {supplement_path}")

    snapshot = read_json(snapshot_path)
    if snapshot.get("snapshot_hash") != semantic_snapshot_hash(snapshot):
        raise TgSolveError("SNAPSHOT_HASH_MISMATCH: snapshot_hash does not match snapshot contents")
    obligations_doc = read_yaml(obligations_path)
    matrix_doc = read_yaml(matrix_path)
    unresolved_doc = read_yaml(unresolved_path)
    supplement = read_yaml(supplement_path)
    semantic_focus_doc = read_yaml(semantic_focus_path) if semantic_focus_path.exists() else {}
    extract_doc = read_yaml(extract_path) if extract_path.exists() else {}
    planning_context = semantic_focus_doc.get("planning_context") if isinstance(semantic_focus_doc, dict) else {}
    hash_matrix_doc = dict(matrix_doc)
    hash_unresolved_doc = dict(unresolved_doc)
    hash_matrix_doc.pop("test_level", None)
    hash_unresolved_doc.pop("test_level", None)
    plan_hash = semantic_plan_hash(snapshot.get("snapshot_hash"), obligations_doc.get("obligations", []), hash_matrix_doc, hash_unresolved_doc, planning_context)
    recorded_plan_hash = obligations_doc.get("plan_hash") or matrix_doc.get("plan_hash") or unresolved_doc.get("plan_hash")
    if recorded_plan_hash != plan_hash:
        raise TgSolveError("PLAN_HASH_MISMATCH: plan_hash does not match phase-one plan contents")
    _require_approval(supplement, snapshot.get("snapshot_hash"), plan_hash, unresolved_doc)
    realization = load_or_build_realization(
        out_root,
        project_root,
        snapshot,
        plan_hash=plan_hash,
        level=str(obligations_doc.get("test_level") or level or ""),
        csv_consumer_root=csv_consumer_root,
        reuse_realization_map=reuse_realization_map,
        allow_legacy_realization=allow_legacy_realization,
        progress=progress,
    )

    result = solve_from_docs(
        snapshot,
        obligations_doc,
        supplement,
        timeout_ms=timeout_ms,
        matrix_doc=matrix_doc,
        unresolved_doc=unresolved_doc,
        extract_doc=extract_doc,
        progress=progress,
        jobs=jobs,
        batch_size=batch_size,
        realization_map=realization["realization_map"],
    )
    result["test_level"] = str(obligations_doc.get("test_level") or level or "")
    _emit_progress(progress, stage="realize", status="start", selected_candidates=len(result.get("selected_candidates") or []), dry_run=dry_run)
    realize_report = realize_candidates_to_csv(
        out_root,
        result.get("selected_candidates") or [],
        snapshot,
        consumer_schema=realization["schema"],
        realization_map=realization["realization_map"],
        obligations=obligations_doc.get("obligations", []),
        dry_run=dry_run,
        level=str(obligations_doc.get("test_level") or level or ""),
        case_name=case_name,
        allow_legacy_realization=allow_legacy_realization,
    )
    result["realize_report"] = realize_report
    result["realization_report"] = realization["report"]
    result["contract_validation"] = realization["validation"]
    solve_root = _solve_dir(out_root, str(obligations_doc.get("test_level") or level or ""), case_name)
    write_solve_outputs(solve_root, result)
    _emit_progress(progress, stage="write_outputs", status="complete", solve_dir=str(solve_root))
    return result


def load_or_build_realization(
    out_root: Path,
    project_root: Path,
    snapshot: dict[str, Any],
    *,
    plan_hash: str,
    level: str = "",
    csv_consumer_root: Path | None,
    reuse_realization_map: bool,
    allow_legacy_realization: bool,
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    paths = realization_paths(out_root)
    snapshot_path = out_root / "snapshot" / "understand_contract.json"
    obligations_path = _plan_dir(out_root, level) / "coverage_obligations.yaml"
    _emit_progress(progress, stage="realization_prepare", status="start")
    consumer_root = None
    if csv_consumer_root is not None:
        consumer_root = discover_consumer_root(project_root, csv_consumer_root)
    if consumer_root is None and paths["evidence"].exists():
        evidence = read_yaml(paths["evidence"])
        _emit_progress(progress, stage="realization_prepare", status="reuse", reason="using_existing_evidence")
    else:
        if consumer_root is None:
            # Prefer existing contract; do not silently discover FASG.
            if paths["map"].exists() and paths["schema"].exists() and paths["evidence"].exists():
                evidence = read_yaml(paths["evidence"])
            else:
                raise TgSolveError(
                    "CSV_CONSUMER_ROOT_REQUIRED: pass --csv-consumer-root or run tg-contract first"
                )
        else:
            evidence = prepare_contract_inputs(
                out_root,
                consumer_root=consumer_root,
                snapshot_path=snapshot_path,
                obligations_path=obligations_path,
            )
    _emit_progress(
        progress,
        stage="realization_prepare",
        status="complete",
        evidence_hash=evidence.get("evidence_hash", ""),
        scanned_files=len(evidence.get("files_read") or []),
    )
    try:
        loaded_evidence, schema, realization_map = load_contract(paths)
        realization_map = normalize_realization_map(realization_map)
        # Keep hashes aligned with current plan after tg-plan refresh.
        for doc in (loaded_evidence, schema, realization_map):
            doc["plan_hash"] = plan_hash
            doc["snapshot_hash"] = str(snapshot.get("snapshot_hash") or "")
            if "evidence_hash" not in doc or not doc.get("evidence_hash"):
                doc["evidence_hash"] = loaded_evidence.get("evidence_hash", "")
        schema["evidence_hash"] = loaded_evidence.get("evidence_hash", "")
        realization_map["evidence_hash"] = loaded_evidence.get("evidence_hash", "")
        validation = ensure_valid_contract(
            loaded_evidence,
            schema,
            realization_map,
            snapshot_hash=str(snapshot.get("snapshot_hash") or ""),
            plan_hash=plan_hash,
        )
        report = realization_report(realization_map)
        report.update(validation)
        write_yaml(paths["report"], report)
        _emit_progress(progress, stage="realization_validate", status="complete", contract_hash=validation["contract_hash"])
        return {"evidence": loaded_evidence, "schema": schema, "realization_map": realization_map, "report": report, "validation": validation}
    except ContractError as exc:
        if not allow_legacy_realization:
            raise TgSolveError(
                f"{exc}. Re-run tg-contract /tg-csv-contract, or pass --allow-legacy-realization "
                "(FASG-only heuristic fallback; not recommended)."
            ) from exc
        _emit_progress(progress, stage="realization_validate", status="legacy_fallback", reason=str(exc))
        _emit_progress(progress, stage="realization_schema", status="start")
        schema = extract_consumer_schema(consumer_root)
        write_yaml(paths["schema"], schema)
        _emit_progress(progress, stage="realization_schema", status="complete", columns=len(schema.get("columns") or []), consumer_root=schema.get("consumer_root", ""))
        if reuse_realization_map and paths["map"].exists():
            realization_map = normalize_realization_map(read_yaml(paths["map"]))
            _emit_progress(progress, stage="realization_map", status="reuse", path=str(paths["map"]))
        else:
            _emit_progress(progress, stage="realization_map", status="start")
            realization_map = build_realization_map(snapshot, schema)
            write_yaml(paths["map"], realization_map)
            _emit_progress(
                progress,
                stage="realization_map",
                status="complete",
                csv_variables=len(realization_map.get("csv_variables") or []),
                derived_variables=len(realization_map.get("derived_variables") or []),
                mapped_branches=len(realization_map.get("branch_mappings") or []),
                abstract_branches=len(realization_map.get("abstract_branches") or []),
            )
        report = realization_report(realization_map)
        report["legacy_mode"] = True
        report["warnings"] = list(report.get("warnings") or []) + [
            "allow_legacy_realization: using FASG heuristic map; SMT→CSV identity not guaranteed"
        ]
        write_yaml(paths["report"], report)
        return {
            "evidence": evidence,
            "schema": schema,
            "realization_map": realization_map,
            "report": report,
            "validation": {
                "status": "legacy",
                "contract_hash": "",
                "evidence_hash": evidence.get("evidence_hash", ""),
                "csv_solver_variable_count": len(realization_map.get("csv_variables") or []),
                "emit_derived_field_count": 0,
                "unmapped_required_field_count": 0,
                "abstract_branch_count": len(realization_map.get("abstract_branches") or []),
            },
        }


def _plan_dir(out_root: Path, level: str) -> Path:
    level = str(level or "").strip().upper()
    if not level:
        return out_root / "plan"
    return out_root / "plan" / "levels" / level


def _solve_dir(out_root: Path, level: str, case_name: str) -> Path:
    level = str(level or "").strip().upper()
    case = _safe_name(case_name) if case_name else ""
    if level:
        base = out_root / "solve" / "levels" / level
        return base / case if case else base
    if case:
        return out_root / "solve" / case
    return out_root / "solve"


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value).strip())
    return safe.strip("_") or "cases"


def solve_from_docs(
    snapshot: dict[str, Any],
    obligations_doc: dict[str, Any],
    supplement: dict[str, Any],
    *,
    timeout_ms: int = 5000,
    matrix_doc: dict[str, Any] | None = None,
    unresolved_doc: dict[str, Any] | None = None,
    extract_doc: dict[str, Any] | None = None,
    progress: ProgressCallback | None = None,
    jobs: int = 1,
    batch_size: int = 512,
    realization_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obligations = [item for item in obligations_doc.get("obligations", []) if isinstance(item, dict)]
    _emit_progress(progress, stage="constraint_ir", status="start", total_obligations=len(obligations))
    ir_result = build_constraint_ir(snapshot, obligations_doc, supplement, realization_map=realization_map)
    ir = ir_result.ir
    composed = compose_global_legal(extract_doc, supplement)
    ir = merge_composed_into_ir(ir, composed)
    _emit_progress(progress, stage="constraint_ir", status="complete", variables=len(ir.get("variables") or []), constraints=len(ir.get("constraints") or []), errors=len(ir_result.global_errors))
    candidates: list[dict[str, Any]] = []
    solve_results: list[dict[str, Any]] = []
    unsat: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = list(ir_result.global_errors)

    if not ir_result.global_errors:
        batch_result = solve_obligations_optimized(
            ir,
            obligations,
            ir_result.obligation_errors,
            timeout_ms=timeout_ms,
            progress=progress,
            jobs=max(1, int(jobs or 1)),
            batch_size=max(1, int(batch_size or 1)),
        )
        solve_results = batch_result["solve_results"]
        candidates = batch_result["candidates"]
        unsat = batch_result["unsat"]
        unknown = batch_result["unknown"]
        errors.extend(batch_result["errors"])
    else:
        solve_results = [{"obligation_id": item.get("id"), "status": "skipped", "model": {}, "reason": "constraint IR has global compile errors"} for item in obligations]

    _emit_progress(progress, stage="dedupe", status="start", raw_candidates=len(candidates))
    try:
        deduped = dedupe_candidates(candidates, obligations)
    except CandidateError as exc:
        errors.append({"code": "CONTRADICTORY_BRANCH_COVERAGE", "message": str(exc)})
        deduped = []
    try:
        _emit_progress(progress, stage="set_cover", status="start", deduped_candidates=len(deduped))
        selected = greedy_set_cover(deduped, [item for item in obligations if item.get("status") == "pending"])
    except CandidateError as exc:
        errors.append({"code": "CONTRADICTORY_BRANCH_COVERAGE", "scope": "global", "severity": "error", "message": str(exc)})
        selected = {"selected_candidates": [], "uncovered_obligations": [{"id": item.get("id"), "kind": item.get("kind"), "priority": item.get("priority"), "reason": "candidate branch coverage conflict"} for item in obligations if item.get("status") == "pending"]}
    report = build_solver_report(obligations, solve_results, candidates, deduped, selected, unsat, unknown, errors)
    _emit_progress(
        progress,
        stage="solve",
        status="complete",
        sat=report["status_counts"]["sat"],
        unsat=report["status_counts"]["unsat"],
        unknown=report["status_counts"]["unknown"],
        raw_candidates=len(candidates),
        deduped_candidates=len(deduped),
        selected_candidates=len(selected["selected_candidates"]),
    )
    return {
        "version": 1,
        "created_at": _now(),
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "constraint_ir": ir,
        "composed_legal_count": len(composed),
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


def solve_obligations_optimized(
    ir: dict[str, Any],
    obligations: list[dict[str, Any]],
    obligation_errors: dict[str, list[dict[str, Any]]],
    *,
    timeout_ms: int,
    progress: ProgressCallback | None,
    jobs: int,
    batch_size: int,
) -> dict[str, Any]:
    backend = Z3Backend(ir, SolveConfig(timeout_ms=timeout_ms))
    if getattr(Z3Backend.solve_one, "__name__", "solve_one") != "solve_one":
        return _solve_obligations_via_solve_one(backend, obligations, obligation_errors, progress=progress)
    total = len(obligations)
    result_by_id: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    unsat: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    prepared: list[dict[str, Any]] = []
    obligation_by_id = {str(item.get("id") or ""): item for item in obligations}

    _emit_progress(
        progress,
        stage="solve",
        status="start",
        total_obligations=total,
        timeout_ms=timeout_ms,
        solve_mode="batch-indexed",
        jobs=jobs,
        batch_size=batch_size,
    )

    for obligation in obligations:
        oid = str(obligation.get("id") or "")
        local_errors = obligation_errors.get(oid) or []
        if local_errors:
            first = local_errors[0]
            result_by_id[oid] = {
                "obligation_id": obligation.get("id"),
                "status": "error",
                "code": first.get("code"),
                "model": {},
                "unsat_core": [],
                "reason": first.get("message") or first.get("code") or "obligation compile error",
                "errors": local_errors,
            }
            errors.extend(local_errors)
            continue
        if obligation.get("status") in {"proof_required", "conflicting", "unresolved", "skipped"}:
            result_by_id[oid] = {"obligation_id": obligation.get("id"), "status": "skipped", "model": {}, "reason": f"obligation status is {obligation.get('status')}"}
            continue
        target = compile_obligation_target(obligation, ir)
        if target.status != "ok":
            result_by_id[oid] = {
                "obligation_id": obligation.get("id"),
                "status": target.status,
                "code": target.code,
                "model": {},
                "unsat_core": [],
                "reason": target.reason,
            }
            if target.status == "error":
                errors.append({"code": target.code or "OBLIGATION_TARGET_NOT_COMPILED", "obligation_id": oid, "message": target.reason})
            continue
        assignments = _extract_eq_assignments(target.expr)
        prepared.append({"id": oid, "obligation": obligation, "expr": target.expr, "assignments": assignments})

    index = _build_coverage_index(prepared)
    batchable = [item for item in prepared if item["assignments"]]
    fallback = [item for item in prepared if not item["assignments"]]
    pending_ids = {item["id"] for item in prepared}
    progress_every = max(1, min(100, total // 20 or 1))
    last_progress = len(result_by_id)

    batch_round = 0
    while pending_ids:
        group = _next_compatible_batch(batchable, pending_ids, batch_size)
        if not group:
            break
        batch_round += 1
        _solve_prepared_batch(
            backend,
            group,
            index,
            prepared,
            pending_ids,
            result_by_id,
            candidates,
            unsat,
            unknown,
            errors,
        )
        solved = len(result_by_id)
        if solved == total or solved - last_progress >= progress_every:
            _emit_solve_running(progress, solved, total, candidates, unsat, unknown, errors, batch_round=batch_round, fallback_pending=len(fallback))
            last_progress = solved

    fallback.extend(item for item in prepared if item["id"] in pending_ids and item not in fallback)
    if fallback:
        _emit_progress(progress, stage="solve_fallback", status="start", pending=len(fallback), jobs=jobs)
        for item, result in _solve_fallback_items(ir, fallback, timeout_ms=timeout_ms, jobs=jobs):
            oid = item["id"]
            if oid not in pending_ids:
                continue
            result_by_id[oid] = result
            pending_ids.discard(oid)
            if result["status"] == "sat":
                covered_ids = _covered_ids_from_model(backend, result.get("model") or {}, index, prepared, pending_ids | {oid})
                if oid not in covered_ids:
                    covered_ids.append(oid)
                _record_sat_candidate(item, result, covered_ids, pending_ids, result_by_id, candidates, obligation_by_id)
            elif result["status"] == "unsat":
                unsat.append(_unsat_entry(item["obligation"], result))
            elif result["status"] == "unknown":
                unknown.append(_unknown_entry(item["obligation"], result))
            elif result["status"] == "error":
                errors.append({"code": result.get("code") or "OBLIGATION_SOLVE_ERROR", "obligation_id": str(result["obligation_id"]), "message": result.get("reason", "")})
            solved = len(result_by_id)
            if solved == total or solved - last_progress >= progress_every:
                _emit_solve_running(progress, solved, total, candidates, unsat, unknown, errors, batch_round=batch_round, fallback_pending=max(0, len(fallback) - solved))
                last_progress = solved

    for item in prepared:
        oid = item["id"]
        if oid in result_by_id:
            continue
        result_by_id[oid] = {"obligation_id": oid, "status": "unknown", "model": {}, "unsat_core": [], "reason": "not solved by batch or fallback"}
        unknown.append(_unknown_entry(item["obligation"], result_by_id[oid]))

    _emit_solve_running(progress, len(result_by_id), total, candidates, unsat, unknown, errors, batch_round=batch_round, fallback_pending=0)
    return {
        "solve_results": [result_by_id.get(str(item.get("id") or ""), {"obligation_id": item.get("id"), "status": "skipped", "model": {}, "reason": "missing result"}) for item in obligations],
        "candidates": candidates,
        "unsat": unsat,
        "unknown": unknown,
        "errors": errors,
    }


def _solve_prepared_batch(
    backend: Z3Backend,
    group: list[dict[str, Any]],
    index: dict[str, Any],
    prepared: list[dict[str, Any]],
    pending_ids: set[str],
    result_by_id: dict[str, dict[str, Any]],
    candidates: list[dict[str, Any]],
    unsat: list[dict[str, Any]],
    unknown: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    active = [item for item in group if item["id"] in pending_ids]
    if not active:
        return
    expr = _batch_expr(active)
    result = backend.solve_expr(expr, label=f"batch:{active[0]['id']}:{len(active)}", obligation_id=active[0]["id"])
    if result["status"] == "sat":
        covered_ids = _covered_ids_from_model(backend, result.get("model") or {}, index, prepared, pending_ids)
        if not covered_ids:
            covered_ids = [active[0]["id"]]
        _record_sat_candidate(active[0], result, covered_ids, pending_ids, result_by_id, candidates, index["obligation_by_id"])
        return
    if len(active) > 1:
        mid = max(1, len(active) // 2)
        _solve_prepared_batch(backend, active[:mid], index, prepared, pending_ids, result_by_id, candidates, unsat, unknown, errors)
        _solve_prepared_batch(backend, active[mid:], index, prepared, pending_ids, result_by_id, candidates, unsat, unknown, errors)
        return
    item = active[0]
    oid = item["id"]
    result_by_id[oid] = result
    pending_ids.discard(oid)
    if result["status"] == "unsat":
        unsat.append(_unsat_entry(item["obligation"], result))
    elif result["status"] == "unknown":
        unknown.append(_unknown_entry(item["obligation"], result))
    elif result["status"] == "error":
        errors.append({"code": result.get("code") or "OBLIGATION_SOLVE_ERROR", "obligation_id": str(result["obligation_id"]), "message": result.get("reason", "")})


def _solve_obligations_via_solve_one(
    backend: Z3Backend,
    obligations: list[dict[str, Any]],
    obligation_errors: dict[str, list[dict[str, Any]]],
    *,
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    solve_results: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    unsat: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for obligation in obligations:
        oid = str(obligation.get("id") or "")
        local_errors = obligation_errors.get(oid) or []
        if local_errors:
            result = {"obligation_id": oid, "status": "error", "model": {}, "unsat_core": [], "reason": local_errors[0].get("message", ""), "errors": local_errors}
            errors.extend(local_errors)
        else:
            result = backend.solve_one(obligation)
        solve_results.append(result)
        if result.get("status") == "sat":
            covered = backend.evaluate_model_coverage(result.get("model") or {}, obligations)
            if oid not in covered:
                covered.append(oid)
            candidates.append(build_candidate(obligation, result, sorted(dict.fromkeys(covered))))
        elif result.get("status") == "unsat":
            unsat.append(_unsat_entry(obligation, result))
        elif result.get("status") == "unknown":
            unknown.append(_unknown_entry(obligation, result))
        elif result.get("status") == "error":
            errors.append({"code": result.get("code") or "OBLIGATION_SOLVE_ERROR", "obligation_id": oid, "message": result.get("reason", "")})
    _emit_solve_running(progress, len(solve_results), len(obligations), candidates, unsat, unknown, errors, batch_round=0, fallback_pending=0)
    return {"solve_results": solve_results, "candidates": candidates, "unsat": unsat, "unknown": unknown, "errors": errors}


def _solve_fallback_items(ir: dict[str, Any], items: list[dict[str, Any]], *, timeout_ms: int, jobs: int) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if jobs <= 1 or len(items) <= 1:
        backend = Z3Backend(ir, SolveConfig(timeout_ms=timeout_ms))
        return [(item, backend.solve_expr(item["expr"], label=f"fallback:{item['id']}", obligation_id=item["id"])) for item in items]

    def worker(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        local_backend = Z3Backend(ir, SolveConfig(timeout_ms=timeout_ms))
        return item, local_backend.solve_expr(item["expr"], label=f"fallback:{item['id']}", obligation_id=item["id"])

    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = [executor.submit(worker, item) for item in items]
        for future in as_completed(futures):
            out.append(future.result())
    return out


def _record_sat_candidate(
    source_item: dict[str, Any],
    result: dict[str, Any],
    covered_ids: list[str],
    pending_ids: set[str],
    result_by_id: dict[str, dict[str, Any]],
    candidates: list[dict[str, Any]],
    obligation_by_id: dict[str, dict[str, Any]],
) -> None:
    covered = sorted(dict.fromkeys(oid for oid in covered_ids if oid in pending_ids or oid == source_item["id"]))
    if not covered:
        return
    candidate = build_candidate(source_item["obligation"], result, covered)
    candidate["source_obligation_ids"] = covered
    keep_full_model_for_all = len(covered) <= 20
    for oid in covered:
        obligation = obligation_by_id.get(oid, source_item["obligation"])
        full_model = result.get("model") or {}
        result_by_id[oid] = {
            "obligation_id": oid,
            "status": "sat",
            "model": full_model if keep_full_model_for_all or oid == source_item["id"] else {},
            "model_ref": candidate["id"] if not keep_full_model_for_all and oid != source_item["id"] else "",
            "unsat_core": [],
            "reason": "" if keep_full_model_for_all or oid == source_item["id"] else "covered by batch candidate model_ref",
        }
        pending_ids.discard(oid)
    candidates.append(candidate)


def _build_coverage_index(prepared: list[dict[str, Any]]) -> dict[str, Any]:
    by_assignment: dict[tuple[str, tuple[str, Any]], list[str]] = {}
    complex_items: list[dict[str, Any]] = []
    obligation_by_id = {item["id"]: item["obligation"] for item in prepared}
    for item in prepared:
        assignments = item.get("assignments") or []
        if len(assignments) == 1:
            var_id, value = assignments[0]
            by_assignment.setdefault((var_id, _literal_key(value)), []).append(item["id"])
        else:
            complex_items.append(item)
    return {"by_assignment": by_assignment, "complex_items": complex_items, "obligation_by_id": obligation_by_id}


def _covered_ids_from_model(
    backend: Z3Backend,
    model: dict[str, Any],
    index: dict[str, Any],
    prepared: list[dict[str, Any]],
    allowed_ids: set[str],
) -> list[str]:
    covered: set[str] = set()
    by_assignment = index["by_assignment"]
    for var_id, value in model.items():
        for oid in by_assignment.get((str(var_id), _literal_key(value)), []):
            if oid in allowed_ids:
                covered.add(oid)
    for item in index["complex_items"]:
        oid = item["id"]
        if oid not in allowed_ids:
            continue
        fast = backend.fast_model_satisfies(model, item["expr"])
        if fast is True:
            covered.add(oid)
        elif fast is None and backend.model_satisfies(model, item["expr"]):
            covered.add(oid)
    return sorted(covered)


def _next_compatible_batch(items: list[dict[str, Any]], pending_ids: set[str], batch_size: int) -> list[dict[str, Any]]:
    group: list[dict[str, Any]] = []
    assignments: dict[str, tuple[str, Any]] = {}
    for item in items:
        if item["id"] not in pending_ids:
            continue
        if _compatible_assignments(assignments, item["assignments"]):
            group.append(item)
            for var_id, value in item["assignments"]:
                assignments[var_id] = _literal_key(value)
        if len(group) >= batch_size:
            break
    return group


def _compatible_assignments(existing: dict[str, tuple[str, Any]], assignments: list[tuple[str, Any]]) -> bool:
    for var_id, value in assignments:
        key = _literal_key(value)
        if var_id in existing and existing[var_id] != key:
            return False
    return True


def _extract_eq_assignments(expr: Any) -> list[tuple[str, Any]]:
    if not isinstance(expr, dict):
        return []
    op = expr.get("op")
    if op == "eq" and "var" in expr and "value" in expr:
        return [(str(expr["var"]), expr.get("value"))]
    if op == "and":
        out: list[tuple[str, Any]] = []
        for arg in expr.get("args") or []:
            assignments = _extract_eq_assignments(arg)
            if not assignments:
                return []
            out.extend(assignments)
        return out
    return []


def _batch_expr(items: list[dict[str, Any]]) -> dict[str, Any]:
    if len(items) == 1:
        return items[0]["expr"]
    return {"op": "and", "args": [item["expr"] for item in items]}


def _literal_key(value: Any) -> tuple[str, Any]:
    if isinstance(value, bool):
        return ("bool", bool(value))
    if isinstance(value, int):
        return ("int", int(value))
    return ("str", str(value))


def _unsat_entry(obligation: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "obligation_id": result["obligation_id"],
        "kind": obligation.get("kind"),
        "priority": obligation.get("priority"),
        "target_refs": obligation.get("target_refs") or [],
        "unsat_core": result.get("unsat_core") or [],
        "reason": result.get("reason") or "unsat",
    }


def _unknown_entry(obligation: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "obligation_id": result["obligation_id"],
        "kind": obligation.get("kind"),
        "priority": obligation.get("priority"),
        "reason": result.get("reason") or "unknown",
    }


def _emit_solve_running(
    progress: ProgressCallback | None,
    solved: int,
    total: int,
    candidates: list[dict[str, Any]],
    unsat: list[dict[str, Any]],
    unknown: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    *,
    batch_round: int,
    fallback_pending: int,
) -> None:
    _emit_progress(
        progress,
        stage="solve",
        status="running",
        solved=solved,
        total_obligations=total,
        sat=sum(len(item.get("covered_obligation_ids") or []) for item in candidates),
        unsat=len(unsat),
        unknown=len(unknown),
        errors=len(errors),
        raw_candidates=len(candidates),
        batch_round=batch_round,
        fallback_pending=fallback_pending,
    )


def write_solve_outputs(solve_root: Path, result: dict[str, Any]) -> None:
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
    if result.get("realize_report"):
        write_yaml(solve_root / "realize_report.yaml", result["realize_report"])
    if result.get("realization_report"):
        write_yaml(solve_root / "realization_report.yaml", result["realization_report"])


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
        "# TestAgent 求解报告",
        "",
        f"- 总 Obligation 数: {len(obligations)}",
        f"- SAT / UNSAT / UNKNOWN / SKIPPED 数: {counts['sat']} / {counts['unsat']} / {counts['unknown']} / {counts['skipped']}",
        f"- 原始候选数: {len(raw_candidates)}",
        f"- 去重后候选数: {len(deduped_candidates)}",
        f"- Set Cover 后候选数: {len(selected['selected_candidates'])}",
        f"- 未覆盖 Hard Obligation: {len(uncovered_hard)}",
        f"- UNSAT 原因摘要: {', '.join(_summarize_unsat(unsat)) if unsat else '无'}",
        f"- Contract 中无法编译的表达式: {len(errors)}",
        "",
        "求解完成后写出 cases CSV（可用 --dry-run 跳过）。CSV 行由 VAR_CSV_* 模型投影生成。",
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


def _require_approval(supplement: dict[str, Any], snapshot_hash: str | None, plan_hash: str | None, unresolved: dict[str, Any]) -> None:
    required = {"decision", "approved_snapshot_hash", "approved_plan_hash", "approved_at", "supplements", "notes"}
    missing = sorted(key for key in required if key not in supplement)
    if missing:
        raise TgSolveError(f"APPROVAL_REQUIRED: approval file missing field(s): {', '.join(missing)}")
    decision = str(supplement.get("decision") or supplement.get("approval") or "").strip().lower()
    status = str(supplement.get("status") or "").strip().lower()
    approved = supplement.get("approved") is True
    if decision != "approve" and status not in {"approved", "approve"} and not approved:
        raise TgSolveError("APPROVAL_REQUIRED: plan approval is required before tg-solve")
    if supplement.get("approved_snapshot_hash") != snapshot_hash:
        raise TgSolveError("APPROVAL_SNAPSHOT_MISMATCH: approval does not match current snapshot_hash")
    if supplement.get("approved_plan_hash") != plan_hash:
        raise TgSolveError("APPROVAL_PLAN_MISMATCH: approval does not match current plan_hash")
    blocking = unresolved.get("blocking_hard_obligations") or []
    gaps = unresolved.get("contract_gaps") or []
    if unresolved.get("status") != "ready_for_manual_review" or blocking:
        raise TgSolveError("PLAN_BLOCKED: unresolved hard blockers must be cleared before tg-solve")
    if gaps:
        raise TgSolveError("CONTRACT_GAPS_PRESENT: contract gaps must be resolved before tg-solve")


def _summarize_unsat(unsat: list[dict[str, Any]]) -> list[str]:
    out = []
    for item in unsat[:5]:
        core = item.get("unsat_core") or []
        out.append(f"{item.get('obligation_id')}: {', '.join(core) if core else item.get('reason', 'unsat')}")
    return out


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _emit_progress(progress: ProgressCallback | None, **event: Any) -> None:
    if progress is None:
        return
    progress({"time": _now(), **event})
