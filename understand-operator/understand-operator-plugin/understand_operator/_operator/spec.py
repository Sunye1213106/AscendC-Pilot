from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


SPEC_REL = Path("skills") / "understand-operator" / "spec"


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def spec_root(root: Path | None = None) -> Path:
    base = root or plugin_root()
    candidate = base / SPEC_REL
    if candidate.exists():
        return candidate
    return plugin_root() / SPEC_REL


def read_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_spec(root: Path | None = None) -> dict[str, Any]:
    spec = spec_root(root)
    return {
        "root": spec,
        "manifest": read_yaml(spec / "manifest.yaml"),
        "file_catalog": read_yaml(spec / "file_catalog.yaml"),
        "ownership": read_yaml(spec / "ownership.yaml"),
        "stage_contracts": read_yaml(spec / "stage_contracts.yaml"),
        "stable_ids": read_yaml(spec / "stable_ids.yaml"),
        "relation_types": read_yaml(spec / "relation_types.yaml"),
        "entity_types": read_yaml(spec / "entity_types.yaml"),
        "source_anchor_rules": read_yaml(spec / "source_anchor_rules.yaml"),
    }


def spec_files(root: Path | None = None) -> list[Path]:
    spec = spec_root(root)
    return sorted(path for path in spec.rglob("*") if path.is_file() and path.suffix in {".yaml", ".json"})


def spec_bundle_hash(root: Path | None = None) -> str:
    digest = hashlib.sha256()
    spec = spec_root(root)
    for path in spec_files(root):
        rel = path.relative_to(spec).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def catalog_entries(spec: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = spec.get("file_catalog") or {}
    entries = catalog.get("files") if isinstance(catalog, dict) else []
    return [entry for entry in entries if isinstance(entry, dict)]
