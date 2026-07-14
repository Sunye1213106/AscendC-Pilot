from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
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
from understand_operator.scripts.build_compile_gate import compile_gate_errors, facts_hashes_for

RAW_RELS = (
    "graphs/raw/manifest.yaml",
    "graphs/raw/nodes.yaml",
    "graphs/raw/edges.yaml",
    "graphs/raw/paths.yaml",
    "graphs/raw/indexes.yaml",
    "indexes/graph_to_yaml.yaml",
    "indexes/yaml_to_graph.yaml",
    "indexes/source_index.yaml",
    "indexes/symbol_index.yaml",
    "indexes/terminology.yaml",
)


def verify_raw_graph(repo_root: Path, op_name: str) -> list[str]:
    if yaml is None:
        return ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    errors: list[str] = []
    errors.extend(compile_gate_errors(uo_root))
    manifest = _read_yaml(uo_root / "manifest.yaml")
    raw_manifest = _read_yaml(uo_root / "graphs" / "raw" / "manifest.yaml")
    for rel in RAW_RELS:
        if not (uo_root / rel).exists():
            errors.append(f"RAW_GRAPH_STALE: {rel} missing")
    if errors:
        return errors
    payload_hash = raw_manifest.get("input_facts_hash")
    current_hash = _combined_hash(facts_hashes_for(uo_root))
    if payload_hash != current_hash:
        errors.append("RAW_GRAPH_STALE: facts hash changed")
    snapshot = raw_manifest.get("snapshot") if isinstance(raw_manifest.get("snapshot"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    if snapshot.get("run_id") != manifest.get("current_run_id"):
        errors.append("RAW_GRAPH_STALE: snapshot.run_id does not match manifest.current_run_id")
    if snapshot.get("source_revision") != source.get("revision"):
        errors.append("RAW_GRAPH_STALE: source revision changed")
    current_rev = _git_revision(repo_root)
    if source.get("revision") not in {None, "", "unknown", current_rev}:
        errors.append("SOURCE_REVISION_STALE: manifest.source.revision does not match git HEAD")
    frozen = raw_manifest.get("output_hashes") if isinstance(raw_manifest.get("output_hashes"), dict) else {}
    for rel in RAW_RELS[1:]:
        expected = frozen.get(rel)
        actual = _sha256(uo_root / rel)
        if expected and expected != actual:
            errors.append(f"RAW_GRAPH_STALE: {rel} hash changed")
    return errors


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _combined_hash(values: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for key, value in sorted(values.items()):
        digest.update(key.encode("utf-8"))
        digest.update(value.encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def _git_revision(repo_root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True)
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify raw graph freshness without rewriting graph artifacts.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    errors = verify_raw_graph(repo_root, op_name)
    for error in errors:
        print(error, file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
