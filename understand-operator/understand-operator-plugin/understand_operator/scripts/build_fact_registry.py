from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name
from understand_operator._operator.fact_registry import build_fact_registry, write_registry_cache


def build_registry_cache(repo_root: Path, op_name: str) -> tuple[int, list[str]]:
    repo_root = repo_root.resolve()
    uo_root = existing_operator_root(repo_root, safe_op_name(op_name, repo_root))
    if not uo_root.exists():
        return 2, [f"operator KB root not found: {uo_root}"]
    registry = build_fact_registry(uo_root)
    if registry.conflicts:
        return 2, [json.dumps(conflict.__dict__, ensure_ascii=False, sort_keys=True) for conflict in registry.conflicts]
    write_registry_cache(uo_root, registry)
    return 0, [f"wrote {uo_root / 'indexes' / 'entity_registry.json'}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild Understand Operator entity_registry.json from Formal Facts.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    code, messages = build_registry_cache(repo_root, op_name)
    stream = sys.stderr if code else sys.stdout
    for message in messages:
        print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
