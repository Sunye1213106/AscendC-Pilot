from __future__ import annotations

import argparse
import hashlib
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


def verify_derived_graph(repo_root: Path, op_name: str) -> list[str]:
    if yaml is None:
        return ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    errors: list[str] = []
    for rel in (
        "graphs/derived/abstraction_rules.yaml",
        "graphs/derived/nodes.yaml",
        "graphs/derived/edges.yaml",
        "graphs/derived/expansions.yaml",
        "graphs/derived/indexes.yaml",
        "checks/derived_validation.yaml",
    ):
        if not (uo_root / rel).exists():
            errors.append(f"DERIVED_GRAPH_STALE: {rel} missing")
    if errors:
        return errors
    rules = _read_yaml(uo_root / "graphs" / "derived" / "abstraction_rules.yaml")
    validation = _read_yaml(uo_root / "checks" / "derived_validation.yaml")
    errors.extend(_hash_errors(uo_root, rules.get("input_hashes"), "DERIVED_RULES_STALE"))
    if validation.get("status") != "pass":
        errors.append("DERIVED_GRAPH_STALE: derived_validation status is not pass")
    errors.extend(_hash_errors(uo_root, validation.get("input_hashes"), "DERIVED_VALIDATION_STALE"))
    manifest = _read_yaml(uo_root / "manifest.yaml")
    for rel in ("graphs/derived/nodes.yaml", "graphs/derived/edges.yaml", "graphs/derived/expansions.yaml", "graphs/derived/indexes.yaml"):
        doc = _read_yaml(uo_root / rel)
        snapshot = doc.get("snapshot") if isinstance(doc.get("snapshot"), dict) else {}
        if snapshot.get("run_id") != manifest.get("current_run_id"):
            errors.append(f"DERIVED_GRAPH_STALE: {rel} snapshot.run_id mismatch")
    expansions = _read_yaml(uo_root / "graphs" / "derived" / "expansions.yaml").get("expansions") or []
    raw_nodes = {str(item.get("id")) for item in (_read_yaml(uo_root / "graphs" / "raw" / "nodes.yaml").get("nodes") or []) if isinstance(item, dict)}
    raw_edges = {str(item.get("id")) for item in (_read_yaml(uo_root / "graphs" / "raw" / "edges.yaml").get("edges") or []) if isinstance(item, dict)}
    for index, expansion in enumerate(expansions):
        if not isinstance(expansion, dict):
            continue
        for ref in expansion.get("raw_node_refs") or []:
            if str(ref) not in raw_nodes:
                errors.append(f"DERIVED_GRAPH_STALE: expansions[{index}] raw node missing {ref}")
        for ref in expansion.get("raw_edge_refs") or []:
            if str(ref) not in raw_edges:
                errors.append(f"DERIVED_GRAPH_STALE: expansions[{index}] raw edge missing {ref}")
        for ref in expansion.get("yaml_refs") or []:
            if _read_yaml_ref(uo_root, str(ref)) is None:
                errors.append(f"DERIVED_GRAPH_STALE: expansions[{index}] yaml ref missing {ref}")
    return errors


def _hash_errors(uo_root: Path, hashes: Any, code: str) -> list[str]:
    if not isinstance(hashes, dict) or not hashes:
        return [f"{code}: input_hashes missing"]
    errors: list[str] = []
    for rel, expected in sorted(hashes.items()):
        path = uo_root / str(rel)
        if not path.exists():
            errors.append(f"{code}: {rel} missing")
            continue
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"{code}: {rel} hash changed")
    return errors


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _read_yaml_ref(uo_root: Path, ref: str) -> Any:
    rel, _, pointer = ref.partition("#")
    path = uo_root / rel
    if not path.exists():
        return None
    value: Any = _read_yaml(path)
    for part in [part for part in pointer.strip("/").split("/") if part]:
        if isinstance(value, list) and part.isdigit():
            idx = int(part)
            value = value[idx] if idx < len(value) else None
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify derived graph freshness without rewriting graph artifacts.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    errors = verify_derived_graph(repo_root, op_name)
    for error in errors:
        print(error, file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
