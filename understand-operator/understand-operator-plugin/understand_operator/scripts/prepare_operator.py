from __future__ import annotations

import argparse
import json
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._core.ignore import DEFAULT_IGNORE_PATTERNS
from understand_operator._operator.artifacts import init_operator_contract_layout, operator_root, safe_op_name, write_text
from understand_operator._operator.cbm_client import write_index_meta
from understand_operator._operator.install_check import compare_installed_skill
from understand_operator._operator.spec import spec_bundle_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare understand-operator KB layout. "
            "CBM graph DB indexing is done by MCP index_repository during /uo-init — not by this script."
        )
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--resume", action="store_true", help="Resume the current incomplete UO run.")
    parser.add_argument("--force-new-run", action="store_true", help="Always create a new UO run.")
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
    init_operator_contract_layout(base, op_name, repo_root)
    run_id = _select_run_id(base, resume=args.resume, force_new=args.force_new_run)
    phase0 = base / "runs" / run_id / "phase0"
    _update_manifest_phase0(base, run_id, repo_root)
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
    _write_phase0_doc(
        phase0 / "context.yaml",
        "runs.context",
        "OP_PHASE0_CONTEXT",
        "context",
        {
            "project_root": str(repo_root),
            "op_name": op_name,
            "script_dir": str(Path(__file__).resolve().parent),
            "run_id": run_id,
            "source_revision": _git_revision(repo_root),
            "source_snapshot_id": _source_snapshot_id(repo_root),
            "spec_bundle_hash": spec_bundle_hash(),
        },
    )
    _write_phase0_doc(phase0 / "installed_skill_check.yaml", "runs.installed_skill_check", "OP_PHASE0_SKILL_CHECK", "installed_skill_check", check)
    if not check.get("consistent"):
        print("ERROR: installed understand-operator plugin is out of sync with the repository.", file=sys.stderr)
        print("Run: powershell -ExecutionPolicy Bypass -File understand-operator/understand-operator-plugin/install.ps1", file=sys.stderr)
        print(f"Details: {phase0 / 'installed_skill_check.yaml'}", file=sys.stderr)
        return 3

    patterns = _load_operator_ignore_patterns(repo_root)
    _write_phase0_doc(
        phase0 / "ignore_rules.yaml",
        "runs.ignore_rules",
        "OP_PHASE0_IGNORE_RULES",
        "ignore_rules",
        {"patterns": patterns},
    )
    for filename, artifact_type, item_id, kind in (
        ("scope_scan.yaml", "runs.scope_scan", "OP_PHASE0_SCOPE_SCAN", "scope_scan"),
        ("semantic_enrichment.yaml", "runs.semantic_enrichment", "OP_PHASE0_SEMANTIC_ENRICHMENT", "semantic_enrichment"),
        ("scope_review.yaml", "runs.scope_review", "OP_PHASE0_SCOPE_REVIEW", "scope_review"),
        ("receipt.yaml", "runs.receipt", "OP_PHASE0_RECEIPT", "phase0_receipt"),
    ):
        target = phase0 / filename
        if not target.exists():
            _write_phase0_doc(target, artifact_type, item_id, kind, {"status": "pending"})

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
                "project_confirmed": bool(args.cbm_project),
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
    print("Next: run validate_facts.py after each agent writes its stage YAML")
    return 0


def _select_run_id(base: Path, *, resume: bool, force_new: bool) -> str:
    if resume and force_new:
        raise SystemExit("--resume and --force-new-run are mutually exclusive")
    if force_new or not resume:
        return _new_run_id()
    current = _current_run_id(base)
    if current is None:
        return _new_run_id()
    receipt = base / "runs" / current / "phase0" / "receipt.yaml"
    if _receipt_passed(receipt):
        raise SystemExit(f"current run {current} already has a pass receipt; create a new run instead")
    return current


def _current_run_id(base: Path) -> str | None:
    manifest = base / "manifest.yaml"
    if manifest.exists():
        try:
            import yaml

            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            value = data.get("current_run_id")
            if isinstance(value, str) and value.startswith("UO_RUN_") and value != "UO_RUN_PENDING":
                return value
        except Exception:  # noqa: BLE001
            pass
    return None


def _new_run_id() -> str:
    return "UO_RUN_" + datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _receipt_passed(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return isinstance(data, dict) and data.get("status") == "pass"
    except Exception:  # noqa: BLE001
        return False


def _git_revision(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _source_snapshot_id(repo_root: Path) -> str:
    revision = _git_revision(repo_root)
    digest = hashlib.sha256((str(repo_root) + revision).encode("utf-8")).hexdigest()[:16].upper()
    return f"SOURCE_{digest}"


def _write_phase0_doc(path: Path, artifact_type: str, item_id: str, kind: str, data: object) -> None:
    payload = {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": {
            "run_id": path.parents[1].name,
            "source_snapshot_id": "SOURCE_PHASE0",
            "source_revision": "unknown",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "items": [{"id": item_id, "kind": kind, "status": "recorded", "data": data}],
        "relations": [],
        "unresolved": [],
    }
    write_text(path, _to_yaml(payload))


def _update_manifest_phase0(base: Path, run_id: str, repo_root: Path) -> None:
    path = base / "manifest.yaml"
    if not path.exists():
        return
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return
        source = data.setdefault("source", {})
        if isinstance(source, dict):
            source["revision"] = _git_revision(repo_root)
            source["snapshot_id"] = _source_snapshot_id(repo_root)
        data["current_run_id"] = run_id
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except Exception:  # noqa: BLE001
        return


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
