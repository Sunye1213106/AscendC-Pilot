from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError: yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.candidate import CandidateError, load_json, prefix_for_kind, source_anchor, stable_id
from understand_operator._operator.source_reader import SourceReader
from understand_operator.scripts.prepare_fact_file import prepare_fact_file
from understand_operator.scripts.validate_candidate_batch import _target_parts, validate_candidate_batch


def compile_candidate_facts(repo_root: Path, op_name: str, batch: Any) -> list[CandidateError]:
    errors = validate_candidate_batch(repo_root, op_name, batch)
    if errors: return errors
    uo_root = existing_operator_root(repo_root, op_name); target, section = _target_parts(batch["target"]); reader = SourceReader(repo_root)
    key_index_path = uo_root / "indexes" / "fact_keys.json"; key_index = _read_json(key_index_path)
    for item in batch["items"]:
        key_index.setdefault(item["fact_key"], stable_id(prefix_for_kind(item["kind"]), item["fact_key"]))
    unknown = [key for relation in batch["relations"] for key in (relation["source_fact_key"], relation["target_fact_key"]) if key not in key_index]
    if unknown: return [CandidateError("FACT_KEY_REFERENCE_UNKNOWN", "relation endpoint fact_key is unknown", target=target, fact_key=key) for key in sorted(set(unknown))]
    items = [_materialize_item(item, reader, key_index) for item in batch["items"]]
    relations = [_materialize_relation(relation, reader, key_index) for relation in batch["relations"]]
    unresolved = [_materialize_unresolved(entry, reader, key_index) for entry in batch["unresolved"]]
    formal = prepare_fact_file(repo_root, op_name, target)
    doc = _load_yaml(formal)
    if section:
        sections = doc.setdefault("sections", {}); content = sections.setdefault(section, {"items": [], "relations": [], "unresolved": []})
        if not isinstance(content, dict): return [CandidateError("PARTITION_SECTION_INVALID", "target section is not a mapping", target=target)]
    else: content = doc
    _merge_by_id(content, "items", items); _merge_by_id(content, "relations", relations); _merge_by_id(content, "unresolved", unresolved)
    _atomic_yaml(formal, doc); _atomic_json(key_index_path, key_index)
    return []


def _materialize_item(item: dict[str, Any], reader: SourceReader, keys: dict[str, str]) -> dict[str, Any]:
    key = item["fact_key"]; fact_id = keys.setdefault(key, stable_id(prefix_for_kind(item["kind"]), key))
    result = {"id": fact_id, "kind": item["kind"], **item.get("fields", {}), "status": "confirmed", "sources": [source_anchor(reader, value) for value in item["source_locations"]]}
    if "name" in item: result["name"] = item["name"]
    return result


def _materialize_relation(relation: dict[str, Any], reader: SourceReader, keys: dict[str, str]) -> dict[str, Any]:
    return {"id": stable_id("REL", f"{relation['type']}\0{keys[relation['source_fact_key']]}\0{keys[relation['target_fact_key']]}\0{relation['relation_key']}"), "type": relation["type"], "source_id": keys[relation["source_fact_key"]], "target_id": keys[relation["target_fact_key"]], **relation.get("fields", {}), "status": "confirmed", "sources": [source_anchor(reader, value) for value in relation["source_locations"]]}


def _materialize_unresolved(entry: dict[str, Any], reader: SourceReader, keys: dict[str, str]) -> dict[str, Any]:
    sources = [source_anchor(reader, value) for value in entry.get("source_locations") or []]
    return {"id": stable_id("UNRESOLVED", entry["unresolved_key"]), "question": entry["description"], "reason": entry["category"], "owner": "candidate-compiler", "blocked_items": [keys[key] for key in entry.get("related_fact_keys") or [] if key in keys], "candidate_sources": sources}


def _read_json(path: Path) -> dict[str, str]:
    if not path.exists(): return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8")); return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError): return {}


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}; return data if isinstance(data, dict) else {}


def _merge_by_id(doc: dict[str, Any], section: str, additions: list[dict[str, Any]]) -> None:
    existing = doc.setdefault(section, []); positions = {entry.get("id"): index for index, entry in enumerate(existing) if isinstance(entry, dict)}
    for entry in additions:
        if entry["id"] in positions: existing[positions[entry["id"]]] = entry
        else: positions[entry["id"]] = len(existing); existing.append(entry)


def _atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(path, yaml.safe_dump(value, sort_keys=False, allow_unicode=True))


def _atomic_json(path: Path, value: dict[str, str]) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle: handle.write(text); temporary = Path(handle.name)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile one LLM candidate JSON batch into formal Facts."); parser.add_argument("repo", nargs="?", default="."); parser.add_argument("--op-name"); parser.add_argument("--batch", required=True, type=Path); args = parser.parse_args(argv)
    repo = Path(args.repo).resolve(); op_name = safe_op_name(args.op_name, repo)
    try: batch = load_json(args.batch)
    except CandidateError as exc: print(json.dumps(exc.to_dict(), ensure_ascii=False)); return 2
    errors = compile_candidate_facts(repo, op_name, batch); print(json.dumps({"status": "fail" if errors else "pass", "errors": [item.to_dict() for item in errors]}, ensure_ascii=False, indent=2)); return 2 if errors else 0

if __name__ == "__main__": raise SystemExit(main())
