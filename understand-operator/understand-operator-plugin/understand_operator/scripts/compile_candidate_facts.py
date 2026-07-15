from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.candidate import CandidateError, load_json, source_anchor, stable_id
from understand_operator._operator.fact_linker import LinkResult, resolve_entity_ref, resolve_reference_fields, resolve_structured_identity
from understand_operator._operator.fact_registry import build_fact_registry
from understand_operator._operator.identity import relation_stable_id
from understand_operator._operator.run_context import assert_candidate_run_current, source_root_for_operator
from understand_operator._operator.source_reader import SourceReader
from understand_operator._operator.spec import load_spec
from understand_operator.scripts.prepare_fact_file import prepare_fact_file
from understand_operator.scripts.validate_candidate_batch import _target_parts, validate_candidate_batch


def compile_candidate_facts(repo_root: Path, op_name: str, batch: Any) -> list[CandidateError]:
    if yaml is None:
        return [CandidateError("YAML_IMPORT_ERROR", "PyYAML is required")]
    errors = validate_candidate_batch(repo_root, op_name, batch)
    if errors:
        return errors
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, op_name)
    target, section = _target_parts(batch["target"])
    task = batch.get("task") if isinstance(batch.get("task"), dict) else {}
    run_check = assert_candidate_run_current(uo_root, str(task.get("run_id") or ""))
    if not run_check.ok:
        return [CandidateError("CANDIDATE_RUN_ID_MISMATCH", run_check.message, target=target, field="task.run_id")]
    reader = SourceReader(source_root_for_operator(repo_root, uo_root, run_check.current_run_id))
    registry = build_fact_registry(uo_root)
    spec = load_spec()
    entity_spec = spec.get("entity_types") if isinstance(spec.get("entity_types"), dict) else {}

    local_symbols: dict[str, str] = {}
    local_kinds: dict[str, str] = {}
    canonical_to_local: dict[str, tuple[str, str]] = {}
    materialized_items: list[dict[str, Any]] = []
    pending = [(index, item) for index, item in enumerate(batch["items"])]
    delayed: list[tuple[int, dict[str, Any], str]] = []
    while pending:
        progressed = False
        next_pending: list[tuple[int, dict[str, Any]]] = []
        delayed = []
        for index, item in pending:
            structured = resolve_structured_identity(
                str(item.get("kind") or ""),
                item.get("identity") or {},
                local_symbols=local_symbols,
                local_kinds=local_kinds,
                registry=registry,
                repo_root=reader.repo_root,
                entity_spec=entity_spec,
                require_registered=False,
            )
            if structured.status != "resolved" or not structured.resolved_identity:
                error = CandidateError(
                    structured.reason or "ENTITY_IDENTITY_REFERENCE_UNRESOLVED",
                    f"identity references could not be resolved; actual={structured.kind}",
                    target=target,
                    local_id=str(item.get("local_id") or ""),
                    field=f"items[{index}].identity",
                )
                if error.code in {"ENTITY_IDENTITY_REFERENCE_UNRESOLVED", "LOCAL_REFERENCE_UNKNOWN"}:
                    next_pending.append((index, item))
                    delayed.append((index, item, error.message))
                    continue
                return [error]
            resolved = structured.resolved_identity
            item_for_identity = {**item, "identity": structured.normalized_input or item.get("identity") or {}}
            previous = canonical_to_local.get(resolved.canonical_key)
            local_id = str(item.get("local_id") or "")
            if previous and previous[0] != local_id:
                message = f"duplicate canonical identity first_local_id={previous[0]} second_local_id={local_id} canonical_key={resolved.canonical_key} stable_id={resolved.stable_id}"
                return [CandidateError("CANDIDATE_IDENTITY_DUPLICATE", message, target=target, local_id=local_id, field=f"items[{index}]")]
            canonical_to_local[resolved.canonical_key] = (local_id, resolved.stable_id)
            fact = _materialize_item(item_for_identity, reader, resolved)
            local_symbols[str(item["local_id"])] = fact["id"]
            local_kinds[str(item["local_id"])] = str(item["kind"])
            materialized_items.append(fact)
            registry.add(fact)
            progressed = True
        if not next_pending:
            break
        if not progressed:
            return [
                CandidateError(
                    "ENTITY_IDENTITY_REFERENCE_UNRESOLVED",
                    f"identity references could not be resolved: {message}",
                    target=target,
                    local_id=str(item.get("local_id") or ""),
                    field=f"items[{index}].identity",
                )
                for index, item, message in delayed
            ]
        pending = next_pending

    resolved_items: list[dict[str, Any]] = []
    resolution_errors: list[CandidateError] = []
    for index, item in enumerate(materialized_items):
        resolved_fields, failures = resolve_reference_fields(
            item,
            local_symbols=local_symbols,
            local_kinds=local_kinds,
            registry=registry,
            repo_root=reader.repo_root,
            kind=str(item.get("kind") or ""),
            entity_spec=entity_spec,
            path=f"items[{index}]",
        )
        for failure in failures:
            resolution_errors.append(_link_error(failure, target, field=str(failure.get("path") or f"items[{index}]")))
        resolved_items.append(resolved_fields)

    materialized_relations: list[dict[str, Any]] = []
    for index, relation in enumerate(batch["relations"]):
        source = resolve_entity_ref(relation["source"], local_symbols=local_symbols, local_kinds=local_kinds, registry=registry, repo_root=reader.repo_root, entity_spec=entity_spec)
        target_ref = resolve_entity_ref(relation["target"], local_symbols=local_symbols, local_kinds=local_kinds, registry=registry, repo_root=reader.repo_root, entity_spec=entity_spec)
        if source.status != "resolved":
            resolution_errors.append(_link_result_error(source, target, f"relations[{index}].source"))
        if target_ref.status != "resolved":
            resolution_errors.append(_link_result_error(target_ref, target, f"relations[{index}].target"))
        resolved_fields, failures = resolve_reference_fields(
            relation.get("fields") or {},
            local_symbols=local_symbols,
            local_kinds=local_kinds,
            registry=registry,
            repo_root=reader.repo_root,
            kind="",
            entity_spec=entity_spec,
            path=f"relations[{index}].fields",
        )
        for failure in failures:
            resolution_errors.append(_link_error(failure, target, field=str(failure.get("path") or f"relations[{index}].fields")))
        if source.status == "resolved" and target_ref.status == "resolved":
            relation_error = _relation_identity_error(spec, relation, resolved_fields, target, index)
            if relation_error:
                resolution_errors.append(relation_error)
            else:
                materialized_relations.append(_materialize_relation(spec, relation, reader, str(source.stable_id), str(target_ref.stable_id), resolved_fields))

    materialized_unresolved = [_materialize_unresolved(entry, reader, local_symbols, local_kinds, registry, reader.repo_root, entity_spec, target, index, resolution_errors) for index, entry in enumerate(batch["unresolved"])]
    materialized_unresolved = [entry for entry in materialized_unresolved if entry is not None]
    if resolution_errors:
        return resolution_errors

    formal = prepare_fact_file(repo_root, op_name, target)
    before_hash = _file_hash(formal)
    doc = _load_yaml(formal)
    content = _target_content(doc, section)
    if content is None:
        return [CandidateError("PARTITION_SECTION_INVALID", "target section is not a mapping", target=target)]
    _merge_by_id(content, "items", resolved_items)
    _merge_by_id(content, "relations", materialized_relations)
    _merge_by_id(content, "unresolved", materialized_unresolved)
    if before_hash != _file_hash(formal):
        return [CandidateError("TARGET_CHANGED_DURING_COMPILE", "target formal fact file changed during compile", target=target)]
    _atomic_yaml(formal, doc)
    return []


def _materialize_item(item: dict[str, Any], reader: SourceReader, resolved: Any) -> dict[str, Any]:
    fields = enrich_deterministic_fields(str(item["kind"]), resolved.normalized_identity, item.get("fields") or {}, reader)
    result = {
        "id": resolved.stable_id,
        "kind": item["kind"],
        **fields,
        "status": "confirmed",
        "identity": {
            "version": resolved.identity_version,
            "canonical_key": resolved.canonical_key,
            "normalized": resolved.normalized_identity,
        },
        "sources": [source_anchor(reader, value) for value in item["source_locations"]],
    }
    if "name" in item:
        result["name"] = item["name"]
    return result


def enrich_deterministic_fields(
    kind: str,
    normalized_identity: dict[str, object],
    fields: dict[str, object],
    source_reader: SourceReader,
) -> dict[str, object]:
    result = dict(fields)
    return result


def _materialize_relation(spec: dict[str, Any], relation: dict[str, Any], reader: SourceReader, source_id: str, target_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    qualifier = _relation_identity_material(spec, str(relation["type"]), fields)
    return {
        "id": relation_stable_id(str(relation["type"]), source_id, target_id, qualifier),
        "type": relation["type"],
        "source_id": source_id,
        "target_id": target_id,
        **fields,
        "status": "confirmed",
        "sources": [source_anchor(reader, value) for value in relation["source_locations"]],
    }


def _relation_identity_error(spec: dict[str, Any], relation: dict[str, Any], fields: dict[str, Any], target: str, index: int) -> CandidateError | None:
    rtype = str(relation.get("type") or "")
    for key in _relation_identity_fields(spec, rtype):
        if fields.get(key) in (None, "", []):
            return CandidateError("RELATION_IDENTITY_FIELD_MISSING", f"relation {rtype} requires identity field {key}", target=target, field=f"relations[{index}].fields.{key}")
    return None


def _relation_identity_material(spec: dict[str, Any], relation_type: str, fields: dict[str, Any]) -> dict[str, Any] | str:
    keys = _relation_identity_fields(spec, relation_type)
    if keys:
        return {key: fields.get(key) for key in keys}
    return fields.get("qualifier") if isinstance(fields, dict) else ""


def _relation_identity_fields(spec: dict[str, Any], relation_type: str) -> list[str]:
    rule = ((spec.get("relation_types") or {}).get("relation_types") or {}).get(relation_type)
    if isinstance(rule, dict) and isinstance(rule.get("identity_fields"), list):
        return [str(item) for item in rule["identity_fields"]]
    return []


def _materialize_unresolved(
    entry: dict[str, Any],
    reader: SourceReader,
    local_symbols: dict[str, str],
    local_kinds: dict[str, str],
    registry: Any,
    repo_root: Path,
    entity_spec: dict[str, Any],
    target: str,
    index: int,
    errors: list[CandidateError],
) -> dict[str, Any] | None:
    blocked: list[str] = []
    for ref_index, ref in enumerate(entry.get("related_refs") or []):
        result = resolve_entity_ref(ref, local_symbols=local_symbols, local_kinds=local_kinds, registry=registry, repo_root=repo_root, entity_spec=entity_spec)
        if result.status == "resolved" and result.stable_id:
            blocked.append(result.stable_id)
        elif result.status == "ambiguous":
            errors.append(_link_result_error(result, target, f"unresolved[{index}].related_refs[{ref_index}]"))
    sources = [source_anchor(reader, value) for value in entry.get("source_locations") or []]
    material = "\0".join((str(entry.get("local_id") or index), str(entry.get("category") or ""), str(entry.get("description") or "")))
    return {
        "id": stable_id("UNRESOLVED", material),
        "question": entry["description"],
        "reason": entry["category"],
        "owner": "candidate-compiler",
        "blocked_items": sorted(set(blocked)),
        "candidate_sources": sources,
    }


def _target_content(doc: dict[str, Any], section: str) -> dict[str, Any] | None:
    if section:
        sections = doc.setdefault("sections", {})
        if not isinstance(sections, dict):
            return None
        content = sections.setdefault(section, {"items": [], "relations": [], "unresolved": []})
        return content if isinstance(content, dict) else None
    return doc


def _link_result_error(result: LinkResult, target: str, field: str) -> CandidateError:
    reason = result.reason or ("ENTITY_REFERENCE_AMBIGUOUS" if result.status == "ambiguous" else "ENTITY_REFERENCE_UNRESOLVED")
    return CandidateError(reason, f"{result.status} reference at {field}", target=target, field=field)


def _link_error(failure: dict[str, Any], target: str, field: str) -> CandidateError:
    reason = str(failure.get("reason") or ("ENTITY_REFERENCE_AMBIGUOUS" if failure.get("status") == "ambiguous" else "ENTITY_REFERENCE_UNRESOLVED"))
    return CandidateError(reason, f"{failure.get('status')} reference at {field}", target=target, field=field)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _merge_by_id(doc: dict[str, Any], section: str, additions: list[dict[str, Any]]) -> None:
    existing = doc.setdefault(section, [])
    positions = {entry.get("id"): index for index, entry in enumerate(existing) if isinstance(entry, dict)}
    for entry in additions:
        if entry["id"] in positions:
            existing[positions[entry["id"]]] = entry
        else:
            positions[entry["id"]] = len(existing)
            existing.append(entry)


def _atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(path, yaml.safe_dump(value, sort_keys=False, allow_unicode=True))


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _file_hash(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile one LLM candidate JSON batch into formal Facts.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name")
    parser.add_argument("--batch", required=True, type=Path)
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo)
    try:
        batch = load_json(args.batch)
    except CandidateError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False))
        return 2
    errors = compile_candidate_facts(repo, op_name, batch)
    print(json.dumps({"status": "fail" if errors else "pass", "errors": [item.to_dict() for item in errors]}, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
