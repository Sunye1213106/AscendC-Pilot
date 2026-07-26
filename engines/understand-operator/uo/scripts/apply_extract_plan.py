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
    out_plan_path = Path(plan_path) if plan_path else (uo_root / "ir" / "extract_plan.yaml")
    if plan is None:
        if not out_plan_path.is_file():
            return {
                "ok": False,
                "rejected_count": 1,
                "rejected": [{"reason": f"extract_plan missing: {out_plan_path}"}],
            }
        plan = read_yaml(out_plan_path)
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

    cand_doc = candidates if isinstance(candidates, dict) else {}
    plan = normalize_plan_from_candidates(plan, cand_doc)
    # Product resilience: backfill contiguous snippet + sha from disk / candidate
    # source_window (same spirit as prior sha-only enrich). Collage `...` is replaced.
    enrich_stats = _enrich_evidence(plan, repo_root, cand_doc)
    # Drop invented non_sink string names before validate (allowlist-only).
    drop_tags = drop_invented_non_sink_roots(plan, cand_doc)
    if drop_tags:
        enrich_stats["items"] = int(enrich_stats.get("items") or 0) + 1
        acts = list(enrich_stats.get("actions") or [])
        acts.extend(drop_tags)
        enrich_stats["actions"] = acts

    errors = validate_extract_plan_against_candidates(
        plan, cand_doc, project_root=repo_root
    )
    buckets = bucket_extract_plan_errors(errors)
    # Persist evidence enrichments even when other contract fields still fail,
    # so rework does not keep burning retries on collage snippets.
    if enrich_stats.get("items") and not check_only:
        write_yaml(out_plan_path, plan)

    if errors:
        if not check_only:
            _write_rework_hints(uo_root, buckets, enrich_stats)
        return {
            "ok": False,
            "rejected_count": int(buckets.get("unique_count") or len(errors)),
            "rejected_raw_count": len(errors),
            "rejected": [{"reason": e} for e in (buckets.get("unique_errors") or errors)[:40]],
            "rejected_buckets": buckets,
            "enriched": enrich_stats,
            "message_zh": (
                f"extract_plan 校验失败（{buckets.get('summary') or 'errors'}）；"
                "请 resume 原子代理修复 alias/non_sink 等合同项；"
                "证据拼贴已尝试从磁盘回填"
            ),
        }

    result = {
        "ok": True,
        "rejected_count": 0,
        "rejected": [],
        "writers": len(plan.get("writers") or []),
        "receivers": len(plan.get("receivers") or []),
        "aliases": len(plan.get("aliases") or []),
        "enriched": enrich_stats,
    }
    if not check_only:
        write_yaml(out_plan_path, plan)
        result["written"] = str(out_plan_path)
        hints = uo_root / "ir" / "extract_plan.rework_hints.yaml"
        if hints.is_file():
            try:
                hints.unlink()
            except OSError:
                pass
    return result


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
                "summary": buckets.get("summary") or "",
                "unique_errors": buckets.get("unique_errors") or [],
                "enriched": enrich_stats,
                "fix_zh": (
                    "禁止只改 candidates_sha256。证据：拷候选 source_window.text 或磁盘连续窗"
                    "（禁 ...）。aliases 必须 local+tdf_leaf。不确定的 non_sink omit。"
                    "Host：子代理若称只改 sha / 未改证据 → 禁止 finalize，继续 resume。"
                ),
            },
        )
    except OSError:
        pass


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
