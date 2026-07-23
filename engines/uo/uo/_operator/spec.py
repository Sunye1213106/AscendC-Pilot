from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


SPEC_REL = Path("spec")
BUNDLE_NAME = "bundle.yaml"


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


def _read_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = read_yaml(path)
    return data if isinstance(data, dict) else {}


def load_bundle(root: Path | None = None) -> dict[str, Any]:
    return _read_optional_yaml(spec_root(root) / BUNDLE_NAME)


def hash_input_rels(root: Path | None = None) -> list[str]:
    """Relative paths (posix) that participate in spec_bundle_hash."""
    bundle = load_bundle(root)
    inputs = bundle.get("hash_inputs")
    if isinstance(inputs, list) and inputs:
        return [str(item).replace("\\", "/").lstrip("./") for item in inputs if str(item).strip()]
    # Safe default if bundle.yaml is missing/broken.
    return [
        "ownership.yaml",
        "kb_layout.yaml",
        "schemas/diff/index.schema.yaml",
        "schemas/diff/change_set.schema.yaml",
        "schemas/diff/impact.schema.yaml",
        "schemas/diff/unresolved.schema.yaml",
    ]


def load_spec(root: Path | None = None) -> dict[str, Any]:
    """Load active spec documents. Missing optional legacy files return {}."""
    spec = spec_root(root)
    return {
        "root": spec,
        "bundle": load_bundle(root),
        "ownership": _read_optional_yaml(spec / "ownership.yaml"),
        "kb_layout": _read_optional_yaml(spec / "kb_layout.yaml"),
        # Legacy keys kept empty so old helper modules do not crash on import.
        "manifest": {},
        "file_catalog": {},
        "stage_contracts": {},
        "stable_ids": {},
        "relation_types": {},
        "entity_types": {},
        "source_anchor_rules": {},
    }


def spec_files(root: Path | None = None) -> list[Path]:
    """Files that participate in the bundle hash (missing files are skipped)."""
    spec = spec_root(root)
    out: list[Path] = []
    for rel in hash_input_rels(root):
        path = spec / rel
        if path.is_file():
            out.append(path)
    return out


def spec_bundle_hash(root: Path | None = None) -> str:
    digest = hashlib.sha256()
    spec = spec_root(root)
    # Include the declared input list so reordering/removing inputs changes the hash.
    for rel in hash_input_rels(root):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        path = spec / rel
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def catalog_entries(spec: dict[str, Any]) -> list[dict[str, Any]]:
    layout = spec.get("kb_layout") or {}
    entries = layout.get("artifacts") if isinstance(layout, dict) else []
    return [entry for entry in entries if isinstance(entry, dict)]
