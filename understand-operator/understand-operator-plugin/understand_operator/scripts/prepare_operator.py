from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._core.config import load_config
from understand_operator._core.ignore import DEFAULT_IGNORE_PATTERNS
from understand_operator._operator.artifacts import init_operator_layout, operator_root, safe_op_name, write_text
from understand_operator._operator.cbm_client import run_operator_cbm_prefetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare understand-operator artifacts and CBM query cache")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--full", action="store_true", help="Force CBM index_repository before analysis")
    parser.add_argument("--cbm-binary", help="Path to codebase-memory-mcp binary")
    parser.add_argument("--cbm-mode", choices=["full", "moderate", "fast"], help="CBM index mode")
    parser.add_argument("--skip-cbm", action="store_true", help="Only create artifact layout")
    parser.add_argument(
        "--prefetch-queries",
        action="store_true",
        help="Legacy: also write bulk search_graph/search_code JSON files under cbm/ (default is index-only)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    config = load_config(repo_root)
    scanner_cfg = config.setdefault("scanner", {})
    if args.cbm_binary:
        scanner_cfg["cbm_binary"] = args.cbm_binary
    if args.cbm_mode:
        scanner_cfg["cbm_mode"] = args.cbm_mode

    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name)
    init_operator_layout(base, op_name, repo_root)

    patterns = _load_operator_ignore_patterns(repo_root)
    write_text(
        base / "summary" / "ignore_rules.md",
        "# Ignore Rules\n\n"
        "These rules are loaded before CBM-assisted operator analysis. Review them if files are missing.\n\n"
        + "\n".join(f"- `{p}`" for p in patterns)
        + "\n",
    )

    if not args.skip_cbm:
        run_operator_cbm_prefetch(
            repo_root,
            base,
            config,
            op_name=op_name,
            full=args.full,
            prefetch_queries=args.prefetch_queries,
        )
    else:
        write_text(base / "cbm" / "cbm_query_log.md", "# CBM Query Log\n\nCBM prefetch skipped by --skip-cbm.\n")

    print(f"Prepared understand-operator artifacts for {op_name}")
    print(f"Output: {base}")
    print(f"CBM: index-only prefetch (use cbm_query.py for on-demand queries)")
    print(f"Next: run Macro Boundary Agent using prompts/02_macro_boundary_agent.md")
    print(f"Then: Boundary Human Review using prompts/02a_boundary_human_review.md")
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


if __name__ == "__main__":
    raise SystemExit(main())
