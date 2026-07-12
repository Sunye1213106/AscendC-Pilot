from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._core.config import load_config
from understand_operator._operator.artifacts import operator_root, safe_op_name
from understand_operator._operator.cbm_client import OperatorCbmClient, append_query_journal, load_index_meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "DEPRECATED for agent/runtime lookups. Prefer MCP server codebase-memory-mcp "
            "(search_graph/search_code/get_code_snippet/trace_path). "
            "This CLI remains for offline/scripted use only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_CLI_EXAMPLES,
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository root (AscendC operator repo)")
    parser.add_argument("tool", help="CBM tool: search_graph, search_code, get_code_snippet, trace_path, ...")
    parser.add_argument(
        "payload_pos",
        nargs="?",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--phase", default="runtime", help="Caller label for journal")
    parser.add_argument("--cbm-binary", help="Override CBM binary path")
    parser.add_argument(
        "-p",
        "--payload",
        default=None,
        help="JSON object string. Prefer this or --payload-file on Windows.",
    )
    parser.add_argument(
        "-f",
        "--payload-file",
        help="Path to a UTF-8 JSON file containing the payload object.",
    )
    parser.add_argument("--name-pattern", help="search_graph shorthand: name_pattern")
    parser.add_argument("--label", help="search_graph shorthand: label (e.g. Function)")
    parser.add_argument("--code-pattern", help="search_code shorthand: pattern")
    parser.add_argument("--function-name", help="trace_path shorthand: function_name")
    parser.add_argument("--direction", default="both", help="trace_path shorthand: direction")
    parser.add_argument("--depth", type=int, default=5, help="trace_path shorthand: depth")
    parser.add_argument("--file", dest="snippet_file", help="get_code_snippet shorthand: file path")
    parser.add_argument("--symbol", help="get_code_snippet shorthand: symbol name")
    parser.add_argument("--save", action="store_true", help="Also write cbm/<seq>_<tool>.json")
    parser.add_argument("--no-journal", action="store_true", help="Do not append cbm/query_journal.jsonl")
    parser.add_argument("--no-project", action="store_true", help="Do not auto-inject CBM project from index_meta")
    args = parser.parse_args(argv)

    try:
        payload = _resolve_payload(args)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    repo_root = Path(args.repo).resolve()
    config = load_config(repo_root)
    if args.cbm_binary:
        config.setdefault("scanner", {})["cbm_binary"] = args.cbm_binary

    op_name = safe_op_name(args.op_name, repo_root)
    artifact_root = operator_root(repo_root, op_name)
    meta = load_index_meta(artifact_root)
    if meta.get("cbm_project") and not args.no_project:
        config.setdefault("scanner", {})["cbm_project"] = meta["cbm_project"]

    client = OperatorCbmClient(repo_root, artifact_root, config)
    if meta.get("cbm_project"):
        client.project_name = str(meta["cbm_project"])

    if not client.available():
        from understand_operator._core.cbm_resolver import cbm_install_hint

        print(json.dumps({"ok": False, "error": cbm_install_hint()}, ensure_ascii=False))
        return 2

    output_name = None
    if args.save:
        seq = _next_journal_seq(artifact_root)
        output_name = f"{seq:04d}_{args.tool}.json"

    print(
        "WARNING: cbm_query.py is deprecated for agent lookups; "
        "use MCP server codebase-memory-mcp instead. See docs/cbm-mcp-setup.md",
        file=sys.stderr,
    )

    data = client.call(args.tool, payload, output_name=output_name, persist=args.save)
    envelope = {
        "ok": data.get("ok", False),
        "tool": args.tool,
        "payload": payload,
        "phase": args.phase,
        "result": data.get("result"),
        "error": data.get("error", ""),
        "deprecated_for_agents": True,
        "prefer": "MCP codebase-memory-mcp",
    }

    if not args.no_journal:
        append_query_journal(
            artifact_root,
            tool=args.tool,
            payload=payload,
            ok=bool(data.get("ok")),
            phase=args.phase,
            error=str(data.get("error") or ""),
            result=data.get("result"),
            saved_to=f"cbm/{output_name}" if args.save and output_name else None,
        )

    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") else 1


def _resolve_payload(args: argparse.Namespace) -> dict[str, Any]:
    sources = [args.payload_file, args.payload, args.payload_pos]
    if sum(1 for item in sources if item not in (None, "")) > 1:
        raise ValueError("use only one of --payload-file, --payload, or positional payload")

    if args.payload_file:
        path = Path(args.payload_file)
        if not path.is_file():
            raise ValueError(f"payload file not found: {path}")
        raw = path.read_text(encoding="utf-8-sig").strip()
        if not raw:
            raise ValueError(f"payload file is empty: {path}")
        return _parse_payload_text(raw, source=str(path))

    if args.payload not in (None, ""):
        return _parse_payload_text(str(args.payload).strip(), source="--payload")

    if args.payload_pos not in (None, ""):
        return _parse_payload_text(str(args.payload_pos).strip(), source="positional payload")

    shorthand = _payload_from_shorthand(args)
    if shorthand:
        return shorthand

    return {}


def _parse_payload_text(raw: str, *, source: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        hint = (
            f"invalid JSON in {source}: {exc}. "
            "On Windows PowerShell prefer shorthand flags "
            "(--name-pattern, --code-pattern, --function-name, --file --symbol) "
            "or --payload-file with a .json file."
        )
        raise ValueError(hint) from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"payload in {source} must be a JSON object")
    return parsed


def _payload_from_shorthand(args: argparse.Namespace) -> dict[str, Any]:
    tool = args.tool
    if tool == "search_graph" and args.name_pattern:
        payload: dict[str, Any] = {"name_pattern": args.name_pattern}
        if args.label:
            payload["label"] = args.label
        return payload
    if tool == "search_code" and args.code_pattern:
        return {"pattern": args.code_pattern}
    if tool in {"trace_path", "trace_call_path"} and args.function_name:
        return {
            "function_name": args.function_name,
            "direction": args.direction,
            "depth": args.depth,
        }
    if tool == "get_code_snippet" and args.snippet_file and args.symbol:
        return {"file": args.snippet_file, "symbol": args.symbol}
    return {}


def _next_journal_seq(artifact_root: Path) -> int:
    journal = artifact_root / "cbm" / "query_journal.jsonl"
    if not journal.exists():
        return 1
    count = 0
    for line in journal.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip():
            count += 1
    return count + 1


_CLI_EXAMPLES = """
Examples (PowerShell — prefer shorthand, no JSON quoting):

  python cbm_query.py D:\\repo search_graph --op-name MyOp --name-pattern ".*MyOpTiling.*" --label Function
  python cbm_query.py D:\\repo search_code --op-name MyOp --code-pattern tiling_key
  python cbm_query.py D:\\repo trace_path --op-name MyOp --function-name MyOpTiling --depth 5
  python cbm_query.py D:\\repo get_code_snippet --op-name MyOp --file op_host/foo.cpp --symbol MyOpTiling

Payload file (complex queries):

  python cbm_query.py D:\\repo query_graph --op-name MyOp --payload-file .\\cbm_payload.json
"""


if __name__ == "__main__":
    raise SystemExit(main())
