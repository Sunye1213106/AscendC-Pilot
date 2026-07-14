from __future__ import annotations

import argparse
import os
import sys
import tempfile
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
from understand_operator.scripts.prepare_fact_file import prepare_fact_file


SECTIONS = ("items", "relations", "unresolved")
FORBIDDEN_TEXT = ("<think>", "</think>", "```")


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    text = path.read_text(encoding="utf-8")
    for marker in FORBIDDEN_TEXT:
        if marker in text:
            raise SystemExit(f"FORBIDDEN_GENERATION_MARKER: {path}: {marker}")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"YAML_ROOT_NOT_MAPPING: {path}")
    return data


def _entry_count(batch: dict[str, Any]) -> int:
    return sum(len(batch.get(section) or []) for section in SECTIONS)


def _merge_section(current: list[Any], incoming: list[Any]) -> list[Any]:
    by_id: dict[str, int] = {}
    result = list(current)
    for index, item in enumerate(result):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            by_id[item["id"]] = index
    for item in incoming:
        if not isinstance(item, dict):
            raise SystemExit("BATCH_ENTRY_NOT_MAPPING")
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id in by_id:
            result[by_id[item_id]] = item
        else:
            if isinstance(item_id, str):
                by_id[item_id] = len(result)
            result.append(item)
    return result


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    for marker in FORBIDDEN_TEXT:
        if marker in text:
            raise SystemExit(f"FORBIDDEN_GENERATION_MARKER_AFTER_MERGE: {marker}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        temp_name = handle.name
        handle.write(text)
    os.replace(temp_name, path)


def merge_fact_entries(repo_root: Path, op_name: str, rel: str, batch_path: Path, *, max_entries: int) -> Path:
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        raise SystemExit(f"UO_ROOT_MISSING: {uo_root}")
    target = prepare_fact_file(repo_root, op_name, rel)
    doc = _load_yaml(target)
    batch = _load_yaml(batch_path)
    count = _entry_count(batch)
    if count < 1:
        raise SystemExit("EMPTY_FACT_BATCH")
    if count > max_entries:
        raise SystemExit(f"FACT_BATCH_TOO_LARGE: {count} > {max_entries}")
    for section in SECTIONS:
        current = doc.get(section) or []
        incoming = batch.get(section) or []
        if not isinstance(current, list) or not isinstance(incoming, list):
            raise SystemExit(f"SECTION_NOT_LIST: {section}")
        doc[section] = _merge_section(current, incoming)
    _atomic_write_yaml(target, doc)
    _load_yaml(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge a small fact batch into a UO YAML fact file atomically.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--path", required=True, help="KB-relative target fact path from spec/file_catalog.yaml")
    parser.add_argument("--batch", required=True, type=Path, help="YAML batch containing items/relations/unresolved")
    parser.add_argument("--max-entries", type=int, default=10, help="Maximum entries per merge batch")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    target = merge_fact_entries(repo_root, op_name, args.path, args.batch, max_entries=args.max_entries)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
