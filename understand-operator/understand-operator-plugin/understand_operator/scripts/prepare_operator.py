from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._core.ignore import DEFAULT_IGNORE_PATTERNS
from understand_operator._operator.artifacts import init_operator_layout, operator_root, safe_op_name, write_text
from understand_operator._operator.cbm_client import write_index_meta
from understand_operator._operator.install_check import compare_installed_skill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare understand-operator KB layout. "
            "CBM graph DB indexing is done by MCP index_repository during /uo-init — not by this script."
        )
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument(
        "--write-index-meta",
        action="store_true",
        help="Write/update cbm/index_meta.json after MCP index_repository (pass --cbm-project from MCP result)",
    )
    parser.add_argument("--cbm-project", help="CBM project name returned by MCP list_projects / index_repository")
    parser.add_argument("--cbm-mode", default="fast", help="Recorded index mode label (default: fast)")
    parser.add_argument(
        "--cli-cbm",
        action="store_true",
        help="DEPRECATED emergency: run binary CLI index via run_operator_cbm_prefetch. Prefer MCP.",
    )
    parser.add_argument("--full", action="store_true", help="With --cli-cbm only: force CLI index_repository")
    parser.add_argument("--cbm-binary", help="With --cli-cbm only: path to codebase-memory-mcp binary")
    parser.add_argument(
        "--prefetch-queries",
        action="store_true",
        help="With --cli-cbm only: legacy bulk query dump",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name)
    init_operator_layout(base, op_name, repo_root)
    installed_skill = Path.home() / ".config" / "opencode" / "skills" / "understand-operator"
    if installed_skill.exists():
        check = compare_installed_skill(Path(__file__).resolve().parents[2], installed_skill)
    else:
        check = {
            "version": 1,
            "consistent": False,
            "error_code": "INSTALLED_SKILL_VERSION_MISMATCH",
            "installed_skill_root": str(installed_skill),
            "mismatches": [{"path": "skills/understand-operator", "reason": "installed skill root missing"}],
        }
    write_text(base / "archive" / "runs" / "installed_skill_check.yaml", _to_yaml(check))

    patterns = _load_operator_ignore_patterns(repo_root)
    write_text(
        base / "archive" / "runs" / "ignore_rules.md",
        "# Ignore Rules\n\n"
        "These rules are loaded before CBM-assisted operator analysis. Review them if files are missing.\n\n"
        + "\n".join(f"- `{p}`" for p in patterns)
        + "\n",
    )

    if args.write_index_meta or args.cbm_project:
        write_index_meta(
            base,
            {
                "repo_root": str(repo_root),
                "op_name": op_name,
                "cbm_project": args.cbm_project,
                "cbm_binary": None,
                "indexed_via": "mcp",
                "cbm_mode": args.cbm_mode,
                "indexed_at": datetime.now(tz=timezone.utc).isoformat(),
                "prefetch_mode": "mcp_index_repository",
                "index_summary": {},
            },
        )
        write_text(
            base / "cbm" / "cbm_query_log.md",
            "# CBM Index Log\n\n"
            f"- indexed_via: mcp\n"
            f"- cbm_project: {args.cbm_project or 'pending'}\n"
            f"- indexed_at: {datetime.now(tz=timezone.utc).isoformat()}\n"
            "- agent queries: MCP codebase-memory-mcp tools only\n",
        )

    if args.cli_cbm:
        print(
            "WARNING: --cli-cbm is deprecated. /uo-init should call MCP index_repository instead.",
            file=sys.stderr,
        )
        from understand_operator._core.config import load_config
        from understand_operator._operator.cbm_client import run_operator_cbm_prefetch

        config = load_config(repo_root)
        scanner_cfg = config.setdefault("scanner", {})
        if args.cbm_binary:
            scanner_cfg["cbm_binary"] = args.cbm_binary
        if args.cbm_mode:
            scanner_cfg["cbm_mode"] = args.cbm_mode
        run_operator_cbm_prefetch(
            repo_root,
            base,
            config,
            op_name=op_name,
            full=args.full or True,
            prefetch_queries=args.prefetch_queries,
        )
    else:
        stub = base / "cbm" / "cbm_query_log.md"
        if not stub.exists():
            write_text(
                stub,
                "# CBM Index Log\n\n"
                "Layout prepared. Waiting for MCP `index_repository` from /uo-init.\n",
            )

    print(f"Prepared understand-operator artifacts for {op_name}")
    print(f"Output: {base}")
    print("CBM: use MCP index_repository in /uo-init (this script does not build the graph DB by default)")
    print("Next: MCP index_repository -> Phase 0.5-A deterministic scope scan -> Phase 0.5-C review")
    return 0


def _load_operator_ignore_patterns(repo_root: Path) -> list[str]:
    base = repo_root / ".understand-operator"
    base.mkdir(parents=True, exist_ok=True)
    path = base / ".understandoperatorignore"
    if not path.exists():
        lines = [
            "# understand-operator ignore rules",
            "",
            "# Default ignored paths:",
            *[f"# {p}" for p in DEFAULT_IGNORE_PATTERNS],
            "",
            "# From .gitignore:",
        ]
        gitignore = repo_root / ".gitignore"
        if gitignore.exists():
            for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    lines.append(stripped)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def _to_yaml(data: object) -> str:
    try:
        import yaml

        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception:  # noqa: BLE001
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
