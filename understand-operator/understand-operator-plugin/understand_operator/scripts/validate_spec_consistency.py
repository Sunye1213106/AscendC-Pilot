from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
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

from understand_operator._operator.catalog import match_catalog_entry
from understand_operator._operator.reference_paths import reference_declarations
from understand_operator._operator.spec import load_spec


MODEL_FORBIDDEN_FIELDS = {"id", "stable_id", "canonical_key", "source_text", "code_hash", "file_hash", "sources"}
COMMON_FORMAL_REQUIRED = {"id", "kind", "status", "identity", "sources"}


@dataclass(frozen=True)
class SpecError:
    code: str
    target: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "target": self.target, "message": self.message}


def validate_spec_consistency(plugin_root: Path | None = None) -> list[SpecError]:
    if yaml is None:
        return [SpecError("YAML_IMPORT_ERROR", ".", "PyYAML is required")]
    spec = load_spec()
    root = spec["root"]
    errors: list[SpecError] = []
    entity_spec = spec.get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec.get("entity_types"), dict) else {}
    kind_groups = entity_spec.get("kind_groups") if isinstance(entity_spec.get("kind_groups"), dict) else {}
    relation_types = (spec.get("relation_types") or {}).get("relation_types") or {}
    valid_targets = set(entity_types) | set(kind_groups) | {"any"}

    _validate_entity_types(entity_types, kind_groups, errors)
    _validate_relation_types(relation_types, valid_targets, errors)
    _validate_formal_schemas(root, entity_spec, entity_types, valid_targets, errors)
    _validate_candidate_schema(root, errors)
    _validate_agent_targets(plugin_root or root.parents[1], spec, errors)
    return errors


def _validate_entity_types(entity_types: dict[str, Any], kind_groups: dict[str, Any], errors: list[SpecError]) -> None:
    valid_targets = set(entity_types) | set(kind_groups) | {"any"}
    for kind, config in sorted(entity_types.items()):
        if not isinstance(config, dict):
            continue
        for field in ("prefix", "identity_strategy", "required_identity_fields", "reference_fields"):
            if field not in config:
                errors.append(SpecError("SPEC_IDENTITY_FIELD_MISMATCH", "entity_types.yaml", f"{kind} missing {field}"))
        required = config.get("required_identity_fields")
        if not isinstance(required, list) or not required:
            errors.append(SpecError("SPEC_IDENTITY_FIELD_MISMATCH", "entity_types.yaml", f"{kind} required_identity_fields must be non-empty"))
        refs = config.get("reference_fields") if isinstance(config.get("reference_fields"), dict) else {}
        for cardinality in ("single", "multiple"):
            declared = refs.get(cardinality) if isinstance(refs.get(cardinality), dict) else {}
            for path, allowed in declared.items():
                suffix = "_ref" if cardinality == "single" else "_refs"
                if not str(path).split(".")[-1].endswith(suffix):
                    errors.append(SpecError("SPEC_REFERENCE_CARDINALITY_MISMATCH", "entity_types.yaml", f"{kind}.{path} must end with {suffix}"))
                _check_allowed_targets(allowed, valid_targets, errors, "SPEC_REFERENCE_KIND_UNKNOWN", f"{kind}.{path}")
        identity_refs = config.get("identity_reference_fields") if isinstance(config.get("identity_reference_fields"), dict) else {}
        identity_fields = set(str(item) for item in (required if isinstance(required, list) else []))
        for path, allowed in identity_refs.items():
            if path not in identity_fields:
                errors.append(SpecError("SPEC_IDENTITY_FIELD_MISMATCH", "entity_types.yaml", f"{kind}.{path} identity reference is not a required identity field"))
            _check_allowed_targets(allowed, valid_targets, errors, "SPEC_REFERENCE_KIND_UNKNOWN", f"{kind}.{path}")


def _validate_relation_types(relation_types: dict[str, Any], valid_targets: set[str], errors: list[SpecError]) -> None:
    for name, config in sorted(relation_types.items()):
        if not isinstance(config, dict):
            continue
        for key in ("source", "target"):
            target = str(config.get(key) or "")
            if target and target not in valid_targets:
                errors.append(SpecError("SPEC_RELATION_KIND_GROUP_UNKNOWN", "relation_types.yaml", f"{name}.{key} uses unknown kind/group {target}"))
        for index, signature in enumerate(config.get("endpoint_signatures") or []):
            if not isinstance(signature, dict):
                continue
            for key in ("source", "target"):
                target = str(signature.get(key) or "")
                if target not in valid_targets:
                    errors.append(SpecError("SPEC_RELATION_KIND_GROUP_UNKNOWN", "relation_types.yaml", f"{name}.endpoint_signatures[{index}].{key} uses unknown kind/group {target}"))


def _validate_formal_schemas(root: Path, entity_spec: dict[str, Any], entity_types: dict[str, Any], valid_targets: set[str], errors: list[SpecError]) -> None:
    for schema_path in sorted((root / "schemas").rglob("*.schema.yaml")):
        rel = schema_path.relative_to(root).as_posix()
        schema = _read_yaml(schema_path)
        kinds = [str(item) for item in schema.get("item_kind_enum") or []]
        required_common = set(str(item) for item in schema.get("required_item_fields") or [])
        if kinds and not COMMON_FORMAL_REQUIRED <= required_common:
            errors.append(SpecError("SPEC_FORMAL_IDENTITY_NOT_REQUIRED", rel, f"required_item_fields must include {sorted(COMMON_FORMAL_REQUIRED)}"))
        forbidden_required = required_common & MODEL_FORBIDDEN_FIELDS - {"id", "sources"}
        if forbidden_required:
            errors.append(SpecError("SPEC_MODEL_FORBIDDEN_FIELD_REQUIRED", rel, f"required_item_fields contains Python-owned fields {sorted(forbidden_required)}"))
        kind_required = schema.get("kind_required_fields") if isinstance(schema.get("kind_required_fields"), dict) else {}
        for kind in kinds:
            if kind not in entity_types:
                errors.append(SpecError("SPEC_REFERENCE_KIND_UNKNOWN", rel, f"schema kind {kind} missing from entity_types.yaml"))
                continue
            declarations = reference_declarations(entity_spec, kind)
            required_fields = [str(item) for item in kind_required.get(kind, []) if isinstance(item, str)]
            for field in required_fields:
                if field in MODEL_FORBIDDEN_FIELDS:
                    errors.append(SpecError("SPEC_MODEL_FORBIDDEN_FIELD_REQUIRED", rel, f"{kind}.{field} is Python-owned and must not be schema-required"))
                if field.endswith("_ref") or field.endswith("_refs"):
                    declaration = declarations.get(field)
                    if declaration is None:
                        errors.append(SpecError("SPEC_REQUIRED_REFERENCE_UNDECLARED", rel, f"{kind}.{field} is required but not declared in entity_types.reference_fields"))
                    elif field.endswith("_ref") and declaration.cardinality != "single":
                        errors.append(SpecError("SPEC_REFERENCE_CARDINALITY_MISMATCH", rel, f"{kind}.{field} must be single"))
                    elif field.endswith("_refs") and declaration.cardinality != "multiple":
                        errors.append(SpecError("SPEC_REFERENCE_CARDINALITY_MISMATCH", rel, f"{kind}.{field} must be multiple"))
            for path, declaration in declarations.items():
                _check_allowed_targets(declaration.allowed, valid_targets, errors, "SPEC_REFERENCE_KIND_UNKNOWN", f"{kind}.{path}")


def _validate_candidate_schema(root: Path, errors: list[SpecError]) -> None:
    path = root / "schemas" / "candidate" / "candidate_batch.schema.json"
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(SpecError("SPEC_CANDIDATE_SCHEMA_INVALID", path.as_posix(), str(exc)))


def _validate_agent_targets(plugin_root: Path, spec: dict[str, Any], errors: list[SpecError]) -> None:
    ownership = (spec.get("ownership") or {}).get("owners") or {}
    agents_dir = plugin_root / "agents"
    for path in sorted(agents_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        owner = path.stem
        for target_path, section in re.findall(r'"target"\s*:\s*\{\s*"path"\s*:\s*"([^"]+)"\s*,\s*"section"\s*:\s*"([^"]*)"', text):
            match = match_catalog_entry(spec, target_path, writable_only=True)
            if not match:
                errors.append(SpecError("SPEC_AGENT_TARGET_UNKNOWN", path.name, f"{target_path} is not in catalog"))
                continue
            if match.entry.get("owner") != owner:
                errors.append(SpecError("SPEC_AGENT_OWNER_MISMATCH", path.name, f"{owner} cannot write {target_path}"))
            sections = match.entry.get("section_schemas") if isinstance(match.entry.get("section_schemas"), dict) else {}
            if section and section not in sections:
                errors.append(SpecError("SPEC_AGENT_TARGET_UNKNOWN", path.name, f"{target_path} section {section} is not in catalog"))
            allowed = ownership.get(owner, {}).get("may_write") if isinstance(ownership.get(owner), dict) else []
            if allowed and not any(_path_matches(target_path, str(pattern)) for pattern in allowed):
                errors.append(SpecError("SPEC_AGENT_OWNER_MISMATCH", path.name, f"ownership.yaml does not allow {owner} to write {target_path}"))


def _check_allowed_targets(allowed: Any, valid_targets: set[str], errors: list[SpecError], code: str, label: str) -> None:
    if not isinstance(allowed, (list, tuple)) or not allowed:
        errors.append(SpecError("SPEC_REFERENCE_KIND_UNKNOWN", "entity_types.yaml", f"{label} has no allowed targets"))
        return
    for item in allowed:
        if str(item) not in valid_targets:
            errors.append(SpecError(code, "entity_types.yaml", f"{label} uses unknown kind/group {item}"))


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _path_matches(path: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(path, pattern.split("#", 1)[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate schema/entity/relation/agent consistency.")
    parser.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    errors = validate_spec_consistency(args.plugin_root.resolve())
    payload = {"status": "fail" if errors else "pass", "errors": [error.to_dict() for error in errors]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
