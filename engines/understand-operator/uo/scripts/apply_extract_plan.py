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
from uo.scripts.extract_plan_autofill import (
    auto_merge_high_confidence_aliases,
    merge_receiver_bindings_into_plan,
    stamp_candidate_ids,
)
from uo.scripts.extract_plan_decision import (
    assert_canonical_plan_slim,
    build_decision_worklist,
    file_sha256_bytes,
    is_decision_report,
    materialize_plan_from_decision_report,
    slim_extract_plan,
    validate_extract_plan_staging,
)
from uo.scripts.extract_plan_io import (
    _match_candidate,
    drop_invented_non_sink_roots,
    normalize_plan_from_candidates,
    validate_extract_plan_against_candidates,
)
from uo.scripts.source_evidence import (
    bucket_extract_plan_errors,
    enrich_item_evidence_from_disk,
)


def apply_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    plan: dict[str, Any] | None = None,
    plan_path: Path | None = None,
    staging_path: Path | None = None,
    check_only: bool = False,
    worklist_path: Path | None = None,
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
    if isinstance(candidates, dict):
        stamp_candidate_ids(candidates)

    canonical_path = Path(plan_path) if plan_path else (uo_root / "ir" / "extract_plan.yaml")
    stage = Path(staging_path) if staging_path else None
    decision_report: dict[str, Any] | None = None
    worklist: dict[str, Any] | None = None

    # Prefer decision_report.yaml; fall back to legacy staging/output.yaml.
    if plan is None and stage is not None:
        report_path = stage.parent / "decision_report.yaml"
        if report_path.is_file():
            loaded = read_yaml(report_path)
            if isinstance(loaded, dict) and is_decision_report(loaded):
                decision_report = loaded
        if decision_report is None and stage.is_file():
            loaded = read_yaml(stage)
            if isinstance(loaded, dict) and is_decision_report(loaded):
                decision_report = loaded
                plan = None
            elif isinstance(loaded, dict):
                plan = loaded

    if plan is None and decision_report is None:
        read_path = None
        if stage is not None and stage.is_file():
            read_path = stage
        elif canonical_path.is_file():
            read_path = canonical_path
        if read_path is None:
            return {
                "ok": False,
                "rejected_count": 1,
                "rejected": [{"reason": f"extract_plan missing: staging or {canonical_path}"}],
            }
        plan = read_yaml(read_path)

    # Load worklist for coverage / architecture gates.
    wl_path = worklist_path
    if wl_path is None and stage is not None:
        cand = stage.parent.parent / "inputs" / "decision_worklist.yaml"
        if cand.is_file():
            wl_path = cand
    if wl_path is not None and Path(wl_path).is_file():
        loaded_wl = read_yaml(Path(wl_path))
        if isinstance(loaded_wl, dict):
            worklist = loaded_wl
    if worklist is None and isinstance(candidates, dict):
        worklist = build_decision_worklist(
            candidates,
            architecture=str((candidates or {}).get("architecture") or ""),
        )

    cand_doc = candidates if isinstance(candidates, dict) else {}

    if decision_report is not None:
        identity = {
            "actor_id": decision_report.get("actor_id"),
            "run_id": decision_report.get("run_id"),
            "workflow_id": decision_report.get("workflow_id"),
            "candidates_sha256": decision_report.get("candidates_sha256"),
            "architecture": decision_report.get("architecture")
            or cand_doc.get("architecture"),
        }
        plan = materialize_plan_from_decision_report(
            decision_report, cand_doc, identity=identity
        )

    if not isinstance(plan, dict):
        return {"ok": False, "rejected_count": 1, "rejected": [{"reason": "plan not a mapping"}]}

    plan.setdefault("version", 1)
    plan.setdefault("confirmed_by", "llm")
    plan.setdefault("writers", [])
    plan.setdefault("receivers", [])
    plan.setdefault("aliases", [])
    plan.setdefault("non_sink_roots", [])
    plan.setdefault("extra_host_entries", [])
    plan.setdefault("derived_roots", [])
    plan.setdefault("receiver_bindings", [])
    plan.setdefault("accepted_candidates", [])
    plan.setdefault("rejected_candidates", [])
    plan.setdefault("deferred_candidates", [])
    if not plan.get("architecture"):
        plan["architecture"] = cand_doc.get("architecture")

    # Staging Gate (schema / coverage / architecture / role evidence).
    staging_errs = validate_extract_plan_staging(
        report=decision_report,
        worklist=worklist,
        plan=plan,
        candidates=cand_doc,
        project_root=repo_root,
    )

    plan = normalize_plan_from_candidates(plan, cand_doc)

    auto_report: dict[str, Any] = {"alias": {}, "receiver_bindings": {}}
    auto_report["alias"] = auto_merge_high_confidence_aliases(
        plan, cand_doc, project_root=repo_root
    )
    auto_report["receiver_bindings"] = merge_receiver_bindings_into_plan(plan, cand_doc)

    enrich_stats = _enrich_evidence(plan, repo_root, cand_doc)
    drop_tags = drop_invented_non_sink_roots(plan, cand_doc)
    if drop_tags:
        enrich_stats["items"] = int(enrich_stats.get("items") or 0) + 1
        acts = list(enrich_stats.get("actions") or [])
        acts.extend(drop_tags)
        enrich_stats["actions"] = acts

    errors = list(staging_errs)
    errors.extend(
        validate_extract_plan_against_candidates(
            plan, cand_doc, project_root=repo_root
        )
    )
    buckets = bucket_extract_plan_errors(errors)
    partial_path = stage if stage is not None else canonical_path
    if enrich_stats.get("items") and not check_only and stage is not None:
        # Keep pre-slim materialization in staging for rework; never write audit blobs to canonical early.
        write_yaml(partial_path, plan)

    if errors:
        if not check_only:
            _write_rework_hints(uo_root, buckets, enrich_stats)
            _write_auto_fill_report(uo_root, auto_report, ok=False)
        return {
            "ok": False,
            "rejected_count": int(buckets.get("unique_count") or len(errors)),
            "rejected_raw_count": len(errors),
            "rejected": [{"reason": e} for e in (buckets.get("unique_errors") or errors)[:40]],
            "rejected_buckets": buckets,
            "enriched": enrich_stats,
            "auto_fill": auto_report,
            "message_zh": (
                f"extract_plan 校验失败（{buckets.get('summary') or 'errors'}）；"
                "请 resume 原子代理修复 decision_report / coverage / evidence；"
                "证据拼贴已尝试从磁盘回填"
            ),
        }

    # Slim canonical IR + sidecars.
    aliases_rel = "extract_plan_aliases.yaml"
    bindings_rel = "receiver_bindings.yaml"
    slim, aliases_doc, bindings_doc = slim_extract_plan(
        plan, aliases_rel=aliases_rel, bindings_rel=bindings_rel
    )

    result = {
        "ok": True,
        "rejected_count": 0,
        "rejected": [],
        "writers": len(slim.get("writers") or []),
        "receivers": len(slim.get("receivers") or []),
        "aliases": len(aliases_doc.get("aliases") or {}),
        "receiver_bindings": len(bindings_doc.get("bindings") or {}),
        "enriched": enrich_stats,
        "auto_fill": auto_report,
        "slim": True,
    }
    if not check_only:
        ir = uo_root / "ir"
        write_yaml(ir / aliases_rel, aliases_doc)
        write_yaml(ir / bindings_rel, bindings_doc)
        a_sha = _sha_file(ir / aliases_rel)
        b_sha = _sha_file(ir / bindings_rel)
        slim["aliases_ref"] = {
            "path": aliases_rel,
            "sha256": a_sha,
            "count": len(aliases_doc.get("aliases") or {}),
        }
        slim["receiver_bindings_ref"] = {
            "path": bindings_rel,
            "sha256": b_sha,
            "count": len(bindings_doc.get("bindings") or {}),
        }
        slim_errs = assert_canonical_plan_slim(slim)
        if slim_errs:
            # Strip any residual audit keys then re-check.
            for k in ("accepted_candidates", "rejected_candidates", "deferred_candidates"):
                slim.pop(k, None)
            slim_errs = assert_canonical_plan_slim(slim)
        if slim_errs:
            _write_rework_hints(
                uo_root,
                bucket_extract_plan_errors(slim_errs),
                enrich_stats,
            )
            return {
                "ok": False,
                "rejected_count": len(slim_errs),
                "rejected": [{"reason": e} for e in slim_errs[:40]],
                "message_zh": "canonical extract_plan slim 失败",
            }
        write_yaml(canonical_path, slim)
        result["written"] = str(canonical_path)
        result["aliases_path"] = str(ir / aliases_rel)
        result["receiver_bindings_path"] = str(ir / bindings_rel)
        _write_auto_fill_report(uo_root, auto_report, ok=True)
        # Persist decision_report copy under ir for audit (not canonical plan).
        if decision_report is not None:
            try:
                write_yaml(ir / "extract_plan_decision_report.yaml", decision_report)
            except OSError:
                pass
        hints = ir / "extract_plan.rework_hints.yaml"
        if hints.is_file():
            try:
                hints.unlink()
            except OSError:
                pass
    return result


def _sha_file(path: Path) -> str:
    try:
        return file_sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def _write_auto_fill_report(uo_root: Path, auto_report: dict[str, Any], *, ok: bool) -> None:
    try:
        write_yaml(
            uo_root / "ir" / "extract_plan_auto_fill_report.yaml",
            {
                "version": 1,
                "ok": bool(ok),
                "auto_fill": auto_report,
            },
        )
    except OSError:
        pass


def _enrich_evidence(
    plan: dict[str, Any],
    repo_root: Path,
    candidates: dict[str, Any],
) -> dict[str, Any]:
    touched = 0
    tags: list[str] = []
    writer_pool = list(candidates.get("writer_candidates") or [])
    recv_pool = list(candidates.get("receiver_candidates") or [])
    for key, pool in (("writers", writer_pool), ("receivers", recv_pool)):
        for item in plan.get(key) or []:
            if not isinstance(item, dict):
                continue
            cand = _match_candidate(item, pool)
            acts = enrich_item_evidence_from_disk(repo_root, item, candidate=cand)
            if acts:
                touched += 1
                tags.extend(acts)
    return {"items": touched, "actions": tags}


def _write_rework_hints(
    uo_root: Path,
    buckets: dict[str, Any],
    enrich_stats: dict[str, Any],
) -> None:
    try:
        write_yaml(
            uo_root / "ir" / "extract_plan.rework_hints.yaml",
            {
                "version": 1,
                "kind": "extract_plan_rework_hints",
                "buckets": buckets.get("counts") or {},
                "unique_errors": (buckets.get("unique_errors") or [])[:40],
                "enrich": enrich_stats,
                "message_zh": (
                    "修复 staging/decision_report.yaml（coverage / role evidence / "
                    "architecture）；禁止把 evidence_snippet 写入 canonical extract_plan.yaml"
                ),
            },
        )
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply / validate extract_plan")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--staging", type=Path, default=None)
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    result = apply_extract_plan(
        repo_root,
        op_name,
        staging_path=args.staging,
        check_only=bool(args.check_only),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
