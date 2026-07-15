from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]
try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import safe_op_name
from understand_operator._operator.catalog import CatalogMatchError, match_catalog_entry
from understand_operator._operator.candidate import CandidateError, FORBIDDEN_ITEM_FIELDS, FORBIDDEN_RELATION_FIELDS, LEGACY_IDENTITY_FIELDS, load_json
from understand_operator._operator.identity import IdentityError, resolve_identity
from understand_operator._operator.kind_match import kind_matches
from understand_operator._operator.reference_paths import declared_reference_for_path, iter_reference_like_paths, iter_reference_values, reference_declarations
from understand_operator._operator.source_reader import SourceReadError, SourceReader
from understand_operator._operator.spec import load_spec


def validate_candidate_batch(repo_root: Path, op_name: str, batch: Any) -> list[CandidateError]:
    errors: list[CandidateError] = []
    spec = load_spec()
    errors.extend(_schema_errors(spec, batch))
    if not isinstance(batch, dict):
        return [CandidateError("CANDIDATE_ROOT_INVALID", "candidate batch must be a JSON object")]
    required = {"version", "task", "target", "items", "relations", "unresolved"}
    unknown = set(batch) - required
    if unknown:
        errors.append(CandidateError("CANDIDATE_FIELD_FORBIDDEN", f"unknown top-level fields: {sorted(unknown)}"))
    if set(batch) & required != required:
        errors.append(CandidateError("CANDIDATE_FIELD_MISSING", "version, task, target, items, relations, unresolved are required"))
        return errors
    target_path, target_section = _target_parts(batch["target"])
    target_label = f"{target_path}#{target_section}" if target_section else str(batch.get("target"))
    if batch["version"] == 1:
        errors.append(CandidateError("CANDIDATE_VERSION_LEGACY", "Candidate version 1 is no longer accepted; migrate to version 2 local_id/identity references", target=target_label))
        return errors
    if batch["version"] != 2:
        errors.append(CandidateError("CANDIDATE_VERSION_INVALID", "version must be 2", target=target_label))
    task = batch["task"]
    if not isinstance(task, dict) or set(task) != {"run_id", "stage", "owner", "task_id"}:
        errors.append(CandidateError("CANDIDATE_TASK_INVALID", "task must contain exactly run_id/stage/owner/task_id", target=target_label))
        return errors
    if not target_path:
        return errors + [CandidateError("CANDIDATE_TARGET_INVALID", "target must contain path")]
    try:
        match = match_catalog_entry(spec, target_path, writable_only=True)
    except CatalogMatchError as exc:
        return errors + [CandidateError(exc.code, exc.message, target=exc.requested_path)]
    entry = match.entry if match else None
    allowed_kinds: set[str] = set()
    if not entry:
        errors.append(CandidateError("CANDIDATE_TARGET_INVALID", "target is not a formal fact catalog path", target=target_path))
    else:
        if entry.get("owner") != task["owner"]:
            errors.append(CandidateError("CANDIDATE_OWNER_FORBIDDEN", f"{task['owner']} may not write {target_path}", target=target_path))
        section_schemas = entry.get("section_schemas") if isinstance(entry.get("section_schemas"), dict) else {}
        if section_schemas and not target_section:
            errors.append(CandidateError("TARGET_SECTION_REQUIRED", "target section is required for partitioned fact files", target=target_path))
        if not section_schemas and target_section:
            errors.append(CandidateError("TARGET_SECTION_FORBIDDEN", "target section is only allowed for partitioned fact files", target=target_path, field="target.section"))
        if yaml is not None and entry.get("schema"):
            schema_rel = section_schemas.get(target_section, entry["schema"]) if target_section else entry["schema"]
            schema = yaml.safe_load((spec["root"] / str(schema_rel)).read_text(encoding="utf-8")) or {}
            allowed_kinds = {str(value) for value in schema.get("item_kind_enum") or []}
            if target_section and section_schemas and target_section not in section_schemas:
                errors.append(CandidateError("CANDIDATE_TARGET_SECTION_INVALID", f"section {target_section!r} is not declared by target schema", target=target_path))
    if task["stage"] not in {"step1", "step2", "step3"}:
        errors.append(CandidateError("CANDIDATE_STAGE_INVALID", "stage must be step1, step2, or step3", target=target_label))
    if not all(isinstance(batch.get(section), list) for section in ("items", "relations", "unresolved")):
        errors.append(CandidateError("CANDIDATE_SECTION_INVALID", "items, relations, unresolved must be arrays", target=target_label))
        return errors

    reader = SourceReader(repo_root)
    entity_spec = spec.get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}
    entity_types = (spec.get("entity_types") or {}).get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}
    local_ids: set[str] = set()
    local_id_to_kind = {str(item.get("local_id")): str(item.get("kind")) for item in batch["items"] if isinstance(item, dict) and item.get("local_id") and item.get("kind")}
    canonical_to_local: dict[str, tuple[str, str]] = {}
    for index, item in enumerate(batch["items"]):
        label = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(CandidateError("CANDIDATE_ITEM_INVALID", "item must be object", target=target_label, field=label))
            continue
        local_id = str(item.get("local_id") or "")
        forbidden = _forbidden_fields(item, FORBIDDEN_ITEM_FIELDS)
        if forbidden:
            errors.append(_forbidden_error(forbidden, target_label, label, local_id=local_id))
        if not local_id:
            errors.append(CandidateError("LOCAL_ID_INVALID", "local_id is required", target=target_label, field=f"{label}.local_id"))
        elif local_id in local_ids:
            errors.append(CandidateError("LOCAL_ID_DUPLICATE", "local_id is duplicated in this batch", target=target_label, local_id=local_id))
        local_ids.add(local_id)
        kind = item.get("kind")
        if not isinstance(kind, str) or not isinstance(item.get("fields"), dict) or not isinstance(item.get("identity"), dict):
            errors.append(CandidateError("CANDIDATE_ITEM_INVALID", "kind, identity and fields are required", target=target_label, local_id=local_id, field=label))
        else:
            if allowed_kinds and kind not in allowed_kinds:
                errors.append(CandidateError("CANDIDATE_KIND_INVALID", f"kind {kind!r} is not allowed by target schema", target=target_label, local_id=local_id, field=f"{label}.kind"))
            identity_for_validation = _identity_with_reference_placeholders(spec, kind, item["identity"], errors, target_label, local_id, label, local_id_to_kind)
            try:
                resolved = resolve_identity(kind, identity_for_validation, repo_root=repo_root)
            except IdentityError as exc:
                errors.append(CandidateError(exc.code, exc.message, target=target_label, local_id=local_id, field=f"{label}.{exc.field}"))
            else:
                previous = canonical_to_local.get(resolved.canonical_key)
                if previous and previous[0] != local_id:
                    message = f"duplicate canonical identity first_local_id={previous[0]} second_local_id={local_id} canonical_key={resolved.canonical_key} stable_id={resolved.stable_id}"
                    errors.append(CandidateError("CANDIDATE_IDENTITY_DUPLICATE", message, target=target_label, local_id=local_id, field=label))
                canonical_to_local[resolved.canonical_key] = (local_id, resolved.stable_id)
                _identity_evidence(item, reader, errors, target_label, local_id, label)
            _reference_objects(item.get("fields"), errors, target_label, f"{label}.fields", str(kind), entity_spec, local_id_to_kind)
        _locations(reader, item.get("source_locations"), errors, target_label, local_id, label)

    relation_types = set((spec["relation_types"].get("relation_types") or {}).keys())
    for index, relation in enumerate(batch["relations"]):
        label = f"relations[{index}]"
        if not isinstance(relation, dict):
            errors.append(CandidateError("CANDIDATE_RELATION_INVALID", "relation must be object", target=target_label, field=label))
            continue
        forbidden = _forbidden_fields(relation, FORBIDDEN_RELATION_FIELDS)
        if forbidden:
            errors.append(_forbidden_error(forbidden, target_label, label))
        if relation.get("type") not in relation_types:
            errors.append(CandidateError("RELATION_TYPE_INVALID", "relation type is not in spec", target=target_label, field=f"{label}.type"))
        _reference(relation.get("source"), errors, target_label, f"{label}.source", local_ids, entity_types)
        _reference(relation.get("target"), errors, target_label, f"{label}.target", local_ids, entity_types)
        if not isinstance(relation.get("fields"), dict):
            errors.append(CandidateError("CANDIDATE_RELATION_INVALID", "relation fields must be object", target=target_label, field=f"{label}.fields"))
        else:
            _reference_objects(relation.get("fields"), errors, target_label, f"{label}.fields", "", entity_spec, local_id_to_kind)
        _locations(reader, relation.get("source_locations"), errors, target_label, "", label)

    for index, entry in enumerate(batch["unresolved"]):
        label = f"unresolved[{index}]"
        if not isinstance(entry, dict):
            errors.append(CandidateError("CANDIDATE_UNRESOLVED_INVALID", "unresolved entry must be object", target=target_label, field=label))
            continue
        forbidden = _forbidden_fields(entry, FORBIDDEN_ITEM_FIELDS)
        if forbidden:
            errors.append(_forbidden_error(forbidden, target_label, label, local_id=str(entry.get("local_id") or "")))
        for ref_index, ref in enumerate(entry.get("related_refs") or []):
            _reference(ref, errors, target_label, f"{label}.related_refs[{ref_index}]", local_ids, entity_types)
        _locations(reader, entry.get("source_locations"), errors, target_label, str(entry.get("local_id") or ""), label, allow_empty=True)
    return errors


def _target_parts(target: Any) -> tuple[str, str]:
    if isinstance(target, dict):
        path, section = target.get("path"), target.get("section")
        return (str(path), str(section)) if isinstance(path, str) and isinstance(section, str) and section else (str(path), "") if isinstance(path, str) else ("", "")
    return "", ""


def _schema_errors(spec: dict[str, Any], batch: Any) -> list[CandidateError]:
    if Draft202012Validator is None:
        return []
    schema_path = spec["root"] / "schemas" / "candidate" / "candidate_batch.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [CandidateError("CANDIDATE_SCHEMA_INVALID", f"candidate schema could not be loaded: {exc}", field="$")]
    validator = Draft202012Validator(schema)
    errors: list[CandidateError] = []
    for exc in sorted(validator.iter_errors(batch), key=lambda item: list(item.path)):
        path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in exc.path)
        schema_path_text = "/" + "/".join(str(part) for part in exc.schema_path)
        errors.append(CandidateError("CANDIDATE_SCHEMA_INVALID", f"{exc.message}; schema_path={schema_path_text}", field=path))
    return errors


def _forbidden_fields(value: Any, forbidden_fields: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden_fields:
                found.add(key)
            found |= _forbidden_fields(child, forbidden_fields)
    elif isinstance(value, list):
        for child in value:
            found |= _forbidden_fields(child, forbidden_fields)
    return found


def _forbidden_error(forbidden: set[str], target: str, field: str, local_id: str = "") -> CandidateError:
    code = "CANDIDATE_LEGACY_IDENTITY_FIELD" if forbidden & LEGACY_IDENTITY_FIELDS else "CANDIDATE_FIELD_FORBIDDEN"
    return CandidateError(code, f"model may not provide {sorted(forbidden)}", target=target, local_id=local_id, field=field)


def _reference(ref: Any, errors: list[CandidateError], target: str, field: str, local_ids: set[str], entity_types: dict[str, Any]) -> None:
    if not isinstance(ref, dict):
        errors.append(CandidateError("ENTITY_REFERENCE_INVALID", "reference must be object", target=target, field=field))
        return
    ref_type = ref.get("ref_type")
    if ref_type == "local":
        local_id = ref.get("local_id")
        if not isinstance(local_id, str) or not local_id:
            errors.append(CandidateError("LOCAL_REFERENCE_INVALID", "local reference needs local_id", target=target, field=field))
        elif local_id not in local_ids:
            errors.append(CandidateError("LOCAL_REFERENCE_UNKNOWN", "local reference points to unknown local_id", target=target, local_id=local_id, field=field))
    elif ref_type == "entity":
        if not isinstance(ref.get("kind"), str) or not isinstance(ref.get("identity"), dict):
            errors.append(CandidateError("ENTITY_REFERENCE_INVALID", "entity reference needs kind and identity", target=target, field=field))
        elif ref["kind"] not in entity_types:
            errors.append(CandidateError("IDENTITY_KIND_UNSUPPORTED", f"unsupported identity kind: {ref['kind']}", target=target, field=field))
    elif ref_type == "symbol":
        if not isinstance(ref.get("kind"), str) or not isinstance(ref.get("qualified_symbol"), str):
            errors.append(CandidateError("ENTITY_REFERENCE_INVALID", "symbol reference needs kind and qualified_symbol", target=target, field=field))
    else:
        errors.append(CandidateError("ENTITY_REFERENCE_INVALID", "ref_type must be local, entity, or symbol", target=target, field=field))


def _identity_with_reference_placeholders(
    spec: dict[str, Any],
    kind: str,
    identity: dict[str, Any],
    errors: list[CandidateError],
    target: str,
    local_id: str,
    label: str,
    local_id_to_kind: dict[str, str],
) -> dict[str, Any]:
    result = dict(identity)
    entity_spec = spec.get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec.get("entity_types"), dict) else {}
    for field_name, allowed in _identity_reference_fields(spec, kind).items():
        value = result.get(field_name)
        if not isinstance(value, dict):
            continue
        _reference(value, errors, target, f"{label}.identity.{field_name}", set(local_id_to_kind), entity_types)
        actual_kind = _static_reference_kind(value, local_id_to_kind)
        if actual_kind and allowed and not any(kind_matches(actual_kind, expected, entity_spec) for expected in allowed):
            errors.append(CandidateError("IDENTITY_REFERENCE_KIND_NOT_ALLOWED", f"{field_name} target kind {actual_kind} not allowed; allowed={allowed}", target=target, local_id=local_id, field=f"{label}.identity.{field_name}"))
        result[field_name] = _reference_placeholder(value)
    return result


def _identity_reference_fields(spec: dict[str, Any], kind: str) -> dict[str, list[str]]:
    entity_spec = spec.get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}
    entity_types = entity_spec.get("entity_types") if isinstance(entity_spec.get("entity_types"), dict) else {}
    config = entity_types.get(kind) if isinstance(entity_types, dict) else None
    refs = config.get("identity_reference_fields") if isinstance(config, dict) and isinstance(config.get("identity_reference_fields"), dict) else {}
    return {str(key): [str(item) for item in value] for key, value in refs.items() if isinstance(value, list)}


def _static_reference_kind(ref: dict[str, Any], local_id_to_kind: dict[str, str]) -> str | None:
    if ref.get("ref_type") == "local" and isinstance(ref.get("local_id"), str):
        return local_id_to_kind.get(str(ref["local_id"]))
    if ref.get("ref_type") in {"entity", "symbol"} and isinstance(ref.get("kind"), str):
        return str(ref["kind"])
    return None


def _reference_placeholder(ref: dict[str, Any]) -> str:
    if ref.get("ref_type") == "local":
        return f"local:{ref.get('local_id')}"
    if ref.get("ref_type") == "symbol":
        return f"symbol:{ref.get('kind')}:{ref.get('qualified_symbol') or ref.get('symbol')}:{ref.get('signature') or ''}"
    return f"entity:{ref.get('kind')}"


def _reference_objects(value: Any, errors: list[CandidateError], target: str, field: str, kind: str, entity_spec: dict[str, Any], local_id_to_kind: dict[str, str]) -> None:
    declarations = reference_declarations(entity_spec, kind) if kind else {}
    for found in iter_reference_values(value, declarations):
        label = f"{field}.{found.path}" if found.path else field
        if found.declaration.cardinality == "single":
            if not isinstance(found.value, dict):
                errors.append(CandidateError("REFERENCE_OBJECT_REQUIRED", f"{found.declaration.path} must be a reference object", target=target, field=label))
                continue
            _reference(found.value, errors, target, label, set(local_id_to_kind), (entity_spec.get("entity_types") or {}))
            _reference_kind_allowed(found.value, found.declaration.allowed, errors, target, label, local_id_to_kind, entity_spec)
        else:
            if not isinstance(found.value, list):
                errors.append(CandidateError("REFERENCE_ARRAY_REQUIRED", f"{found.declaration.path} must be an array of reference objects", target=target, field=label))
                continue
            for index, ref in enumerate(found.value):
                item_label = f"{label}[{index}]"
                if not isinstance(ref, dict):
                    errors.append(CandidateError("REFERENCE_OBJECT_REQUIRED", f"{found.declaration.path} entries must be reference objects", target=target, field=item_label))
                    continue
                _reference(ref, errors, target, item_label, set(local_id_to_kind), (entity_spec.get("entity_types") or {}))
                _reference_kind_allowed(ref, found.declaration.allowed, errors, target, item_label, local_id_to_kind, entity_spec)
    for path, key, _node in iter_reference_like_paths(value):
        if declared_reference_for_path(declarations, path) is None:
            errors.append(CandidateError("REFERENCE_FIELD_UNDECLARED", f"{key} must be declared in entity_types reference_fields or renamed to *_symbol/*_text", target=target, field=f"{field}.{path}"))


def _reference_kind_allowed(ref: dict[str, Any], allowed: tuple[str, ...], errors: list[CandidateError], target: str, field: str, local_id_to_kind: dict[str, str], entity_spec: dict[str, Any]) -> None:
    actual_kind = _static_reference_kind(ref, local_id_to_kind)
    if actual_kind and allowed and not any(kind_matches(actual_kind, expected, entity_spec) for expected in allowed):
        errors.append(CandidateError("REFERENCE_KIND_NOT_ALLOWED", f"reference target kind {actual_kind} not allowed; allowed={list(allowed)}", target=target, field=field))


def _locations(reader: SourceReader, locations: Any, errors: list[CandidateError], target: str, local_id: str, field: str, allow_empty: bool = False) -> None:
    if not isinstance(locations, list) or (not locations and not allow_empty):
        errors.append(CandidateError("SOURCE_LOCATION_INVALID", "source_locations must be non-empty", target=target, local_id=local_id, field=field))
        return
    for index, location in enumerate(locations):
        if not isinstance(location, dict) or set(location) != {"file", "symbol", "start_line", "end_line", "anchor_kind"}:
            errors.append(CandidateError("SOURCE_LOCATION_INVALID", "location requires exactly file/symbol/start_line/end_line/anchor_kind", target=target, local_id=local_id, field=f"{field}.source_locations[{index}]"))
            continue
        try:
            reader.read(str(location["file"])).span(location["start_line"], location["end_line"])
        except (SourceReadError, TypeError) as exc:
            code = exc.code if isinstance(exc, SourceReadError) else "SOURCE_LOCATION_INVALID"
            errors.append(CandidateError(code, str(exc), target=target, local_id=local_id, field=f"{field}.source_locations[{index}]"))


def _identity_evidence(item: dict[str, Any], reader: SourceReader, errors: list[CandidateError], target: str, local_id: str, field: str) -> None:
    identity = item.get("identity") if isinstance(item.get("identity"), dict) else {}
    locations = item.get("source_locations") if isinstance(item.get("source_locations"), list) else []
    source_file = identity.get("source_file") or identity.get("path")
    span = (
        identity.get("declaration_span")
        or identity.get("call_span")
        or identity.get("predicate_span")
        or identity.get("loop_header_span")
        or identity.get("write_span")
        or identity.get("read_span")
        or identity.get("source_span")
    )
    if isinstance(source_file, str) and isinstance(span, dict):
        start, end = span.get("start_line"), span.get("end_line")
        matching = [
            loc for loc in locations
            if isinstance(loc, dict)
            and str(loc.get("file")).replace("\\", "/") == source_file.replace("\\", "/")
            and isinstance(loc.get("start_line"), int)
            and isinstance(loc.get("end_line"), int)
            and isinstance(start, int)
            and isinstance(end, int)
            and int(loc["start_line"]) <= start
            and int(loc["end_line"]) >= end
        ]
        if not matching:
            errors.append(CandidateError("IDENTITY_EVIDENCE_MISMATCH", "identity source/span must be covered by a source_location", target=target, local_id=local_id, field=f"{field}.identity"))
            return
        anchor_text = "\n".join(_safe_span(reader, loc) for loc in matching)
        for key in ("source_name", "callee_symbol", "field_name"):
            value = identity.get(key)
            if isinstance(value, str) and value and value not in anchor_text:
                errors.append(CandidateError("IDENTITY_EVIDENCE_MISMATCH", f"identity.{key} is not present in covered source text", target=target, local_id=local_id, field=f"{field}.identity.{key}"))
        scope_symbol = identity.get("scope_symbol")
        if isinstance(scope_symbol, str) and scope_symbol and not any(isinstance(loc, dict) and loc.get("symbol") == scope_symbol for loc in matching):
            errors.append(CandidateError("IDENTITY_EVIDENCE_MISMATCH", "identity.scope_symbol does not match covered source_location.symbol", target=target, local_id=local_id, field=f"{field}.identity.scope_symbol"))


def _safe_span(reader: SourceReader, location: dict[str, Any]) -> str:
    try:
        return reader.read(str(location["file"])).span(int(location["start_line"]), int(location["end_line"]))
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fast local validation for one candidate JSON batch.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name")
    parser.add_argument("--batch", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        batch = load_json(args.batch)
    except CandidateError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False))
        return 2
    repo = Path(args.repo).resolve()
    errors = validate_candidate_batch(repo, safe_op_name(args.op_name, repo), batch)
    print(json.dumps({"status": "fail" if errors else "pass", "errors": [item.to_dict() for item in errors]}, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
