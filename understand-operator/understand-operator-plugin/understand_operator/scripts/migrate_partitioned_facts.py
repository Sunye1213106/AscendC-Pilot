"""One-shot, failure-safe migration from split Facts to partition Facts."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path: sys.path.insert(0, str(root))
from understand_operator._operator.artifacts import existing_operator_root, safe_op_name

GROUPS = {
    "facts/host.yaml": ["variables", "expressions", "control_flow", "calls", "tiling_key", "tiling_key_enumeration", "tiling_key_constraints", "tilingdata_writes"],
    "facts/compute.yaml": ["tensors", "operations", "dataflow", "numerical_semantics"],
    "facts/kernel/overview.yaml": ["entries", "functions", "call_graph", "frontier", "global_resources"],
}
LEGACY_DIRS = {
    "facts/host.yaml": "facts/host",
    "facts/compute.yaml": "facts/compute",
    "facts/kernel/overview.yaml": "facts/kernel/overview",
}

def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict): raise ValueError(f"{path} is not a mapping")
    return data

def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True); temp = Path(f.name)
    os.replace(temp, path)

def migrate_partitioned_facts(repo: Path, op_name: str) -> dict[str, Any]:
    root = existing_operator_root(repo.resolve(), safe_op_name(op_name, repo))
    report: dict[str, Any] = {"status": "pass", "migrated": [], "skipped": [], "timestamp": datetime.now(timezone.utc).isoformat()}
    run_id = str(_read(root / "manifest.yaml").get("current_run_id") or "migration")
    backup = root / "runs" / run_id / "migration_backup"
    planned: list[tuple[Path, dict[str, Any], list[Path]]] = []
    for dest_rel, names in GROUPS.items():
        dest = root / dest_rel
        if dest.exists(): report["skipped"].append(dest_rel); continue
        old = [(root / LEGACY_DIRS[dest_rel] / f"{name}.yaml") for name in names]
        present = [path for path in old if path.exists()]
        if not present: continue
        docs = [_read(path) for path in present] # validate YAML before changing anything
        first = docs[0]
        sections = {name: {"items": [], "relations": [], "unresolved": []} for name in names}
        for path, doc in zip(present, docs):
            name = path.stem; sections[name] = {key: list(doc.get(key) or []) for key in ("items", "relations", "unresolved")}
        planned.append((dest, {"version": 1, "artifact": {"type": f"{dest.stem}.partition", "schema_version": 1, "owner": first.get("artifact", {}).get("owner")}, "snapshot": first.get("snapshot", {}), "sections": sections}, present))
    # All parsing precedes writes; a failed source leaves Facts untouched.
    for dest, doc, old in planned:
        _write_atomic(dest, doc)
        for path in old:
            target = backup / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        report["migrated"].append({"target": dest.relative_to(root).as_posix(), "sources": [p.relative_to(root).as_posix() for p in old]})
    slices = root / "facts" / "kernel" / "slices"
    if slices.exists():
        names = ["variables", "expressions", "branches", "loops", "tilingdata_reads", "calls", "dataflow", "memory", "synchronization"]
        for directory in sorted(path for path in slices.iterdir() if path.is_dir()):
            dest = slices / f"{directory.name}.yaml"
            present = [directory / f"{name}.yaml" for name in names if (directory / f"{name}.yaml").exists()]
            if dest.exists() or not present:
                continue
            docs = [_read(path) for path in present]
            sections = {path.stem: {key: list(doc.get(key) or []) for key in ("items", "relations", "unresolved")} for path, doc in zip(present, docs)}
            first = docs[0]
            _write_atomic(dest, {"version": 1, "artifact": {"type": "kernel.slice.partition", "schema_version": 1, "owner": first.get("artifact", {}).get("owner")}, "snapshot": first.get("snapshot", {}), "sections": sections})
            for path in present:
                target = backup / path.relative_to(root); target.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(path), str(target))
            directory.rmdir()
            report["migrated"].append({"target": dest.relative_to(root).as_posix(), "sources": [p.relative_to(root).as_posix() for p in present]})
    _write_atomic(root / "runs" / run_id / "migration_report.yaml", report)
    return report

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(); p.add_argument("repo", nargs="?", default="."); p.add_argument("--op-name", required=True); args = p.parse_args(argv)
    print(yaml.safe_dump(migrate_partitioned_facts(Path(args.repo), args.op_name), sort_keys=False, allow_unicode=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
