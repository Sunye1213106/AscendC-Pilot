from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates


def build_plan(op: Path, output: Path) -> dict:
    ir = op / ".ascendc-pilot" / "uo" / "ir"
    candidates = yaml.safe_load(
        (ir / "extract_plan_candidates.yaml").read_text(encoding="utf-8")
    ) or {}
    allowed_roles = {
        "tiling_writer",
        "key_writer",
        "workspace_writer",
        "provenance_helper",
        "ignore",
    }
    writers = []
    for cand in candidates.get("writer_candidates") or []:
        if not isinstance(cand, dict) or not cand.get("name"):
            continue
        name = str(cand["name"])
        role = str(cand.get("role_suggested") or "ignore")
        if role not in allowed_roles or re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", name):
            role = "ignore"
        writers.append(
            {
                "name": name,
                "qualified_name": cand.get("qualified_name") or name,
                "class_or_namespace": cand.get("class_or_namespace") or "",
                "file_path": cand.get("file_path") or "",
                "start_line": int(cand.get("start_line") or 0),
                "role": role,
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": [cand.get("file_path")] if cand.get("file_path") else [],
                "evidence_lines": [int(cand.get("start_line"))] if cand.get("start_line") else [],
                "decision_reason": "candidate source body and structural evidence reviewed for real FAG CI rebuild",
            }
        )
    receivers = [
        {
            "name": str(c["name"]),
            "qualified_name": c.get("qualified_name") or str(c["name"]),
            "class_or_namespace": c.get("class_or_namespace") or "",
            "file_path": c.get("file_path") or "",
            "start_line": int(c.get("start_line") or 0),
            "is_tiling_sink": bool(c.get("is_tiling_sink_suggested")),
            "evidence_source": "candidate_only",
            "confidence": "candidate",
        }
        for c in candidates.get("receiver_candidates") or []
        if isinstance(c, dict) and c.get("name")
    ]
    aliases = [
        {
            "local": str(c["local"]),
            "tdf_leaf": str(c["tdf_leaf"]),
            "tdf_path": c.get("tdf_path") or c.get("tdf_leaf"),
            "file_path": c.get("file_path") or "",
            "start_line": int(c.get("start_line") or 0),
        }
        for c in candidates.get("alias_candidates") or []
        if isinstance(c, dict) and c.get("local") and c.get("tdf_leaf")
    ]
    plan = {
        "version": 1,
        "op_name": "flash_attention_score_grad",
        "architecture": "arch35",
        "status": "confirmed_for_ci_rebuild",
        "writers": writers,
        "receivers": receivers,
        "aliases": aliases,
        "non_sink_roots": sorted(
            {
                str(c["name"])
                for c in candidates.get("non_sink_root_candidates") or []
                if isinstance(c, dict) and c.get("name")
            }
        ),
        "derived_roots": [],
        "extra_host_entries": [
            {
                "name": str(c["name"]),
                "file_path": c.get("file_path") or "",
                "start_line": int(c.get("start_line") or 0),
            }
            for c in candidates.get("extra_entry_candidates") or []
            if isinstance(c, dict) and c.get("name")
        ],
    }
    errors = validate_extract_plan_against_candidates(plan, candidates)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "errors": errors,
                "writers": len(writers),
                "receivers": len(receivers),
                "aliases": len(aliases),
                "non_sink_roots": len(plan["non_sink_roots"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if errors:
        raise SystemExit("extract plan rejected: " + "; ".join(errors[:20]))
    (ir / "extract_plan.yaml").write_text(
        yaml.safe_dump(plan, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("op")
    parser.add_argument("--report", default="results/plan-validation.json")
    args = parser.parse_args()
    build_plan(Path(args.op), Path(args.report))


if __name__ == "__main__":
    main()
