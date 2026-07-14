from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError: yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.candidate import CandidateError, FORBIDDEN_ITEM_FIELDS, FORBIDDEN_RELATION_FIELDS, load_json
from understand_operator._operator.source_reader import SourceReadError, SourceReader
from understand_operator._operator.spec import catalog_entries, load_spec


def validate_candidate_batch(repo_root: Path, op_name: str, batch: Any) -> list[CandidateError]:
    errors: list[CandidateError] = []
    if not isinstance(batch, dict): return [CandidateError("CANDIDATE_ROOT_INVALID", "candidate batch must be a JSON object")]
    required = {"version", "task", "target", "items", "relations", "unresolved"}
    unknown = set(batch) - required
    if unknown: errors.append(CandidateError("CANDIDATE_FIELD_FORBIDDEN", f"unknown top-level fields: {sorted(unknown)}"))
    if set(batch) & required != required: errors.append(CandidateError("CANDIDATE_FIELD_MISSING", "version, task, target, items, relations, unresolved are required")); return errors
    task, target = batch["task"], batch["target"]
    if batch["version"] != 1: errors.append(CandidateError("CANDIDATE_VERSION_INVALID", "version must be 1", target=str(target)))
    if not isinstance(task, dict) or set(task) != {"run_id", "stage", "owner", "task_id"}: errors.append(CandidateError("CANDIDATE_TASK_INVALID", "task must contain exactly run_id/stage/owner/task_id", target=str(target))); return errors
    target_path, target_section = _target_parts(target)
    if not target_path: return errors + [CandidateError("CANDIDATE_TARGET_INVALID", "target must be path#sections/name or {path, section}")]
    spec = load_spec(); entry = next((item for item in catalog_entries(spec) if item.get("path") == target_path), None); allowed_kinds: set[str] = set()
    if not entry: errors.append(CandidateError("CANDIDATE_TARGET_INVALID", "target is not a formal fact catalog path", target=target))
    else:
        if entry.get("owner") != task["owner"]: errors.append(CandidateError("CANDIDATE_OWNER_FORBIDDEN", f"{task['owner']} may not write {target_path}", target=target_path))
        if yaml is not None and entry.get("schema"):
            schema_rel = entry.get("section_schemas", {}).get(target_section, entry["schema"]) if target_section else entry["schema"]
            schema = yaml.safe_load((spec["root"] / str(schema_rel)).read_text(encoding="utf-8")) or {}
            allowed_kinds = {str(value) for value in schema.get("item_kind_enum") or []}
    if task["stage"] not in {"step1", "step2", "step3"}: errors.append(CandidateError("CANDIDATE_STAGE_INVALID", "stage must be step1, step2, or step3", target=target))
    reader = SourceReader(repo_root); keys: set[str] = set()
    for index, item in enumerate(batch["items"] if isinstance(batch["items"], list) else []):
        label = f"items[{index}]"
        if not isinstance(item, dict): errors.append(CandidateError("CANDIDATE_ITEM_INVALID", "item must be object", target=target, field=label)); continue
        key = item.get("fact_key"); forbidden = (set(item) | set(item.get("fields", {}) if isinstance(item.get("fields"), dict) else {})) & FORBIDDEN_ITEM_FIELDS
        if forbidden: errors.append(CandidateError("CANDIDATE_FIELD_FORBIDDEN", f"model may not provide {sorted(forbidden)}", target=target, fact_key=str(key or ""), field=label))
        if not isinstance(key, str) or not key: errors.append(CandidateError("FACT_KEY_INVALID", "fact_key is required", target=target, field=label)); continue
        if key in keys: errors.append(CandidateError("FACT_KEY_DUPLICATE", "fact_key is duplicated in this batch", target=target, fact_key=key))
        keys.add(key)
        if not isinstance(item.get("kind"), str) or not isinstance(item.get("fields"), dict): errors.append(CandidateError("CANDIDATE_ITEM_INVALID", "kind and fields are required", target=target, fact_key=key))
        elif allowed_kinds and item["kind"] not in allowed_kinds: errors.append(CandidateError("CANDIDATE_KIND_INVALID", f"kind {item['kind']!r} is not allowed by target schema", target=target, fact_key=key, field=f"{label}.kind"))
        _locations(reader, item.get("source_locations"), errors, target, key, label)
    relation_keys: set[str] = set(); relation_types = set((spec["relation_types"].get("relation_types") or {}).keys())
    for index, relation in enumerate(batch["relations"] if isinstance(batch["relations"], list) else []):
        label = f"relations[{index}]"
        if not isinstance(relation, dict): errors.append(CandidateError("CANDIDATE_RELATION_INVALID", "relation must be object", target=target, field=label)); continue
        key = relation.get("relation_key"); forbidden = (set(relation) | set(relation.get("fields", {}) if isinstance(relation.get("fields"), dict) else {})) & FORBIDDEN_RELATION_FIELDS
        if forbidden: errors.append(CandidateError("CANDIDATE_FIELD_FORBIDDEN", f"model may not provide {sorted(forbidden)}", target=target, relation_key=str(key or ""), field=label))
        if not isinstance(key, str) or not key: errors.append(CandidateError("RELATION_KEY_INVALID", "relation_key is required", target=target, field=label)); continue
        if key in relation_keys: errors.append(CandidateError("RELATION_KEY_DUPLICATE", "relation_key is duplicated", target=target, relation_key=key))
        relation_keys.add(key)
        if relation.get("type") not in relation_types: errors.append(CandidateError("RELATION_TYPE_INVALID", "relation type is not in spec", target=target, relation_key=key))
        if not isinstance(relation.get("source_fact_key"), str) or not isinstance(relation.get("target_fact_key"), str): errors.append(CandidateError("RELATION_ENDPOINT_KEY_INVALID", "source_fact_key and target_fact_key are required", target=target, relation_key=key))
        _locations(reader, relation.get("source_locations"), errors, target, "", label, key)
    if not all(isinstance(batch.get(section), list) for section in ("items", "relations", "unresolved")): errors.append(CandidateError("CANDIDATE_SECTION_INVALID", "items, relations, unresolved must be arrays", target=target))
    return errors


def _target_parts(target: Any) -> tuple[str, str]:
    if isinstance(target, dict):
        path, section = target.get("path"), target.get("section")
        return (str(path), str(section)) if isinstance(path, str) and isinstance(section, str) and section else ("", "")
    if isinstance(target, str):
        path, marker, pointer = target.partition("#")
        if not marker: return path, ""
        prefix = "/sections/"
        return (path, pointer[len(prefix):]) if pointer.startswith(prefix) else ("", "")
    return "", ""


def _locations(reader: SourceReader, locations: Any, errors: list[CandidateError], target: str, fact_key: str, field: str, relation_key: str = "") -> None:
    if not isinstance(locations, list) or not locations: errors.append(CandidateError("SOURCE_LOCATION_INVALID", "source_locations must be non-empty", target=target, fact_key=fact_key, relation_key=relation_key, field=field)); return
    for index, location in enumerate(locations):
        if not isinstance(location, dict) or set(location) != {"file", "symbol", "start_line", "end_line", "anchor_kind"}: errors.append(CandidateError("SOURCE_LOCATION_INVALID", "location requires exactly file/symbol/start_line/end_line/anchor_kind", target=target, fact_key=fact_key, relation_key=relation_key, field=f"{field}.source_locations[{index}]")); continue
        try: reader.read(str(location["file"])).span(location["start_line"], location["end_line"])
        except (SourceReadError, TypeError) as exc:
            code = exc.code if isinstance(exc, SourceReadError) else "SOURCE_LOCATION_INVALID"; errors.append(CandidateError(code, str(exc), target=target, fact_key=fact_key, relation_key=relation_key, field=f"{field}.source_locations[{index}]"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fast local validation for one candidate JSON batch."); parser.add_argument("repo", nargs="?", default="."); parser.add_argument("--op-name"); parser.add_argument("--batch", required=True, type=Path); args = parser.parse_args(argv)
    try: batch = load_json(args.batch)
    except CandidateError as exc: print(json.dumps(exc.to_dict(), ensure_ascii=False)); return 2
    errors = validate_candidate_batch(Path(args.repo).resolve(), safe_op_name(args.op_name, Path(args.repo).resolve()), batch)
    print(json.dumps({"status": "fail" if errors else "pass", "errors": [item.to_dict() for item in errors]}, ensure_ascii=False, indent=2)); return 2 if errors else 0

if __name__ == "__main__": raise SystemExit(main())
