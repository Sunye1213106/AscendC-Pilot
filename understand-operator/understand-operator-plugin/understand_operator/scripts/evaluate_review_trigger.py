"""Deterministically decide whether an LLM fact review is required."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.fact_hashes import all_fact_hashes, step2_fact_hashes
from understand_operator._operator.spec import spec_bundle_hash


def evaluate_review_trigger(repo: Path, op_name: str, step: str) -> dict[str, Any]:
    root = existing_operator_root(repo.resolve(), safe_op_name(op_name, repo))
    if step == "step2":
        fact_paths = [root / rel for rel in step2_fact_hashes(root)]
        hashes = step2_fact_hashes(root)
    else:
        fact_paths = [root / rel for rel in all_fact_hashes(root)]
        hashes = all_fact_hashes(root)
    reasons: list[str] = []
    for path in fact_paths:
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        groups = (doc.get("sections") or {}).values() if isinstance(doc.get("sections"), dict) else [doc]
        if any(bool(group.get("unresolved")) for group in groups if isinstance(group, dict)):
            reasons.append(f"unresolved:{path.relative_to(root).as_posix()}")
    if _registry_conflict(root):
        reasons.append("registry_conflict")
    triggered = bool(reasons)
    return {
        "version": 1,
        "artifact": {"type": f"checks.{step}.review_trigger", "schema_version": 1, "owner": "facts-validator"},
        "snapshot": _snapshot(root),
        "status": "triggered" if triggered else "skipped",
        "reason": ";".join(reasons) if triggered else "no_unresolved_ambiguous_registry_conflict_or_closure_gap",
        "input_hashes": hashes,
        "items": [],
        "relations": [],
        "unresolved": [],
        "warnings": [],
        "errors": [],
    }


def _registry_conflict(root: Path) -> bool:
    registry = root / "indexes" / "entity_registry.json"
    if not registry.exists():
        return False
    text = registry.read_text(encoding="utf-8", errors="replace").lower()
    return "conflict" in text


def _snapshot(root: Path) -> dict[str, str]:
    manifest_path = root / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return {
        "run_id": str(manifest.get("current_run_id") or "UO_RUN_REVIEW_TRIGGER"),
        "source_snapshot_id": str(source.get("snapshot_id") or "SOURCE_REVIEW_TRIGGER"),
        "source_revision": str(source.get("revision") or "unknown"),
        "spec_bundle_hash": spec_bundle_hash(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate whether Step 2/3 LLM review is required.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--step", choices=("step2", "step3"), required=True)
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    root = existing_operator_root(repo, safe_op_name(args.op_name, repo))
    data = evaluate_review_trigger(repo, args.op_name, args.step)
    out = root / "checks" / args.step / "review_trigger.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
