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

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo._operator.run_context import active_run_id, scope_snapshot
from uo._operator.spec import spec_bundle_hash


def finalize_scope(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    try:
        run_id = active_run_id(uo_root)
    except RuntimeError as exc:
        return 2, [str(exc)]
    phase0 = uo_root / "runs" / run_id / "scope"
    docs = {
        "context": _load_yaml(phase0 / "context.yaml"),
        "installed_skill_check": _load_yaml(phase0 / "installed_skill_check.yaml"),
        "scope_scan": _load_yaml(phase0 / "scope_scan.yaml"),
        "semantic_enrichment": _load_yaml(phase0 / "semantic_enrichment.yaml"),
        "scope_review": _load_yaml(phase0 / "scope_review.yaml"),
        "scope_confirmed": _load_yaml(phase0 / "scope_confirmed.yaml"),
    }
    errors = _validation_errors(repo_root, uo_root, docs, op_name=op_name)
    if errors:
        return 2, errors

    context = _item_data(docs["context"])
    expected_op = str(context.get("op_name") or op_name or "").strip() or safe_op_name(None, repo_root)
    cbm_meta = _load_json(uo_root / "cbm" / "index_meta.json")
    scan = docs["scope_scan"]
    review = docs["scope_review"]
    confirmed = docs["scope_confirmed"] or _scope_confirmed_from_review(
        uo_root, run_id, review, operator=expected_op
    )
    if isinstance(confirmed, dict):
        confirmed["run_id"] = run_id
        confirmed["workflow_id"] = str(confirmed.get("workflow_id") or "uo-init")
        confirmed["action_id"] = "scope_confirmation"
        if str(confirmed.get("status") or "").strip().lower() not in {"confirmed", "empty"}:
            confirmed["status"] = "confirmed" if _confirmed_files(confirmed) else "empty"
        (phase0 / "scope_confirmed.yaml").write_text(
            yaml.safe_dump(confirmed, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    files = scan.get("files") if isinstance(scan.get("files"), dict) else {}
    approved = review.get("approved_scope") if isinstance(review.get("approved_scope"), dict) else {}
    def scoped(key: str) -> Any:
        return approved[key] if key in approved else files.get(key, [])

    source = _source_block(repo_root, scan)
    _update_manifest_source(uo_root, source, context, run_id)

    receipt = {
        "version": 1,
        "artifact": {"type": "runs.receipt", "schema_version": 1, "owner": "deterministic-uo-engine"},
        # Top-level identity so run-action --finalize contract check passes before
        # pilot-finalizer stamps artifact_identity (avoids ARTIFACT_IDENTITY_MISSING deadlock).
        "run_id": run_id,
        "workflow_id": "uo-init",
        "phase": "scope",
        "action_id": "scope_confirmation",
        "snapshot": scope_snapshot(uo_root, run_id),
        "status": "pass",
        "source": source,
        "finalized_at": datetime.now(tz=timezone.utc).isoformat(),
        "frozen_scope": {
            "approved_initial_files": scoped("initial_operator_files"),
            "approved_dependency_files": scoped("dependency_files"),
            "approved_include": approved.get("approved_include") or [],
            "approved_exclude": scoped("excluded_files"),
            "architecture_variants": approved["architecture_variants"] if "architecture_variants" in approved else scan.get("architecture_variants", []),
            "unresolved_dependencies": scoped("uncertain_files"),
            "operator_roots": approved["operator_roots"] if "operator_roots" in approved else scan.get("operator_roots", []),
            "scope_roots": approved["scope_roots"] if "scope_roots" in approved else scan.get("scope_roots", []),
            "dependency_roots": approved["dependency_roots"] if "dependency_roots" in approved else scan.get("dependency_roots", []),
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
            "indexed_scope_roots": cbm_meta.get("indexed_scope_roots") or scan.get("scope_roots") or [],
            "indexed_files": cbm_meta.get("indexed_files") or confirmed.get("confirmed_file_list") or [],
            "index_input": cbm_meta.get("index_input") or "confirmed_file_list",
            "cbm_status": cbm_meta.get("cbm_status") or _default_cbm_status(cbm_meta),
        },
        "source_revision": context.get("source_revision"),
        "source_snapshot_id": context.get("source_snapshot_id"),
        "spec_bundle_hash": spec_bundle_hash(),
        "input_hashes": _scope_input_hashes(uo_root, phase0, run_id),
        "items": [
            {
                "id": "OP_SCOPE_RECEIPT",
                "kind": "scope_receipt",
                "status": "recorded",
                "identity": {"run_id": run_id, "artifact": "runs.receipt"},
                "sources": [{"kind": "runtime", "path": f"runs/{run_id}/scope/receipt.yaml"}],
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
    _write_entry_points(phase0 / "entry_points.yaml", uo_root, run_id, confirmed)
    return 0, [f"wrote {out}"]


def _validation_errors(
    repo_root: Path,
    uo_root: Path,
    docs: dict[str, dict[str, Any]],
    *,
    op_name: str = "",
) -> list[str]:
    errors: list[str] = []
    context = _item_data(docs["context"])
    skill = _item_data(docs["installed_skill_check"])
    meta_path = uo_root / "cbm" / "index_meta.json"
    if not meta_path.is_file():
        errors.append(
            "cbm/index_meta.json missing — after MCP index_repository run "
            "`acp uo-scope record-index --cbm-project <name>` before finalize"
        )
    cbm_meta = _load_json(meta_path)
    # Presence of uo-init is hard; hash drift is soft (matches prepare_layout exit 3).
    skill_present = skill.get("skill_present")
    error_code = str(skill.get("error_code") or "")
    skill_root = str(skill.get("installed_skill_root") or "").replace("\\", "/")
    if skill_present is None:
        if error_code == "MISSING_INSTALLED_SKILL":
            skill_present = False
        else:
            skill_present = skill.get("consistent") is True or skill_root.rstrip("/").endswith("uo-init")
    if skill_present is False or error_code == "MISSING_INSTALLED_SKILL":
        errors.append("installed_skill_check: uo-init skill missing (reinstall)")
    elif skill.get("consistent") is not True:
        print(
            "WARNING: installed_skill_check version mismatch (continuing finalize). "
            "Re-run install.ps1/install.sh to align plugin hashes.",
            file=sys.stderr,
        )
    # MCP index is mandatory — no filesystem_scan soft-skip.
    if not cbm_meta.get("cbm_project"):
        errors.append("cbm/index_meta.json missing cbm_project")
    if cbm_meta.get("indexed_via") != "mcp":
        errors.append("cbm/index_meta.json indexed_via must be mcp")
    if not cbm_meta.get("indexed_at"):
        errors.append("cbm/index_meta.json missing indexed_at")
    if cbm_meta.get("repo_root") and Path(str(cbm_meta["repo_root"])).resolve() != repo_root:
        errors.append("cbm/index_meta.json repo_root does not match current repository")
    # KB lives at <repo>/.ascendc-pilot/uo — uo_root.name is always "uo".
    # Compare op_name to context / CLI / package name, never to uo_root.name.
    expected_op = (
        str(context.get("op_name") or op_name or "").strip() or safe_op_name(None, repo_root)
    )
    meta_op = str(cbm_meta.get("op_name") or "").strip()
    if meta_op and meta_op != expected_op:
        errors.append(
            f"cbm/index_meta.json op_name does not match operator root "
            f"(meta={meta_op!r}, expected={expected_op!r})"
        )
    if cbm_meta.get("project_confirmed") is False:
        errors.append("cbm/index_meta.json project_confirmed is false")
    if _doc_status(docs["scope_scan"]) != "complete":
        errors.append("scope_scan.yaml status is not complete")
    semantic_status = _doc_status(docs["semantic_enrichment"])
    if semantic_status in {"complete", "degraded"}:
        _validate_semantic_enrichment(docs["semantic_enrichment"], errors)
    elif semantic_status != "pending":
        errors.append("semantic_enrichment.yaml status must be pending, complete, or degraded")
    if docs["scope_review"].get("decision") != "continue":
        errors.append("scope_review.yaml decision is not continue")
    _validate_scope_sets(docs["scope_review"], errors)
    confirmed_files = _confirmed_files(docs.get("scope_confirmed") or docs["scope_review"])
    if not confirmed_files:
        errors.append("scope_confirmed.yaml missing confirmed_file_list")
    indexed_files = cbm_meta.get("indexed_files")
    if cbm_meta.get("index_input") != "confirmed_file_list":
        errors.append("cbm/index_meta.json index_input must be confirmed_file_list")
    if indexed_files is None:
        errors.append("cbm/index_meta.json missing indexed_files")
    elif sorted(_paths(indexed_files)) != sorted(_paths(confirmed_files)):
        errors.append("cbm/index_meta.json indexed_files must match confirmed_file_list")
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
    if "queries" in doc or "queries" in data:
        errors.append("semantic_enrichment.yaml must use cbm_queries instead of queries")
    records = data.get("cbm_queries") or doc.get("cbm_queries")
    architecture_filter = data.get("architecture_filter") or doc.get("architecture_filter")
    if not isinstance(architecture_filter, dict):
        errors.append("semantic_enrichment.yaml missing architecture_filter mapping")
    else:
        for key in ("included", "excluded"):
            if not isinstance(architecture_filter.get(key), list):
                errors.append(f"semantic_enrichment.yaml architecture_filter.{key} must be a list")
    for key in ("architecture_variants", "excluded_architectures", "confirmed_scope_additions", "warnings"):
        value = data.get(key) if key in data else doc.get(key)
        if not isinstance(value, list):
            errors.append(f"semantic_enrichment.yaml missing {key} list")
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
        for key in ("tool",):
            if key not in record:
                errors.append(f"semantic_enrichment.yaml cbm_queries[{index}] missing {key}")
        if not any(key in record for key in ("payload", "query")):
            errors.append(f"semantic_enrichment.yaml cbm_queries[{index}] missing payload/query")
        if not any(key in record for key in ("result_summary", "result", "error", "reason")):
            errors.append(f"semantic_enrichment.yaml cbm_queries[{index}] missing result/error")


def _scope_confirmed_from_review(
    uo_root: Path,
    run_id: str,
    review: dict[str, Any],
    *,
    operator: str,
) -> dict[str, Any]:
    approved = review.get("approved_scope") if isinstance(review.get("approved_scope"), dict) else {}
    files = _confirmed_files(review)
    return {
        "version": 1,
        "artifact": {"type": "runs.scope_confirmed", "schema_version": 1, "owner": "deterministic-uo-engine"},
        "snapshot": scope_snapshot(uo_root, run_id),
        "status": "confirmed" if files else "empty",
        "run_id": run_id,
        "workflow_id": "uo-init",
        "action_id": "scope_confirmation",
        "operator": operator,
        "confirmed_file_list": files,
        "excluded_files": approved.get("excluded_files") or [],
        "analysis_scope": {
            "input_output": _paths_by_role(files, {"input_output", "api", "proto"}),
            "host": _paths_by_role(files, {"host"}),
            "tiling": [item["path"] for item in files if "tiling" in item.get("path", "").lower() or item.get("role") == "tiling"],
            "kernel": _paths_by_role(files, {"kernel"}),
            "headers": _paths_by_role(files, {"headers", "header"}),
            "other": _paths_by_role(files, {"unknown", "other", "manual_include", "manual_dependency"}),
        },
        "cbm": {"indexing_allowed": bool(files), "input": "confirmed_file_list"},
    }


def _confirmed_files(doc: dict[str, Any]) -> list[dict[str, str]]:
    raw = doc.get("confirmed_file_list")
    if isinstance(raw, list):
        return [{"path": path, "role": _role_of(item)} for item in raw if (path := _path_of(item))]
    approved = doc.get("approved_scope") if isinstance(doc.get("approved_scope"), dict) else {}
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for key in ("initial_operator_files", "dependency_files", "generated_files"):
        for item in approved.get(key) or []:
            path = _path_of(item)
            if path and path not in seen:
                result.append({"path": path, "role": _role_of(item)})
                seen.add(path)
    return result


def _path_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("path") or "").replace("\\", "/")
    return str(item or "").replace("\\", "/")


def _role_of(item: Any) -> str:
    if isinstance(item, dict) and item.get("role"):
        return str(item["role"])
    path = _path_of(item).lower()
    suffix = Path(path).suffix
    if suffix in {".h", ".hh", ".hpp", ".hxx"}:
        return "headers"
    if "op_kernel" in path or "kernel" in path:
        return "kernel"
    if "tiling" in path:
        return "tiling"
    if "op_host" in path or "host" in path:
        return "host"
    if "op_api" in path or "proto" in path or "infer" in path:
        return "input_output"
    return "other"


def _paths(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [_path_of(item) for item in items if _path_of(item)]


def _paths_by_role(items: list[dict[str, str]], roles: set[str]) -> list[str]:
    return [item["path"] for item in items if item.get("role") in roles]


def _write_entry_points(path: Path, uo_root: Path, run_id: str, confirmed: dict[str, Any]) -> None:
    files = _confirmed_files(confirmed)
    payload = {
        "version": 1,
        "artifact": {"type": "runs.entry_points", "schema_version": 1, "owner": "deterministic-uo-engine"},
        "snapshot": scope_snapshot(uo_root, run_id),
        "status": "complete",
        "note": "scope confirmation intentionally records only shallow entry hints; deep operator understanding starts after CBM indexing.",
        "input": {"files": _paths_by_role(files, {"input_output", "host"}), "symbols": [], "optional": []},
        "output": {"files": _paths_by_role(files, {"input_output", "host"}), "symbols": []},
        "attributes": {"files": _paths_by_role(files, {"input_output", "host"}), "symbols": []},
        "host": {"file": _paths_by_role(files, {"host"}), "entry": []},
        "tiling": {
            "registration": {"file": [item["path"] for item in files if "tiling" in item["path"].lower()]},
            "key": {"file": [item["path"] for item in files if "tiling" in item["path"].lower()]},
            "data": {"file": _paths_by_role(files, {"headers"})},
        },
        "kernel": {"file": _paths_by_role(files, {"kernel"}), "entry": []},
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _default_cbm_status(cbm_meta: dict[str, Any]) -> dict[str, Any]:
    available = bool(cbm_meta.get("cbm_project")) and cbm_meta.get("project_confirmed") is not False
    return {
        "available": available,
        "retry_count": int(cbm_meta.get("retry_count") or 0),
        "fallback": "" if available else "filesystem_scan",
        "last_error": str(cbm_meta.get("last_error") or ""),
    }


def _source_block(operator_root: Path, scan: dict[str, Any]) -> dict[str, str]:
    # workspace_root = parent with common/ (for path resolution); project_root = operator package (KB).
    raw_workspace = scan.get("workspace_root") or scan.get("project_root")
    source_root = (
        Path(str(raw_workspace)).resolve()
        if isinstance(raw_workspace, str) and raw_workspace
        else operator_root.resolve()
    )
    operator_path = scan.get("operator_path")
    if not isinstance(operator_path, str) or not operator_path.strip():
        try:
            operator_path = operator_root.resolve().relative_to(source_root).as_posix()
        except ValueError:
            operator_path = ""
    try:
        root_relative = source_root.relative_to(operator_root.resolve()).as_posix()
    except ValueError:
        try:
            root_relative = __import__("os").path.relpath(source_root, operator_root.resolve()).replace("\\", "/")
        except ValueError:
            root_relative = ""
    return {
        "root": source_root.as_posix(),
        "operator_path": operator_path,
        "root_relative_to_operator": root_relative,
    }


def _update_manifest_source(uo_root: Path, source: dict[str, str], context: dict[str, Any], run_id: str) -> None:
    manifest_path = uo_root / "manifest.yaml"
    manifest = _load_yaml(manifest_path)
    source_block = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    source_block.update(source)
    source_block["revision"] = context.get("source_revision") or source_block.get("revision") or "unknown"
    source_block["snapshot_id"] = context.get("source_snapshot_id") or source_block.get("snapshot_id") or "SOURCE_UNKNOWN"
    manifest["source"] = source_block
    manifest["current_run_id"] = run_id
    stages = manifest.get("stages") if isinstance(manifest.get("stages"), dict) else {}
    scope_stage = stages.get("scope") if isinstance(stages.get("scope"), dict) else {}
    scope_stage["status"] = "complete"
    if "label_zh" not in scope_stage:
        scope_stage["label_zh"] = "范围确认"
    stages["scope"] = scope_stage
    manifest["stages"] = stages
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _doc_status(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("status"), str):
        return str(doc["status"])
    data = _item_data(doc)
    return str(data.get("status") or "")


def _item_data(doc: dict[str, Any]) -> dict[str, Any]:
    direct = {
        key: value
        for key, value in doc.items()
        if key not in {"version", "artifact", "snapshot", "items", "relations", "unresolved"}
    }
    if direct:
        return direct
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


def _scope_input_hashes(uo_root: Path, phase0: Path, run_id: str) -> dict[str, str]:
    candidates = {
        "manifest.yaml": uo_root / "manifest.yaml",
        f"runs/{run_id}/scope/context.yaml": phase0 / "context.yaml",
        f"runs/{run_id}/scope/installed_skill_check.yaml": phase0 / "installed_skill_check.yaml",
        f"runs/{run_id}/scope/ignore_rules.yaml": phase0 / "ignore_rules.yaml",
        f"runs/{run_id}/scope/scope_scan.yaml": phase0 / "scope_scan.yaml",
        f"runs/{run_id}/scope/semantic_enrichment.yaml": phase0 / "semantic_enrichment.yaml",
        f"runs/{run_id}/scope/scope_review.yaml": phase0 / "scope_review.yaml",
        f"runs/{run_id}/scope/scope_confirmed.yaml": phase0 / "scope_confirmed.yaml",
        "cbm/index_meta.json": uo_root / "cbm" / "index_meta.json",
    }
    return {rel: _sha256_file(path) for rel, path in candidates.items() if path.exists()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finalize scope confirmation and write the only pass receipt.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = finalize_scope(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
