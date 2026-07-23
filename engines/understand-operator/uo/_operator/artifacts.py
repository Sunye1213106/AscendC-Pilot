from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uo._operator.spec import spec_bundle_hash

# Canonical KB root: <repo>/.ascendc-pilot/uo/ (no per-op nesting).
ARTIFACT_DIR = ".ascendc-pilot"
UO_SUBDIR = "uo"


def safe_op_name(name: str | None, repo_root: Path) -> str:
    raw = (name or "").strip() or repo_root.name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return cleaned or "unknown_operator"


def operator_root(repo_root: Path, op_name: str) -> Path:
    del op_name  # retained for call-site compatibility; products are not nested by op
    path = repo_root / ARTIFACT_DIR / UO_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def existing_operator_root(repo_root: Path, op_name: str) -> Path:
    """Return the expected KB root without creating an empty KB directory."""
    del op_name
    return repo_root / ARTIFACT_DIR / UO_SUBDIR


def resolve_existing_operator_root(repo_root: Path, op_name: str) -> tuple[str, Path] | None:
    """Resolve an existing KB by manifest metadata and terminology aliases."""
    exact = existing_operator_root(repo_root, op_name)
    if (exact / "manifest.yaml").exists():
        # Prefer manifest op_name when present
        aliases = _manifest_aliases(exact)
        token = op_name.strip().lower()
        # Single KB per repo (no op nesting). Accept empty token or alias hit;
        # otherwise still return KB but prefer manifest op_name (warn via aliases miss).
        manifest_op = None
        try:
            import yaml

            data = yaml.safe_load((exact / "manifest.yaml").read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and isinstance(data.get("op_name"), str):
                manifest_op = data["op_name"]
        except Exception:  # noqa: BLE001
            manifest_op = None
        if not token or token in aliases or (manifest_op and token == manifest_op.lower()):
            return (manifest_op or op_name), exact
        # Soft bind: one KB tree — return it with manifest name rather than invent a second root
        return (manifest_op or op_name), exact

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
    """Create the layered-IR operator KB layout."""
    bundle_hash = spec_bundle_hash()
    for rel in [
        "ir",
        "tiling",
        "kernel",
        "cross_layer",
        "flow",
        "test",
        "checks",
        "runs",
        "cbm",
        "analysis",
        "diff",
        "summary",
        "review",
    ]:
        (base / rel).mkdir(parents=True, exist_ok=True)

    # Remove obsolete empty shells if present.
    _prune_obsolete_layout_dirs(base)

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
pipeline: layered_ir
stages:
  scope:
    status: pending
    label_zh: 范围确认
  extract:
    status: pending
    label_zh: 结构抽取
  resolve:
    status: pending
    label_zh: 语义闭合
  export:
    status: pending
    label_zh: 导出与校验
  review:
    status: pending
    label_zh: 产物审查
artifacts:
  ir:
    status: pending
""",
    )


def _prune_obsolete_layout_dirs(base: Path) -> None:
    """Drop obsolete empty shells that confuse operators."""
    obsolete_dirs = (
        "facts",
        "graphs",
        "indexes",
        "contracts",
        "checks/step1",
        "checks/step2",
        "checks/step3",
    )
    for rel in obsolete_dirs:
        path = base / rel
        if not path.exists():
            continue
        try:
            # Only remove when the tree contains no non-empty files.
            if any(p.is_file() and p.stat().st_size > 0 and p.name != ".gitkeep" for p in path.rglob("*")):
                continue
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    child.rmdir()
            if path.is_dir():
                path.rmdir()
        except OSError:
            continue
