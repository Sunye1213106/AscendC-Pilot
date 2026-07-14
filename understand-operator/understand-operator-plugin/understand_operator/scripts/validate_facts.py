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
VALIDATION_SCOPES = ("all", "boundary", "host", "compute", "kernel-overview", "kernel-slice")
SCOPE_OWNERS = {
    "boundary": {"uo-boundary-agent"},
    "host": {"uo-host-tiling-agent"},
    "compute": {"uo-compute-agent"},
    "kernel-overview": {"uo-kernel-overview-agent"},
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

    entries = catalog_entries(spec)
    catalog_by_path = {str(entry.get("path", "")).replace("\\", "/"): entry for entry in entries}
    ownership = _ownership_patterns(spec)
    relation_types = set(((spec.get("relation_types") or {}).get("relation_types") or {}).keys())
    id_re = re.compile(str((spec.get("stable_ids") or {}).get("pattern") or r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$"))
    allowed_prefixes = set(((spec.get("stable_ids") or {}).get("prefixes") or {}).keys())

    docs: dict[str, dict[str, Any]] = {}
    scoped_entries = _entries_for_scope(entries, scope)
    for rel in _required_paths_for_stage(scoped_entries, stage):
        if "*" in rel:
            if not any(fnmatch.fnmatch(path.relative_to(uo_root).as_posix(), rel) for path in _yaml_paths(uo_root)):
                continue
        path = uo_root / rel
        if not path.exists():
            errors.append(FactValidationError("REQUIRED_FILE_MISSING", rel, f"required after {stage}"))

    all_docs = _load_all_yaml_docs(uo_root)
    for path in _yaml_paths(uo_root):
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
        _validate_owner(rel, doc, entry, ownership, errors)
        _validate_ids(rel, doc, id_re, allowed_prefixes, errors)
        _validate_relation_types(rel, doc, relation_types, errors)
        _validate_sources(repo_root, rel, doc, id_re, errors)

    known_ids = _collect_known_ids(all_docs | docs)
    for rel, doc in docs.items():
        _validate_references(rel, doc, known_ids, errors)
    return errors


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


def _ownership_patterns(spec: dict[str, Any]) -> dict[str, list[str]]:
    owners = (spec.get("ownership") or {}).get("owners") or {}
    result: dict[str, list[str]] = {}
    for owner, value in owners.items():
        if isinstance(value, dict):
            result[str(owner)] = [str(item).replace("\\", "/") for item in value.get("may_write") or []]
    return result


def _required_paths_for_stage(entries: list[dict[str, Any]], stage: str) -> list[str]:
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
            if not isinstance(item, dict) or item.get("status") != "confirmed":
                continue
            sources = item.get("sources")
            if not isinstance(sources, list) or not sources:
                errors.append(FactValidationError("SOURCE_MISSING", rel, f"{section_name}[{index}] confirmed entry lacks sources"))
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
        "errors": [error.to_dict() for error in errors],
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


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
