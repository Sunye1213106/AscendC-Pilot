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
from understand_operator._operator.spec import spec_bundle_hash
from understand_operator.scripts.verify_raw_graph import verify_raw_graph

INPUT_RELS = (
    "checks/compile_gate.yaml",
    "graphs/raw/manifest.yaml",
    "graphs/raw/nodes.yaml",
    "graphs/raw/edges.yaml",
)


def prepare_abstraction_rules(repo_root: Path, op_name: str, *, force: bool = False) -> tuple[int, list[str]]:
    if yaml is None:
        return 2, ["PyYAML is required"]
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        return 2, [f"operator KB root not found: {uo_root}"]
    errors = verify_raw_graph(repo_root, op_name)
    if errors:
        return 2, errors
    out = uo_root / "graphs" / "derived" / "abstraction_rules.yaml"
    if out.exists() and not force:
        existing = _read_yaml(out)
        rules = existing.get("rules")
        if isinstance(rules, list) and rules:
            return 2, ["abstraction_rules.yaml already has rules; pass --force to rebuild skeleton"]
    manifest = _read_yaml(uo_root / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
    payload = {
        "version": 1,
        "artifact": {"type": "graph.derived.abstraction_rules", "schema_version": 1, "owner": "uo-behavior-abstraction-agent"},
        "snapshot": {
            "run_id": manifest.get("current_run_id") or "UO_RUN_UNKNOWN",
            "source_snapshot_id": source.get("snapshot_id") or "SOURCE_UNKNOWN",
            "source_revision": source.get("revision") or "unknown",
            "spec_bundle_hash": spec.get("bundle_hash") or spec_bundle_hash(),
        },
        "input_hashes": {rel: _sha256(uo_root / rel) for rel in INPUT_RELS},
        "rules": [] if force or not out.exists() else (_read_yaml(out).get("rules") or []),
        "items": [],
        "relations": [],
        "unresolved": [],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return 0, [f"wrote {out}"]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare derived abstraction rule skeleton with frozen raw graph input hashes.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing abstraction_rules.yaml skeleton.")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = prepare_abstraction_rules(repo_root, op_name, force=args.force)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
