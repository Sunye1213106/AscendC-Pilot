from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from understand_operator._operator.spec import spec_bundle_hash

ARTIFACT_DIR = ".understand-operator"
REQUIRED_TILING_ARCHIVE_FILES: list[str] = []

def safe_op_name(name: str | None, repo_root: Path) -> str:
    raw = (name or "").strip() or repo_root.name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return cleaned or "unknown_operator"


def operator_root(repo_root: Path, op_name: str) -> Path:
    path = repo_root / ARTIFACT_DIR / op_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def existing_operator_root(repo_root: Path, op_name: str) -> Path:
    """Return the expected KB root without creating an empty KB directory."""
    return repo_root / ARTIFACT_DIR / op_name


def resolve_existing_operator_root(repo_root: Path, op_name: str) -> tuple[str, Path] | None:
    """Resolve an existing KB by manifest metadata and terminology aliases."""
    exact = existing_operator_root(repo_root, op_name)
    if (exact / "manifest.yaml").exists():
        return op_name, exact

    kb_parent = repo_root / ARTIFACT_DIR
    if not kb_parent.exists():
        return None
    token = op_name.strip().lower()
    matches: list[tuple[str, Path]] = []
    for candidate in kb_parent.iterdir():
        if not candidate.is_dir() or not (candidate / "manifest.yaml").exists():
            continue
        aliases = {alias.lower() for alias in _default_operator_aliases(candidate.name, repo_root)}
        aliases.add(candidate.name.lower())
        aliases.add(re.sub(r"[^A-Za-z0-9]+", "", candidate.name).lower())
        aliases.update(_manifest_aliases(candidate))
        if token in aliases:
            matches.append((candidate.name, candidate))
    if len(matches) == 1:
        return matches[0]
    return None


def _manifest_aliases(candidate: Path) -> set[str]:
    aliases: set[str] = set()
    for rel in ("manifest.yaml", "indexes/terminology.yaml", "query/terminology.yaml", "registry/aliases.yaml"):
        path = candidate / rel
        if not path.exists():
            continue
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        op_name = data.get("op_name")
        if isinstance(op_name, str):
            aliases.add(op_name.lower())
            aliases.add(re.sub(r"[^A-Za-z0-9]+", "", op_name).lower())
        for item in _iter_alias_items(data):
            if item:
                aliases.add(item.lower())
                aliases.add(re.sub(r"[^A-Za-z0-9]+", "", item).lower())
    return aliases


def _iter_alias_items(data: dict[str, Any]) -> list[str]:
    result: list[str] = []
    aliases = data.get("aliases")
    if isinstance(aliases, list):
        for item in aliases:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and isinstance(item.get("alias"), str):
                result.append(item["alias"])
    terms = data.get("terms")
    if isinstance(terms, dict):
        result.extend(str(key) for key in terms)
    return result


def _stable_slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return slug or "UNKNOWN"


def _default_operator_aliases(op_name: str, repo_root: Path) -> list[str]:
    candidates = [
        op_name,
        op_name.lower(),
        op_name.replace("_", ""),
        op_name.replace("_", "").lower(),
        repo_root.name,
        repo_root.name.lower(),
    ]
    for value in (op_name, repo_root.name):
        words = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
        if len(words) > 1:
            candidates.append("".join(part[0] for part in words).lower())
        prefix = re.sub(r"(?:[_\-.]?test|[_\-.]?op)$", "", value, flags=re.IGNORECASE).strip("._-")
        if prefix and prefix != value:
            candidates.append(prefix)
            candidates.append(prefix.lower())
    seen: set[str] = set()
    aliases: list[str] = []
    for item in candidates:
        alias = item.strip()
        key = alias.lower()
        if alias and key not in seen:
            aliases.append(alias)
            seen.add(key)
    return aliases


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_text_if_missing(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def init_operator_layout(base: Path, op_name: str, repo_root: Path) -> None:
    init_operator_contract_layout(base, op_name, repo_root)



def init_operator_contract_layout(base: Path, op_name: str, repo_root: Path) -> None:
    """Create the new spec-driven operator KB layout.

    The Skill spec is the single source of schema/ownership truth and is not
    copied into the per-operator KB.
    """
    bundle_hash = spec_bundle_hash()
    for rel in [
        "facts/operator",
        "facts/host",
        "facts/compute",
        "facts/kernel/overview",
        "facts/kernel/slices",
        "checks/step1",
        "checks/step2",
        "checks/step3",
        "checks",
        "graphs/raw",
        "graphs/derived",
        "indexes",
        "runs",
        "cbm",
    ]:
        (base / rel).mkdir(parents=True, exist_ok=True)

    for keep in [
        "facts/host/.gitkeep",
        "facts/compute/.gitkeep",
        "facts/kernel/slices/.gitkeep",
        "graphs/raw/.gitkeep",
        "graphs/derived/.gitkeep",
        "indexes/.gitkeep",
        "runs/.gitkeep",
    ]:
        write_text_if_missing(base / keep, "")

    write_text_if_missing(
        base / "manifest.yaml",
        f"""version: 1
op_name: {op_name}
repo_root: {repo_root.as_posix()}
source:
  revision: unknown
  snapshot_id: SOURCE_PENDING
spec:
  name: understand-operator
  version: 1
  bundle_hash: {bundle_hash}
current_run_id: UO_RUN_PENDING
stages:
  step1_boundary:
    status: pending
  step2_host_compute_kernel_overview:
    status: pending
  step3_kernel_slices:
    status: pending
graphs:
  raw:
    status: pending
  derived:
    status: pending
""",
    )
