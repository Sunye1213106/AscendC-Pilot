from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.run_context import active_run_id, phase0_snapshot, read_yaml_mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produce Phase 0 semantic_enrichment.yaml from current scope scan and CBM metadata.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)

    if yaml is None:
        print("PyYAML is required", file=sys.stderr)
        return 2

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    run_id = active_run_id(uo_root)
    phase0 = uo_root / "runs" / run_id / "phase0"
    scan = read_yaml_mapping(phase0 / "scope_scan.yaml")
    if scan.get("status") != "complete":
        print("scope_scan.yaml must be complete before semantic_enrichment.py", file=sys.stderr)
        return 2

    cbm_meta = _read_json(uo_root / "cbm" / "index_meta.json")
    variants = _normalize_architecture_variants(scan.get("architecture_variants"))
    variant_names = [item["name"] for item in variants]
    cbm_available = _cbm_available(cbm_meta)
    fallback = "" if cbm_available else "filesystem_scan"
    warnings: list[str] = []
    unresolved: list[dict[str, Any]] = []
    cbm_queries: list[dict[str, Any]] = []

    if cbm_available:
        cbm_queries.append(
            {
                "tool": "index_status",
                "payload": {"cbm_project": cbm_meta.get("cbm_project")},
                "result_summary": {
                    "project_confirmed": bool(cbm_meta.get("project_confirmed")),
                    "indexed_scope_roots": cbm_meta.get("indexed_scope_roots") or scan.get("scope_roots") or [],
                    "cbm_mode": cbm_meta.get("cbm_mode") or "",
                },
                "fallback_used": True,
                "reason": "Local semantic_enrichment.py records CBM readiness; targeted MCP semantic lookups remain orchestrator-owned.",
            }
        )
        unresolved.append(
            {
                "kind": "mcp_semantic_queries_pending",
                "reason": "Targeted MCP semantic enrichment was not executed by the local fallback producer.",
                "cbm_project": cbm_meta.get("cbm_project") or "",
            }
        )
        warnings.append("semantic_enrichment.py used local degraded fallback; targeted MCP semantic queries remain pending.")
    else:
        unresolved.append(
            {
                "kind": "cbm_index_unavailable",
                "reason": "CBM project is unavailable or unconfirmed; semantic enrichment fell back to filesystem evidence only.",
            }
        )
        warnings.append("semantic_enrichment.py ran without a confirmed CBM project and recorded degraded filesystem-only semantics.")

    payload = {
        "version": 1,
        "artifact": {"type": "runs.semantic_enrichment", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": phase0_snapshot(uo_root, run_id),
        "status": "degraded",
        "architecture_filter": {"included": variant_names, "excluded": []},
        "cbm_queries": cbm_queries,
        "architecture_variants": variants,
        "excluded_architectures": [],
        "confirmed_scope_additions": [],
        "unresolved": unresolved,
        "warnings": warnings,
        "fallback": fallback,
    }
    out_path = phase0 / "semantic_enrichment.yaml"
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def _normalize_architecture_variants(raw: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return result
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result.append(
            {
                "name": name,
                "matched_paths": list(item.get("matched_paths") or []),
                "semantic_status": str(item.get("semantic_status") or "candidate"),
                "cbm_evidence": list(item.get("cbm_evidence") or []),
            }
        )
    return result


def _cbm_available(cbm_meta: dict[str, Any]) -> bool:
    status = cbm_meta.get("cbm_status") if isinstance(cbm_meta.get("cbm_status"), dict) else {}
    if "available" in status:
        return bool(status.get("available"))
    return bool(cbm_meta.get("cbm_project")) and cbm_meta.get("project_confirmed") is not False


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
