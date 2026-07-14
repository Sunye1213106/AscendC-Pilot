from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import sys
from dataclasses import dataclass
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
from understand_operator._operator.spec import catalog_entries, load_spec, spec_bundle_hash

STAGE_ORDER = {"init": 0, "step1": 1, "step2": 2, "step3": 3, "compile": 4, "derived": 5}
VALIDATION_SCOPES = ("all", "boundary", "host", "compute", "kernel-overview", "kernel-slice-planner", "kernel-slice")
SCOPE_OWNERS = {
    "boundary": {"uo-boundary-agent"},
    "host": {"uo-host-tiling-agent"},
    "compute": {"uo-compute-agent"},
    "kernel-overview": {"uo-kernel-overview-agent"},
    "kernel-slice-planner": {"uo-kernel-slice-planner"},
    "kernel-slice": {"uo-kernel-slice-agent"},
}
CHECK_DIRS = ("facts", "checks", "graphs", "indexes", "runs")
DISALLOWED_KB_DIRS = ("spec", "_spec", "reference", "references", "exports", "proposal", "proposals", "archive")
REFERENCE_KEY_RE = re.compile(r".*(_id|_ids|_ref|_refs)$")
IGNORED_REFERENCE_KEYS = {
    "id",
    "run_id",
    "current_run_id",
    "snapshot_id",
    "source_snapshot_id",
    "spec_bundle_hash",
    "code_hash",
}


@dataclass(frozen=True)
class FactValidationError:
    code: str
    artifact: str
    message: str

    def render(self) -> str:
        return f"{self.code}: {self.artifact}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "artifact": self.artifact, "message": self.message}


def validate_facts(repo_root: Path, op_name: str, *, stage: str = "step1", scope: str = "all") -> list[FactValidationError]:
    if yaml is None:
        return [FactValidationError("YAML_IMPORT_ERROR", ".", "PyYAML is required")]
    repo_root = repo_root.resolve()
    spec = load_spec()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    errors: list[FactValidationError] = []
    if not uo_root.exists():
        return [FactValidationError("UO_ROOT_MISSING", ".", f"operator KB root not found: {uo_root}")]

    _validate_spec_catalog(spec, errors)
    _validate_forbidden_kb_dirs(uo_root, errors)
    manifest = _load_yaml(uo_root / "manifest.yaml", "manifest.yaml", errors)
    if isinstance(manifest, dict):
        _validate_manifest(manifest, errors)
        if STAGE_ORDER.get(stage, 0) >= STAGE_ORDER["step1"]:
            _validate_phase0_receipt(repo_root, uo_root, manifest, errors)

    entries = catalog_entries(spec)
    catalog_by_path = {str(entry.get("path", "")).replace("\\", "/"): entry for entry in entries}
    ownership = _ownership_patterns(spec)
    relation_types = set(((spec.get("relation_types") or {}).get("relation_types") or {}).keys())
    relation_type_specs = (spec.get("relation_types") or {}).get("relation_types") or {}
    id_re = re.compile(str((spec.get("stable_ids") or {}).get("pattern") or r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$"))
    allowed_prefixes = set(((spec.get("stable_ids") or {}).get("prefixes") or {}).keys())

    docs: dict[str, dict[str, Any]] = {}
    scoped_entries = _entries_for_scope(entries, scope)
    yaml_paths = _yaml_paths(uo_root)
    for rel in _required_paths_for_stage(spec, scoped_entries, stage, scope):
        if "*" in rel:
            if not any(fnmatch.fnmatch(path.relative_to(uo_root).as_posix(), rel) for path in yaml_paths):
                continue
            continue
        path = uo_root / rel
        if not path.exists():
            errors.append(FactValidationError("REQUIRED_FILE_MISSING", rel, f"required after {stage}"))
    if stage == "step3" and scope in {"all", "kernel-slice"}:
        _validate_kernel_slice_file_sets(uo_root, yaml_paths, errors)

    all_docs = _load_all_yaml_docs(uo_root)
    for path in yaml_paths:
        rel = path.relative_to(uo_root).as_posix()
        doc = _load_yaml(path, rel, errors)
        if not isinstance(doc, dict):
            if doc is not None:
                errors.append(FactValidationError("YAML_ROOT_NOT_MAPPING", rel, "YAML root must be a mapping"))
            continue
        docs[rel] = doc
        entry = _catalog_match(catalog_by_path, rel)
        if not entry:
            errors.append(FactValidationError("CATALOG_PATH_UNKNOWN", rel, "YAML file is not listed in spec/file_catalog.yaml"))
            continue
        if not _entry_in_scope(entry, scope) and rel != "manifest.yaml":
            continue
        _validate_document_header(rel, doc, entry, errors)
        if rel != "manifest.yaml":
            _validate_machine_schema(spec["root"], rel, doc, entry, errors)
            _validate_compute_execution_rules(rel, doc, errors)
            _validate_formal_fact_status(rel, doc, errors)
        _validate_generic_fact_forbidden(rel, doc, errors)
        _validate_owner(rel, doc, entry, ownership, errors)
        _validate_ids(rel, doc, id_re, allowed_prefixes, errors)
        _validate_relation_types(rel, doc, relation_types, errors)
        _validate_sources(repo_root, rel, doc, id_re, errors)

    known_ids = _collect_known_ids(all_docs | docs)
    known_kinds = _collect_known_kinds(all_docs | docs)
    for rel, doc in docs.items():
        _validate_references(rel, doc, known_ids, errors)
        _validate_relation_endpoints(rel, doc, known_kinds, relation_type_specs, errors)
    return errors


def _validate_kernel_slice_file_sets(uo_root: Path, yaml_paths: list[Path], errors: list[FactValidationError]) -> None:
    required_names = {
        "variables.yaml",
        "expressions.yaml",
        "branches.yaml",
        "loops.yaml",
        "tilingdata_reads.yaml",
        "calls.yaml",
        "dataflow.yaml",
        "memory.yaml",
        "synchronization.yaml",
    }
    slice_root = uo_root / "facts" / "kernel" / "slices"
    slice_dirs = sorted(path for path in slice_root.glob("*") if path.is_dir()) if slice_root.exists() else []
    if not slice_dirs:
        errors.append(FactValidationError("KERNEL_SLICE_MISSING", "facts/kernel/slices/*", "Step 3 requires at least one kernel slice directory"))
        return
    existing_rel = {path.relative_to(uo_root).as_posix() for path in yaml_paths}
    for slice_dir in slice_dirs:
        rel_dir = slice_dir.relative_to(uo_root).as_posix()
        missing = sorted(name for name in required_names if f"{rel_dir}/{name}" not in existing_rel)
        if missing:
            errors.append(FactValidationError("KERNEL_SLICE_FILE_SET_INCOMPLETE", rel_dir, f"missing slice YAML files: {', '.join(missing)}"))


def _entries_for_scope(entries: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
    return [entry for entry in entries if _entry_in_scope(entry, scope)]


def _entry_in_scope(entry: dict[str, Any], scope: str) -> bool:
    if scope == "all":
        return True
    if str(entry.get("path") or "") == "manifest.yaml":
        return True
    return str(entry.get("owner") or "") in SCOPE_OWNERS.get(scope, set())


def _validate_spec_catalog(spec: dict[str, Any], errors: list[FactValidationError]) -> None:
    root = spec["root"]
    seen_paths: set[str] = set()
    for entry in catalog_entries(spec):
        rel = str(entry.get("path") or "").replace("\\", "/")
        if not rel:
            errors.append(FactValidationError("CATALOG_PATH_MISSING", "spec/file_catalog.yaml", "entry missing path"))
            continue
        if rel in seen_paths:
            errors.append(FactValidationError("CATALOG_PATH_DUPLICATE", rel, "duplicate catalog path"))
        seen_paths.add(rel)
        for key in ("artifact_type", "owner", "required_after_stage", "allow_empty"):
            if key not in entry:
                errors.append(FactValidationError("CATALOG_FIELD_MISSING", rel, f"missing catalog field: {key}"))
        schema = entry.get("schema")
        if schema and not (root / str(schema)).exists():
            errors.append(FactValidationError("SCHEMA_FILE_MISSING", rel, f"schema not found: {schema}"))


def _validate_forbidden_kb_dirs(uo_root: Path, errors: list[FactValidationError]) -> None:
    for name in DISALLOWED_KB_DIRS:
        path = uo_root / name
        if path.exists():
            errors.append(FactValidationError("FORBIDDEN_KB_PATH", name, "operator KB must not contain spec/reference/exports/proposal/archive"))


def _validate_manifest(manifest: dict[str, Any], errors: list[FactValidationError]) -> None:
    spec_info = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
    actual = spec_info.get("bundle_hash")
    expected = spec_bundle_hash()
    if actual != expected:
        errors.append(FactValidationError("SPEC_BUNDLE_MISMATCH", "manifest.yaml", f"manifest has {actual!r}, expected {expected!r}"))


def _validate_phase0_receipt(
    repo_root: Path,
    uo_root: Path,
    manifest: dict[str, Any],
    errors: list[FactValidationError],
) -> None:
    run_id = manifest.get("current_run_id")
    if not isinstance(run_id, str) or run_id == "UO_RUN_PENDING":
        return
    rel = f"runs/{run_id}/phase0/receipt.yaml"
    receipt = _load_yaml(uo_root / rel, rel, errors)
    if not isinstance(receipt, dict):
        return
    if receipt.get("status") != "pass":
        errors.append(FactValidationError("PHASE0_RECEIPT_INVALID", rel, "status must be pass"))
    snapshot = receipt.get("snapshot") if isinstance(receipt.get("snapshot"), dict) else {}
    if snapshot.get("run_id") != run_id:
        errors.append(FactValidationError("PHASE0_RECEIPT_INVALID", rel, "snapshot.run_id does not match manifest.current_run_id"))
    if snapshot.get("spec_bundle_hash") != spec_bundle_hash():
        errors.append(FactValidationError("SPEC_BUNDLE_MISMATCH", rel, "receipt spec hash does not match current Skill spec"))
    expected_revision = snapshot.get("source_revision") or receipt.get("source_revision")
    current_revision = _git_revision(repo_root)
    if expected_revision and expected_revision != "unknown" and expected_revision != current_revision:
        errors.append(FactValidationError("PHASE0_RECEIPT_STALE", rel, f"source revision changed: {expected_revision} != {current_revision}"))
    input_hashes = receipt.get("input_hashes")
    if not isinstance(input_hashes, dict) or not input_hashes:
        errors.append(FactValidationError("PHASE0_RECEIPT_INVALID", rel, "input_hashes must freeze Phase 0 artifacts"))
    elif isinstance(input_hashes, dict):
        for item_rel, expected_hash in sorted(input_hashes.items()):
            item_path = uo_root / str(item_rel)
            if not item_path.exists():
                errors.append(FactValidationError("PHASE0_RECEIPT_STALE", rel, f"{item_rel} is missing"))
                continue
            actual_hash = "sha256:" + hashlib.sha256(item_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                errors.append(FactValidationError("PHASE0_RECEIPT_STALE", rel, f"{item_rel} hash changed"))


def _git_revision(repo_root: Path) -> str:
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True)
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _ownership_patterns(spec: dict[str, Any]) -> dict[str, list[str]]:
    owners = (spec.get("ownership") or {}).get("owners") or {}
    result: dict[str, list[str]] = {}
    for owner, value in owners.items():
        if isinstance(value, dict):
            result[str(owner)] = [str(item).replace("\\", "/") for item in value.get("may_write") or []]
    return result


def _required_paths_for_stage(spec: dict[str, Any], entries: list[dict[str, Any]], stage: str, scope: str) -> list[str]:
    if scope == "all":
        contracts = ((spec.get("stage_contracts") or {}).get("stages") or {}).get(stage) or {}
        required = contracts.get("required_files") or []
        if isinstance(required, list):
            return [str(item).replace("\\", "/") for item in required if not str(item).startswith("checks/")]
    requested = STAGE_ORDER.get(stage, STAGE_ORDER["step1"])
    result: list[str] = []
    for entry in entries:
        required_after = str(entry.get("required_after_stage") or "")
        if required_after in {"runtime", "derived"}:
            continue
        if str(entry.get("path") or "").startswith("checks/"):
            continue
        order = STAGE_ORDER.get(required_after)
        if order is not None and order <= requested and entry.get("schema") is not None:
            result.append(str(entry.get("path")).replace("\\", "/"))
    return result


def _yaml_paths(uo_root: Path) -> list[Path]:
    paths = [uo_root / "manifest.yaml"] if (uo_root / "manifest.yaml").exists() else []
    for dirname in CHECK_DIRS:
        root = uo_root / dirname
        if root.exists():
            paths.extend(path for path in root.rglob("*.yaml") if path.is_file())
    return sorted(set(paths))


def _load_all_yaml_docs(uo_root: Path) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    if yaml is None:
        return docs
    for path in _yaml_paths(uo_root):
        rel = path.relative_to(uo_root).as_posix()
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, UnicodeDecodeError):
            continue
        if isinstance(doc, dict):
            docs[rel] = doc
    return docs


def _load_yaml(path: Path, rel: str, errors: list[FactValidationError]) -> Any:
    if not path.exists():
        errors.append(FactValidationError("REQUIRED_FILE_MISSING", rel, "required file is missing"))
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        errors.append(FactValidationError("YAML_SYNTAX_ERROR", rel, str(exc)))
    except UnicodeDecodeError as exc:
        errors.append(FactValidationError("YAML_DECODE_ERROR", rel, str(exc)))
    return None


def _catalog_match(catalog_by_path: dict[str, dict[str, Any]], rel: str) -> dict[str, Any] | None:
    if rel in catalog_by_path:
        return catalog_by_path[rel]
    for pattern, entry in catalog_by_path.items():
        if "*" in pattern and fnmatch.fnmatch(rel, pattern):
            return entry
    return None


def _validate_document_header(rel: str, doc: dict[str, Any], entry: dict[str, Any], errors: list[FactValidationError]) -> None:
    if rel == "manifest.yaml":
        for key in ("version", "op_name", "repo_root", "source", "spec", "current_run_id", "stages"):
            if key not in doc:
                errors.append(FactValidationError("MANIFEST_FIELD_MISSING", rel, f"missing {key}"))
        return
    for key in ("version", "artifact", "snapshot"):
        if key not in doc:
            errors.append(FactValidationError("DOCUMENT_FIELD_MISSING", rel, f"missing {key}"))
    artifact = doc.get("artifact") if isinstance(doc.get("artifact"), dict) else {}
    snapshot = doc.get("snapshot") if isinstance(doc.get("snapshot"), dict) else {}
    if artifact.get("type") != entry.get("artifact_type"):
        errors.append(FactValidationError("ARTIFACT_TYPE_MISMATCH", rel, f"expected {entry.get('artifact_type')}, got {artifact.get('type')}"))
    if artifact.get("owner") != entry.get("owner"):
        errors.append(FactValidationError("OWNER_MISMATCH", rel, f"expected {entry.get('owner')}, got {artifact.get('owner')}"))
    if not str(snapshot.get("run_id") or "").startswith("UO_RUN_"):
        errors.append(FactValidationError("RUN_ID_INVALID", rel, "snapshot.run_id must start with UO_RUN_"))
    if not str(snapshot.get("source_snapshot_id") or "").startswith("SOURCE_"):
        errors.append(FactValidationError("SOURCE_SNAPSHOT_INVALID", rel, "snapshot.source_snapshot_id must start with SOURCE_"))
    if snapshot.get("spec_bundle_hash") != spec_bundle_hash():
        errors.append(FactValidationError("SPEC_BUNDLE_MISMATCH", rel, "snapshot.spec_bundle_hash does not match current Skill spec"))
    for key in ("items", "relations", "unresolved"):
        if key in doc and not isinstance(doc.get(key), list):
            errors.append(FactValidationError("DOCUMENT_SECTION_INVALID", rel, f"{key} must be a list"))
    if (
        not rel.startswith("checks/")
        and not entry.get("allow_empty")
        and not (doc.get("items") or doc.get("relations") or doc.get("unresolved"))
    ):
        errors.append(FactValidationError("DOCUMENT_EMPTY_NOT_ALLOWED", rel, "catalog marks this artifact as non-empty after its stage"))
    if (
        not rel.startswith(("checks/", "graphs/", "indexes/", "runs/"))
        and entry.get("allow_empty")
        and not (doc.get("items") or doc.get("relations") or doc.get("unresolved"))
    ):
        if doc.get("analysis_status") != "not_applicable" or not doc.get("reason") or not doc.get("sources"):
            errors.append(
                FactValidationError(
                    "EMPTY_REQUIRES_NOT_APPLICABLE",
                    rel,
                    "empty optional artifacts must state analysis_status: not_applicable with reason and sources",
                )
            )


def _validate_machine_schema(
    spec_root: Path,
    rel: str,
    doc: dict[str, Any],
    entry: dict[str, Any],
    errors: list[FactValidationError],
) -> None:
    schema_rel = entry.get("schema")
    if not schema_rel:
        return
    schema_path = spec_root / str(schema_rel)
    schema = _load_schema(schema_path, errors, rel)
    if not schema:
        return
    for key in schema.get("required_top_level") or []:
        if key not in doc:
            errors.append(FactValidationError("SCHEMA_REQUIRED_FIELD_MISSING", rel, f"/{key} is required by {schema_rel}"))
    allowed = schema.get("allowed_top_level")
    if isinstance(allowed, list):
        allowed_set = {str(item) for item in allowed}
        for key in doc:
            if key not in allowed_set:
                errors.append(FactValidationError("SCHEMA_TOP_LEVEL_FIELD_FORBIDDEN", rel, f"/{key} is not allowed by {schema_rel}"))
    item_kinds = {str(item) for item in schema.get("item_kind_enum") or []}
    required_item_fields = [str(item) for item in schema.get("required_item_fields") or []]
    kind_required_fields = schema.get("kind_required_fields") if isinstance(schema.get("kind_required_fields"), dict) else {}
    for index, item in enumerate(doc.get("items") or []):
        if not isinstance(item, dict):
            errors.append(FactValidationError("SCHEMA_ITEM_NOT_MAPPING", rel, f"/items/{index} must be a mapping"))
            continue
        kind = str(item.get("kind") or "")
        if item_kinds and kind not in item_kinds:
            errors.append(FactValidationError("SCHEMA_ITEM_KIND_INVALID", rel, f"/items/{index}/kind {kind!r} is not allowed"))
        needed = list(required_item_fields)
        if isinstance(kind_required_fields.get(kind), list):
            needed.extend(str(field) for field in kind_required_fields[kind])
        if _normalize_kind(kind) == "outcome" and "outcome_refs" in item:
            errors.append(FactValidationError("SCHEMA_OUTCOME_FIELD_FORBIDDEN", rel, f"/items/{index}/outcome_refs is not allowed on branch outcome"))
        for field in sorted(set(needed)):
            if field not in item or item.get(field) in (None, ""):
                errors.append(FactValidationError("SCHEMA_ITEM_FIELD_MISSING", rel, f"/items/{index}/{field} is required"))
        _validate_nested_schema_rules(rel, f"/items/{index}", item, schema, errors)
    relation_required_fields = [str(item) for item in schema.get("relation_required_fields") or []]
    for index, relation in enumerate(doc.get("relations") or []):
        if not isinstance(relation, dict):
            continue
        for field in relation_required_fields:
            if field not in relation or relation.get(field) in (None, ""):
                errors.append(FactValidationError("SCHEMA_RELATION_FIELD_MISSING", rel, f"/relations/{index}/{field} is required"))
        _validate_nested_schema_rules(rel, f"/relations/{index}", relation, schema, errors)
    min_cardinality = schema.get("minimum_cardinality")
    if isinstance(min_cardinality, int) and min_cardinality > 0:
        if len(doc.get("items") or []) + len(doc.get("relations") or []) + len(doc.get("unresolved") or []) < min_cardinality:
            errors.append(FactValidationError("SCHEMA_MIN_CARDINALITY", rel, f"requires at least {min_cardinality} item/relation/unresolved entry"))


def _validate_nested_schema_rules(rel: str, base_path: str, value: dict[str, Any], schema: dict[str, Any], errors: list[FactValidationError]) -> None:
    for required_path in schema.get("required_paths") or []:
        if _path_value(value, str(required_path)) in (None, "", []):
            errors.append(FactValidationError("SCHEMA_REQUIRED_FIELD_MISSING", rel, f"{base_path}/{str(required_path).strip('/')} is required"))
    enum_paths = schema.get("enum_paths") if isinstance(schema.get("enum_paths"), dict) else {}
    for path, allowed in enum_paths.items():
        current = _path_value(value, str(path))
        if current is not None and isinstance(allowed, list) and current not in allowed:
            errors.append(FactValidationError("SCHEMA_ENUM_INVALID", rel, f"{base_path}/{str(path).strip('/')} {current!r} is not one of {allowed}"))
    list_rules = schema.get("list_item_rules") if isinstance(schema.get("list_item_rules"), dict) else {}
    for path, rule in list_rules.items():
        items = _path_value(value, str(path))
        if not isinstance(items, list):
            errors.append(FactValidationError("SCHEMA_LIST_FIELD_INVALID", rel, f"{base_path}/{str(path).strip('/')} must be a list"))
            continue
        rule_map = rule if isinstance(rule, dict) else {}
        required = [str(item) for item in rule_map.get("required_fields") or []]
        enum_fields = rule_map.get("enum_fields") if isinstance(rule_map.get("enum_fields"), dict) else {}
        for index, item in enumerate(items):
            item_path = f"{base_path}/{str(path).strip('/')}/{index}"
            if not isinstance(item, dict):
                errors.append(FactValidationError("SCHEMA_LIST_ITEM_NOT_MAPPING", rel, f"{item_path} must be a mapping"))
                continue
            for field in required:
                if item.get(field) in (None, "", []):
                    errors.append(FactValidationError("SCHEMA_ITEM_FIELD_MISSING", rel, f"{item_path}/{field} is required"))
            for field, allowed in enum_fields.items():
                if item.get(field) is not None and isinstance(allowed, list) and item.get(field) not in allowed:
                    errors.append(FactValidationError("SCHEMA_ENUM_INVALID", rel, f"{item_path}/{field} {item.get(field)!r} is not one of {allowed}"))


def _path_value(value: Any, path: str) -> Any:
    current = value
    for part in [item for item in path.strip("/").split("/") if item]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
    return current


def _validate_formal_fact_status(rel: str, doc: dict[str, Any], errors: list[FactValidationError]) -> None:
    if not rel.startswith("facts/"):
        return
    for section in ("items", "relations"):
        for index, item in enumerate(doc.get(section) or []):
            if isinstance(item, dict) and item.get("status") != "confirmed":
                errors.append(FactValidationError("FORMAL_FACT_STATUS_INVALID", rel, f"/{section}/{index}/status must be confirmed; put unconfirmed information in unresolved"))


def _validate_generic_fact_forbidden(rel: str, doc: dict[str, Any], errors: list[FactValidationError]) -> None:
    for section in ("items", "relations"):
        for index, item in enumerate(doc.get(section) or []):
            if isinstance(item, dict) and item.get("kind") == "generic_fact":
                errors.append(FactValidationError("SCHEMA_GENERIC_FACT_FORBIDDEN", rel, f"/{section}/{index}/kind generic_fact is not allowed in core facts"))


def _validate_compute_execution_rules(rel: str, doc: dict[str, Any], errors: list[FactValidationError]) -> None:
    if not rel.endswith("facts/compute/operations.yaml") and rel != "facts/compute/operations.yaml":
        return
    for index, item in enumerate(doc.get("items") or []):
        if not isinstance(item, dict):
            continue
        execution = item.get("execution") if isinstance(item.get("execution"), dict) else {}
        classification = execution.get("classification")
        paths = [path for path in execution.get("paths") or [] if isinstance(path, dict)]
        engines = [str(path.get("engine") or "") for path in paths]
        if classification not in {"cube", "vector", "scalar", "data_movement", "conditional", "mixed", "unknown"}:
            errors.append(FactValidationError("COMPUTE_EXECUTION_CLASSIFICATION_INVALID", rel, f"/items/{index}/execution/classification is required"))
            continue
        if not isinstance(execution.get("paths"), list):
            errors.append(FactValidationError("COMPUTE_EXECUTION_PATHS_INVALID", rel, f"/items/{index}/execution/paths must be a list"))
        for path_index, path in enumerate(paths):
            if path.get("engine") not in {"cube", "vector", "scalar", "data_movement", "unknown"}:
                errors.append(FactValidationError("COMPUTE_EXECUTION_ENGINE_INVALID", rel, f"/items/{index}/execution/paths/{path_index}/engine is invalid"))
        if classification in {"cube", "vector", "scalar", "data_movement"} and classification not in engines:
            errors.append(FactValidationError("COMPUTE_EXECUTION_PATH_MISSING", rel, f"/items/{index} classification {classification} requires a {classification} path"))
        if classification == "conditional":
            signatures = {(str(path.get("engine") or ""), tuple(str(ref) for ref in path.get("condition_refs") or [])) for path in paths}
            if len(signatures) < 2:
                errors.append(FactValidationError("COMPUTE_CONDITIONAL_PATH_INSUFFICIENT", rel, f"/items/{index} conditional classification requires at least two distinct path conditions or engines"))
        if classification == "mixed":
            if not {"cube", "vector"} <= set(engines):
                errors.append(FactValidationError("COMPUTE_MIXED_PATH_INSUFFICIENT", rel, f"/items/{index} mixed classification requires cube and vector paths"))
            for engine in ("cube", "vector"):
                if not any(path.get("engine") == engine and path.get("api_refs") for path in paths):
                    errors.append(FactValidationError("COMPUTE_MIXED_API_REFS_MISSING", rel, f"/items/{index} mixed classification requires {engine} path api_refs"))
        if classification == "unknown":
            related_id = str(item.get("id") or "")
            unresolved = [entry for entry in doc.get("unresolved") or [] if isinstance(entry, dict)]
            if not any(str(entry.get("related_item_ref") or "") == related_id and str(entry.get("id") or "").startswith("OPR_") for entry in unresolved):
                errors.append(FactValidationError("COMPUTE_UNKNOWN_REQUIRES_UNRESOLVED", rel, f"/items/{index} unknown classification requires unresolved OPR_* with related_item_ref"))


def _load_schema(schema_path: Path, errors: list[FactValidationError], rel: str) -> dict[str, Any]:
    try:
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        errors.append(FactValidationError("SCHEMA_YAML_INVALID", rel, f"{schema_path}: {exc}"))
        return {}
    if not isinstance(schema, dict):
        errors.append(FactValidationError("SCHEMA_ROOT_NOT_MAPPING", rel, f"{schema_path} must be a mapping"))
        return {}
    return schema


def _validate_owner(
    rel: str,
    doc: dict[str, Any],
    entry: dict[str, Any],
    ownership: dict[str, list[str]],
    errors: list[FactValidationError],
) -> None:
    owner = str((doc.get("artifact") or {}).get("owner") or entry.get("owner") or "")
    allowed = ownership.get(owner, [])
    if not any(fnmatch.fnmatch(rel, pattern) for pattern in allowed):
        errors.append(FactValidationError("OWNER_PATH_FORBIDDEN", rel, f"{owner} may not write this path"))


def _validate_ids(
    rel: str,
    doc: Any,
    id_re: re.Pattern[str],
    allowed_prefixes: set[str],
    errors: list[FactValidationError],
) -> None:
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key == "id" and isinstance(child, str):
                    _check_id(rel, child_path, child, id_re, allowed_prefixes, errors)
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(doc, "")


def _check_id(
    rel: str,
    path: str,
    value: str,
    id_re: re.Pattern[str],
    allowed_prefixes: set[str],
    errors: list[FactValidationError],
) -> None:
    if not id_re.fullmatch(value):
        errors.append(FactValidationError("STABLE_ID_INVALID", rel, f"{path} invalid id: {value}"))
        return
    prefix = value.split("_", 1)[0]
    if prefix not in allowed_prefixes:
        errors.append(FactValidationError("STABLE_ID_PREFIX_INVALID", rel, f"{path} uses unknown prefix: {prefix}"))


def _validate_relation_types(rel: str, doc: dict[str, Any], relation_types: set[str], errors: list[FactValidationError]) -> None:
    for index, relation in enumerate(doc.get("relations") or []):
        if not isinstance(relation, dict):
            errors.append(FactValidationError("RELATION_NOT_MAPPING", rel, f"relations[{index}] must be a mapping"))
            continue
        rtype = relation.get("type")
        if rtype not in relation_types:
            errors.append(FactValidationError("RELATION_TYPE_INVALID", rel, f"relations[{index}].type is not in spec: {rtype}"))


def _validate_sources(repo_root: Path, rel: str, doc: dict[str, Any], id_re: re.Pattern[str], errors: list[FactValidationError]) -> None:
    for section_name in ("items", "relations"):
        for index, item in enumerate(doc.get(section_name) or []):
            if not isinstance(item, dict):
                continue
            sources = item.get("sources")
            if not isinstance(sources, list) or not sources:
                errors.append(FactValidationError("SOURCE_MISSING", rel, f"{section_name}[{index}] formal entry lacks sources"))
                continue
            for source_index, source in enumerate(sources):
                if not isinstance(source, dict):
                    errors.append(FactValidationError("SOURCE_NOT_MAPPING", rel, f"{section_name}[{index}].sources[{source_index}]"))
                    continue
                _validate_one_source(repo_root, rel, f"{section_name}[{index}].sources[{source_index}]", source, id_re, errors)


def _validate_one_source(
    repo_root: Path,
    rel: str,
    label: str,
    source: dict[str, Any],
    id_re: re.Pattern[str],
    errors: list[FactValidationError],
) -> None:
    for key in ("id", "file", "symbol", "span", "source_text", "code_hash", "anchor_kind"):
        if key not in source or source.get(key) in (None, ""):
            errors.append(FactValidationError("SOURCE_FIELD_MISSING", rel, f"{label}.{key} is required"))
    source_id = source.get("id")
    if isinstance(source_id, str) and (not source_id.startswith("SRC_") or not id_re.fullmatch(source_id)):
        errors.append(FactValidationError("SOURCE_ID_INVALID", rel, f"{label}.id must be SRC_*"))
    file_value = source.get("file")
    if not isinstance(file_value, str) or Path(file_value).is_absolute():
        errors.append(FactValidationError("SOURCE_FILE_INVALID", rel, f"{label}.file must be repo-relative"))
        return
    source_path = (repo_root / file_value).resolve()
    try:
        source_path.relative_to(repo_root)
    except ValueError:
        errors.append(FactValidationError("SOURCE_FILE_OUTSIDE_REPO", rel, f"{label}.file points outside repo"))
        return
    if not source_path.exists() or not source_path.is_file():
        errors.append(FactValidationError("SOURCE_FILE_MISSING", rel, f"{label}.file not found: {file_value}"))
        return
    span = source.get("span")
    if not isinstance(span, dict):
        errors.append(FactValidationError("SOURCE_SPAN_INVALID", rel, f"{label}.span must be a mapping"))
        return
    start = span.get("start_line")
    end = span.get("end_line")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        errors.append(FactValidationError("SOURCE_SPAN_INVALID", rel, f"{label}.span start_line/end_line invalid"))
        return
    lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if end > len(lines):
        errors.append(FactValidationError("SOURCE_SPAN_OUT_OF_RANGE", rel, f"{label}.span exceeds file length"))
        return
    actual_text = "\n".join(lines[start - 1 : end])
    if source.get("source_text") != actual_text:
        errors.append(FactValidationError("SOURCE_TEXT_MISMATCH", rel, f"{label}.source_text does not match file span"))
        return
    expected_hash = "sha256:" + hashlib.sha256(actual_text.encode("utf-8")).hexdigest()
    if source.get("code_hash") != expected_hash:
        errors.append(FactValidationError("SOURCE_HASH_MISMATCH", rel, f"{label}.code_hash does not match source_text"))


def _collect_known_ids(docs: dict[str, dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for doc in docs.values():
        for section in ("items", "relations", "unresolved"):
            for item in doc.get(section) or []:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    ids.add(item["id"])
                if isinstance(item, dict):
                    for source in item.get("sources") or []:
                        if isinstance(source, dict) and isinstance(source.get("id"), str):
                            ids.add(source["id"])
    return ids


def _collect_known_kinds(docs: dict[str, dict[str, Any]]) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for doc in docs.values():
        for item in doc.get("items") or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                kinds[item["id"]] = _normalize_kind(str(item.get("kind") or "fact"))
        for relation in doc.get("relations") or []:
            if isinstance(relation, dict) and isinstance(relation.get("id"), str):
                kinds[relation["id"]] = "relation"
    return kinds


def _validate_references(rel: str, doc: Any, known_ids: set[str], errors: list[FactValidationError]) -> None:
    def visit(value: Any, path: str, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, f"{path}.{child_key}" if path else str(child_key), str(child_key))
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]", key)
            return
        if key in IGNORED_REFERENCE_KEYS or not REFERENCE_KEY_RE.fullmatch(key):
            return
        if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+", value) and value not in known_ids:
            errors.append(FactValidationError("REFERENCE_TARGET_MISSING", rel, f"{path} references unknown id {value}"))

    visit(doc, "")


def _validate_relation_endpoints(
    rel: str,
    doc: dict[str, Any],
    known_kinds: dict[str, str],
    relation_type_specs: dict[str, Any],
    errors: list[FactValidationError],
) -> None:
    for index, relation in enumerate(doc.get("relations") or []):
        if not isinstance(relation, dict):
            continue
        source_id = relation.get("source_id")
        target_id = relation.get("target_id")
        rtype = relation.get("type")
        for label, value in (("source_id", source_id), ("target_id", target_id)):
            if not isinstance(value, str) or not value:
                errors.append(FactValidationError("RELATION_ENDPOINT_MISSING", rel, f"/relations/{index}/{label} is required"))
            elif value not in known_kinds:
                errors.append(FactValidationError("RELATION_ENDPOINT_UNKNOWN", rel, f"/relations/{index}/{label} references unknown id {value}"))
        spec = relation_type_specs.get(rtype) if isinstance(relation_type_specs, dict) else None
        if not isinstance(spec, dict) or not isinstance(source_id, str) or not isinstance(target_id, str):
            continue
        expected_source = str(spec.get("source") or "any")
        expected_target = str(spec.get("target") or "any")
        actual_source = known_kinds.get(source_id)
        actual_target = known_kinds.get(target_id)
        if actual_source and not _kind_matches(actual_source, expected_source):
            errors.append(
                FactValidationError(
                    "RELATION_ENDPOINT_KIND_INVALID",
                    rel,
                    f"/relations/{index}/source_id expects {expected_source}, got {actual_source} for {source_id}",
                )
            )
        if actual_target and not _kind_matches(actual_target, expected_target):
            errors.append(
                FactValidationError(
                    "RELATION_ENDPOINT_KIND_INVALID",
                    rel,
                    f"/relations/{index}/target_id expects {expected_target}, got {actual_target} for {target_id}",
                )
            )


def _kind_matches(actual: str, expected: str) -> bool:
    if expected == "any":
        return True
    if actual == expected:
        return True
    aliases = {
        "argument": {"input_tensor", "output_tensor", "optional_input", "attribute"},
        "variable": {"variable", "runtime_variable", "host_variable", "tilingdata", "key"},
        "symbol": {"symbol", "host_entry", "tiling_entry", "kernel_entry", "function", "call"},
        "expression": {"expression"},
        "branch": {"branch"},
        "outcome": {"outcome"},
        "loop": {"loop"},
        "call": {"call"},
        "key": {"key"},
        "tilingdata": {"tilingdata"},
        "tensor": {"tensor", "input_tensor", "output_tensor"},
        "operation": {"operation"},
        "api": {"api", "call"},
        "sync": {"sync"},
        "source_file": {"source_file", "dependency_file"},
        "memory_resource": {"memory_resource"},
    }
    return actual in aliases.get(expected, set())


def _normalize_kind(kind: str) -> str:
    lowered = kind.lower()
    if lowered.startswith("input_") or lowered.startswith("output_"):
        return lowered
    if "outcome" in lowered:
        return "outcome"
    if "tensor" in lowered:
        return "tensor"
    if "operation" in lowered:
        return "operation"
    if "resource" in lowered:
        return "memory_resource"
    if "api" in lowered:
        return "api"
    if lowered in {"source_file", "dependency_file"}:
        return "source_file"
    if "branch" in lowered:
        return "branch"
    if "loop" in lowered:
        return "loop"
    if "call" in lowered:
        return "call"
    if "key" in lowered:
        return "key"
    if "tilingdata" in lowered:
        return "tilingdata"
    if "sync" in lowered:
        return "sync"
    if "entry" in lowered or "function" in lowered or "symbol" in lowered:
        return "symbol"
    if "expr" in lowered:
        return "expression"
    if "var" in lowered:
        return "variable"
    return lowered or "fact"


def _write_report(uo_root: Path, stage: str, scope: str, errors: list[FactValidationError]) -> None:
    if stage == "step1":
        report = uo_root / "checks" / "step1" / "validation.yaml"
        artifact_type = "checks.step1.validation"
    elif stage == "step2":
        report_map = {
            "host": ("host_validation.yaml", "checks.step2.host_validation"),
            "compute": ("compute_validation.yaml", "checks.step2.compute_validation"),
            "kernel-overview": ("kernel_overview_validation.yaml", "checks.step2.kernel_overview_validation"),
        }
        report_name, artifact_type = report_map.get(scope, report_map["host"])
        report = uo_root / "checks" / "step2" / report_name
    elif stage == "step3":
        report = uo_root / "checks" / "step3" / "slice_validations.yaml"
        artifact_type = "checks.step3.slice_validations"
    else:
        report = uo_root / "checks" / "compile_gate.yaml"
        artifact_type = "checks.compile_gate"
    payload = {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": "facts-validator"},
        "snapshot": {
            "run_id": "UO_RUN_VALIDATOR",
            "source_snapshot_id": "SOURCE_VALIDATOR",
            "source_revision": "unknown",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "status": "fail" if errors else "pass",
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "input_hashes": _input_hashes_for_scope(uo_root, stage, scope),
        "errors": [error.to_dict() for error in errors],
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _input_hashes_for_scope(uo_root: Path, stage: str, scope: str) -> dict[str, str]:
    fact_paths: list[Path] = []
    if stage == "step1":
        fact_paths = sorted((uo_root / "facts" / "operator").glob("*.yaml"))
    elif stage == "step2":
        roots = {
            "host": [uo_root / "facts" / "host"],
            "compute": [uo_root / "facts" / "compute"],
            "kernel-overview": [uo_root / "facts" / "kernel" / "overview"],
            "all": [uo_root / "facts" / "host", uo_root / "facts" / "compute", uo_root / "facts" / "kernel" / "overview"],
        }.get(scope, [])
        for root in roots:
            if root.exists():
                fact_paths.extend(sorted(root.rglob("*.yaml")))
    elif stage in {"step3", "compile"}:
        if (uo_root / "facts").exists():
            fact_paths = sorted((uo_root / "facts").rglob("*.yaml"))
    result: dict[str, str] = {}
    for path in fact_paths:
        if path.is_file():
            rel = path.relative_to(uo_root).as_posix()
            result[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Understand Operator source-fact YAML against the Skill spec.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--stage", default="step1", choices=sorted(STAGE_ORDER), help="Validation stage")
    parser.add_argument("--scope", default="all", choices=VALIDATION_SCOPES, help="Artifact ownership slice to validate")
    parser.add_argument("--write-report", action="store_true", help="Write checks/<stage>/validation YAML")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    errors = validate_facts(repo_root, op_name, stage=args.stage, scope=args.scope)
    uo_root = existing_operator_root(repo_root, op_name)
    if args.write_report and uo_root.exists():
        _write_report(uo_root, args.stage, args.scope, errors)
    if errors:
        for error in errors:
            print(error.render(), file=sys.stderr)
        return 2
    print(f"Facts validation passed for {op_name} at {args.stage}/{args.scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
