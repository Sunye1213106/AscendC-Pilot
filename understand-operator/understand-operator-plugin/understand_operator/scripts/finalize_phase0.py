from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
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
from understand_operator._operator.spec import spec_bundle_hash


def finalize_phase0(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    manifest = _load_yaml(uo_root / "manifest.yaml")
    run_id = manifest.get("current_run_id") if isinstance(manifest, dict) else None
    if not isinstance(run_id, str) or not run_id.startswith("UO_RUN_") or run_id == "UO_RUN_PENDING":
        return 2, ["manifest.yaml.current_run_id is not active"]
    phase0 = uo_root / "runs" / run_id / "phase0"
    docs = {
        "context": _load_yaml(phase0 / "context.yaml"),
        "installed_skill_check": _load_yaml(phase0 / "installed_skill_check.yaml"),
        "scope_scan": _load_yaml(phase0 / "scope_scan.yaml"),
        "semantic_enrichment": _load_yaml(phase0 / "semantic_enrichment.yaml"),
        "scope_review": _load_yaml(phase0 / "scope_review.yaml"),
    }
    errors = _validation_errors(repo_root, uo_root, docs)
    if errors:
        return 2, errors

    context = _item_data(docs["context"])
    cbm_meta = _load_json(uo_root / "cbm" / "index_meta.json")
    scan = docs["scope_scan"]
    review = docs["scope_review"]
    files = scan.get("files") if isinstance(scan.get("files"), dict) else {}
    approved = review.get("approved_scope") if isinstance(review.get("approved_scope"), dict) else {}
    def scoped(key: str) -> Any:
        return approved[key] if key in approved else files.get(key, [])

    receipt = {
        "version": 1,
        "artifact": {"type": "runs.receipt", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": {
            "run_id": run_id,
            "source_snapshot_id": context.get("source_snapshot_id") or (scan.get("snapshot") or {}).get("source_snapshot_id") or "SOURCE_PHASE0",
            "source_revision": context.get("source_revision") or (scan.get("snapshot") or {}).get("source_revision") or "unknown",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "status": "pass",
        "finalized_at": datetime.now(tz=timezone.utc).isoformat(),
        "frozen_scope": {
            "approved_initial_files": scoped("initial_operator_files"),
            "approved_dependency_files": scoped("dependency_files"),
            "approved_include": approved.get("approved_include") or [],
            "approved_exclude": scoped("excluded_files"),
            "architecture_variants": approved["architecture_variants"] if "architecture_variants" in approved else scan.get("architecture_variants", []),
            "unresolved_dependencies": scoped("uncertain_files"),
            "operator_roots": approved["operator_roots"] if "operator_roots" in approved else scan.get("operator_roots", []),
            "include_search_paths": approved["include_search_paths"] if "include_search_paths" in approved else scan.get("include_search_paths", []),
        },
        "cbm_project": cbm_meta.get("cbm_project"),
        "cbm_mode": cbm_meta.get("cbm_mode"),
        "cbm": {
            "repo_root": cbm_meta.get("repo_root"),
            "op_name": cbm_meta.get("op_name"),
            "cbm_project": cbm_meta.get("cbm_project"),
            "indexed_via": cbm_meta.get("indexed_via"),
            "cbm_mode": cbm_meta.get("cbm_mode"),
            "indexed_at": cbm_meta.get("indexed_at"),
            "project_confirmed": cbm_meta.get("project_confirmed"),
        },
        "source_revision": context.get("source_revision"),
        "source_snapshot_id": context.get("source_snapshot_id"),
        "spec_bundle_hash": spec_bundle_hash(),
        "input_hashes": _phase0_input_hashes(uo_root, phase0, run_id),
        "items": [
            {
                "id": "OP_PHASE0_RECEIPT",
                "kind": "phase0_receipt",
                "status": "recorded",
                "source_revision": context.get("source_revision"),
                "source_snapshot_id": context.get("source_snapshot_id"),
                "cbm_project": cbm_meta.get("cbm_project"),
                "spec_bundle_hash": spec_bundle_hash(),
            }
        ],
        "relations": [],
        "unresolved": [],
    }
    out = phase0 / "receipt.yaml"
    out.write_text(yaml.safe_dump(receipt, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return 0, [f"wrote {out}"]


def _validation_errors(repo_root: Path, uo_root: Path, docs: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    context = _item_data(docs["context"])
    skill = _item_data(docs["installed_skill_check"])
    cbm_meta = _load_json(uo_root / "cbm" / "index_meta.json")
    if skill.get("consistent") is not True:
        errors.append("installed_skill_check.consistent is not true")
    if not cbm_meta.get("cbm_project"):
        errors.append("cbm/index_meta.json missing cbm_project")
    if cbm_meta.get("indexed_via") != "mcp":
        errors.append("cbm/index_meta.json indexed_via must be mcp")
    if not cbm_meta.get("indexed_at"):
        errors.append("cbm/index_meta.json missing indexed_at")
    if cbm_meta.get("repo_root") and Path(str(cbm_meta["repo_root"])).resolve() != repo_root:
        errors.append("cbm/index_meta.json repo_root does not match current repository")
    if cbm_meta.get("op_name") and cbm_meta.get("op_name") != (uo_root.name):
        errors.append("cbm/index_meta.json op_name does not match operator root")
    if cbm_meta.get("project_confirmed") is False:
        errors.append("cbm/index_meta.json project_confirmed is false")
    if _doc_status(docs["scope_scan"]) != "complete":
        errors.append("scope_scan.yaml status is not complete")
    if _doc_status(docs["semantic_enrichment"]) != "complete":
        errors.append("semantic_enrichment.yaml status is not complete")
    _validate_semantic_enrichment(docs["semantic_enrichment"], errors)
    if docs["scope_review"].get("decision") != "continue":
        errors.append("scope_review.yaml decision is not continue")
    _validate_scope_sets(docs["scope_review"], errors)
    expected_revision = context.get("source_revision") or (docs["scope_scan"].get("snapshot") or {}).get("source_revision")
    current_revision = _git_revision(repo_root)
    if expected_revision and expected_revision != "unknown" and current_revision != expected_revision:
        errors.append(f"source revision changed: receipt expects {expected_revision}, current {current_revision}")
    expected_spec = context.get("spec_bundle_hash") or (docs["scope_scan"].get("snapshot") or {}).get("spec_bundle_hash")
    if expected_spec != spec_bundle_hash():
        errors.append("spec bundle hash changed")
    return errors


def _validate_scope_sets(scope_review: dict[str, Any], errors: list[str]) -> None:
    approved = scope_review.get("approved_scope") if isinstance(scope_review.get("approved_scope"), dict) else {}
    groups = {
        "initial_operator_files": approved.get("initial_operator_files") or [],
        "dependency_files": approved.get("dependency_files") or [],
        "generated_files": approved.get("generated_files") or [],
        "excluded_files": approved.get("excluded_files") or [],
        "uncertain_files": approved.get("uncertain_files") or [],
    }
    owner_by_path: dict[str, str] = {}
    for group, items in groups.items():
        for item in items:
            path = str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/")
            if not path:
                continue
            previous = owner_by_path.get(path)
            if previous and previous != group:
                errors.append(f"scope_review.yaml path appears in multiple scope sets: {path} ({previous}, {group})")
            owner_by_path[path] = group


def _validate_semantic_enrichment(doc: dict[str, Any], errors: list[str]) -> None:
    data = _item_data(doc)
    records = data.get("cbm_queries") or doc.get("cbm_queries")
    unresolved = doc.get("unresolved") if isinstance(doc.get("unresolved"), list) else []
    if not isinstance(records, list):
        errors.append("semantic_enrichment.yaml missing cbm_queries list")
        return
    if not records and not unresolved:
        errors.append("semantic_enrichment.yaml must record cbm_queries or unresolved semantic gaps")
        return
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"semantic_enrichment.yaml cbm_queries[{index}] must be a mapping")
            continue
        for key in ("tool", "payload", "candidate", "result_summary", "confidence", "fallback_used"):
            if key not in record:
                errors.append(f"semantic_enrichment.yaml cbm_queries[{index}] missing {key}")


def _doc_status(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("status"), str):
        return str(doc["status"])
    data = _item_data(doc)
    return str(data.get("status") or "")


def _item_data(doc: dict[str, Any]) -> dict[str, Any]:
    for item in doc.get("items") or []:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            return item["data"]
    return {}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _git_revision(repo_root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True)
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _phase0_input_hashes(uo_root: Path, phase0: Path, run_id: str) -> dict[str, str]:
    candidates = {
        "manifest.yaml": uo_root / "manifest.yaml",
        f"runs/{run_id}/phase0/context.yaml": phase0 / "context.yaml",
        f"runs/{run_id}/phase0/installed_skill_check.yaml": phase0 / "installed_skill_check.yaml",
        f"runs/{run_id}/phase0/ignore_rules.yaml": phase0 / "ignore_rules.yaml",
        f"runs/{run_id}/phase0/scope_scan.yaml": phase0 / "scope_scan.yaml",
        f"runs/{run_id}/phase0/semantic_enrichment.yaml": phase0 / "semantic_enrichment.yaml",
        f"runs/{run_id}/phase0/scope_review.yaml": phase0 / "scope_review.yaml",
        "cbm/index_meta.json": uo_root / "cbm" / "index_meta.json",
    }
    return {rel: _sha256_file(path) for rel, path in candidates.items() if path.exists()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finalize Phase 0 and write the only pass receipt.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = finalize_phase0(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
