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
from understand_operator._operator.catalog import CatalogMatchError, match_catalog_entry
from understand_operator._operator.run_context import active_run_id, read_yaml_mapping
from understand_operator._operator.spec import load_spec, spec_bundle_hash


def _read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _catalog_entry(rel: str) -> dict[str, Any]:
    rel = rel.replace("\\", "/")
    try:
        match = match_catalog_entry(load_spec(), rel, writable_only=True)
    except CatalogMatchError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from exc
    if not match:
        raise SystemExit(f"FACT_PATH_NOT_IN_CATALOG: {rel}")
    return match.entry


def _phase0_receipt_snapshot(uo_root: Path) -> dict[str, str]:
    try:
        run_id = active_run_id(uo_root)
    except RuntimeError as exc:
        raise SystemExit(f"PHASE0_NOT_FINALIZED: {exc}") from exc
    rel = Path("runs") / run_id / "phase0" / "receipt.yaml"
    receipt = read_yaml_mapping(uo_root / rel)
    if receipt.get("status") != "pass":
        raise SystemExit(f"PHASE0_NOT_FINALIZED: {rel.as_posix()} status is not pass")
    snapshot = receipt.get("snapshot") if isinstance(receipt.get("snapshot"), dict) else {}
    if snapshot.get("run_id") != run_id:
        raise SystemExit(f"PHASE0_RECEIPT_INVALID: {rel.as_posix()} snapshot.run_id mismatch")
    if snapshot.get("spec_bundle_hash") != spec_bundle_hash():
        raise SystemExit(f"PHASE0_RECEIPT_INVALID: {rel.as_posix()} spec_bundle_hash mismatch")
    source_snapshot_id = str(snapshot.get("source_snapshot_id") or "")
    if not source_snapshot_id.startswith("SOURCE_") or source_snapshot_id == "SOURCE_PENDING":
        raise SystemExit(f"PHASE0_RECEIPT_INVALID: {rel.as_posix()} source_snapshot_id is not finalized")
    return {
        "run_id": run_id,
        "source_snapshot_id": source_snapshot_id,
        "source_revision": str(snapshot.get("source_revision") or receipt.get("source_revision") or "unknown"),
        "spec_bundle_hash": str(snapshot.get("spec_bundle_hash")),
    }


def prepare_fact_file(repo_root: Path, op_name: str, rel: str, *, force: bool = False) -> Path:
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        raise SystemExit(f"UO_ROOT_MISSING: {uo_root}")
    entry = _catalog_entry(rel)
    target = uo_root / rel
    snapshot = _phase0_receipt_snapshot(uo_root)
    if target.exists() and not force:
        current = _read_yaml(target)
        current_snapshot = current.get("snapshot") if isinstance(current.get("snapshot"), dict) else {}
        if current_snapshot == snapshot:
            return target
        if document_has_fact_content(current):
            raise SystemExit(f"FACT_FILE_SNAPSHOT_STALE: {rel} does not match finalized Phase 0 receipt")
    payload = {
        "version": 1,
        "artifact": {
            "type": entry.get("artifact_type"),
            "schema_version": 1,
            "owner": entry.get("owner"),
        },
        "snapshot": snapshot,
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    section_schemas = entry.get("section_schemas") if isinstance(entry.get("section_schemas"), dict) else {}
    if section_schemas:
        payload.pop("items"); payload.pop("relations"); payload.pop("unresolved")
        payload["sections"] = {str(name): {"items": [], "relations": [], "unresolved": []} for name in section_schemas}
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_yaml(target, payload)
    return target


def document_has_fact_content(doc: dict[str, object]) -> bool:
    for key in ("items", "relations", "unresolved"):
        value = doc.get(key)
        if isinstance(value, list) and value:
            return True
    sections = doc.get("sections")
    if isinstance(sections, dict):
        for section in sections.values():
            if not isinstance(section, dict):
                continue
            for key in ("items", "relations", "unresolved"):
                value = section.get(key)
                if isinstance(value, list) and value:
                    return True
    return False


def _atomic_yaml(path: Path, payload: dict[str, object]) -> None:
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp = Path(handle.name)
    os.replace(temp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a schema/catalog-valid Understand Operator fact skeleton.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--path", required=True, help="KB-relative fact path from spec/file_catalog.yaml")
    parser.add_argument("--force", action="store_true", help="Overwrite the existing file with an empty skeleton.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    target = prepare_fact_file(repo_root, op_name, args.path, force=args.force)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
