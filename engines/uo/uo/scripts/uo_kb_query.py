"""CLI: uo-kb-query — pattern queries over indexes/kb_graph.sqlite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts.kb_graph_query import PATTERNS, index_status, query_kb_graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query derived KB graph (indexes/kb_graph.sqlite)")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument(
        "--pattern",
        required=False,
        choices=PATTERNS,
        default=None,
        help="Query pattern (required unless --status-only)",
    )
    parser.add_argument("--target", default="", help="Entity id/label, or comma-separated file paths")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--relation-type", default=None)
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Print kb_graph index freshness only (does not require --pattern)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    try:
        uo_root = existing_operator_root(repo_root, op_name)
    except Exception as exc:  # noqa: BLE001
        print(f"uo-kb-query failed: {exc}", file=sys.stderr)
        return 2

    if args.status_only:
        print(json.dumps(index_status(uo_root), ensure_ascii=False, indent=2))
        return 0

    if not args.pattern:
        parser.error("--pattern is required unless --status-only is set")

    try:
        result = query_kb_graph(
            uo_root,
            pattern=args.pattern,
            target=args.target,
            depth=args.depth,
            limit=args.limit,
            relation_type=args.relation_type,
        )
    except ValueError as exc:
        print(f"uo-kb-query failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("index_status") in {"missing", "stale"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
