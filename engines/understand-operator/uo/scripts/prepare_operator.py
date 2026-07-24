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

from uo._core.ignore import DEFAULT_IGNORE_PATTERNS
from uo._operator.artifacts import init_operator_contract_layout, operator_root, safe_op_name, write_text
from uo._operator.cbm_metadata import write_index_meta
from uo._operator.install_check import compare_installed_skill
from uo._operator.run_context import is_active_run_id, scope_snapshot, read_yaml_mapping
from uo._operator.spec import spec_bundle_hash


# Primary skill junctioned by install.ps1/sh.
_PRIMARY_SKILL_NAME = "uo-init"


def _resolve_installed_skill_check(repo_plugin_root: Path) -> dict[str, object]:
    """Compare installed ``uo-init`` skill against the plugin tree.

    Presence of ``uo-init`` is required. Hash drift is a soft warning (exit 3),
    not a missing-skill hard fail (exit 2).
    """
    skills_root = Path.home() / ".config" / "opencode" / "skills"
    primary = skills_root / _PRIMARY_SKILL_NAME
    if primary.exists():
        check = compare_installed_skill(repo_plugin_root, primary)
        check["primary_skill"] = _PRIMARY_SKILL_NAME
        check["skill_present"] = True
        return check

    return {
        "version": 2,
        "consistent": False,
        "skill_present": False,
        "primary_skill": _PRIMARY_SKILL_NAME,
        "error_code": "MISSING_INSTALLED_SKILL",
        "installed_skill_root": str(primary),
        "mismatches": [
            {
                "path": f"skills/{_PRIMARY_SKILL_NAME}",
                "reason": "installed skill root missing",
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare UO KB layout for acp uo-init. "
            "CBM graph DB indexing is done by MCP index_repository during /uo-init, not by this script."
        )
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the current incomplete UO run (default already reuses incomplete current_run_id).",
    )
    parser.add_argument(
        "--force-new-run",
        action="store_true",
        help="Always create a new UO run (do not use with --write-index-meta mid-scope-confirmation).",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help=(
            "Bind this session's single run id (Pilot state.run_id). "
            "When set, UO writes under runs/<run-id>/ and does not mint a second UO_RUN_* id."
        ),
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help=(
            "Allow minting UO_RUN_* without an active Pilot workflow. "
            "Forbidden when .ascendc-pilot/state/workflow.yaml is active."
        ),
    )
    parser.add_argument(
        "--write-index-meta",
        action="store_true",
        help=(
            "Write/update cbm/index_meta.json after MCP index_repository "
            "(reuses unfinished current_run_id; pass --cbm-project from MCP result)"
        ),
    )
    parser.add_argument("--cbm-project", help="CBM project name returned by MCP list_projects / index_repository")
    parser.add_argument("--cbm-mode", default="fast", help="Recorded MCP index mode label (default: fast)")
    parser.add_argument("--full", action="store_true", help="Record full MCP index mode")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name)
    init_operator_contract_layout(base, op_name, repo_root)
    pilot_state = _load_active_pilot_state(repo_root)
    bound = str(args.run_id or "").strip() or None
    if pilot_state:
        pilot_run = str(pilot_state.get("run_id") or "").strip()
        if args.standalone:
            raise SystemExit(
                "STANDALONE_FORBIDDEN_DURING_ACTIVE_PILOT: "
                "active Pilot workflow requires --run-id without --standalone"
            )
        if not bound:
            raise SystemExit("PILOT_RUN_ID_REQUIRED: active Pilot workflow requires --run-id")
        if pilot_run and bound != pilot_run:
            raise SystemExit(
                f"PILOT_RUN_ID_MISMATCH: --run-id={bound!r} != Pilot state.run_id={pilot_run!r}"
            )
    run_id = _select_run_id(
        base,
        resume=args.resume,
        force_new=args.force_new_run,
        bound_run_id=bound,
        allow_uo_run=not pilot_state,
    )
    phase0 = base / "runs" / run_id / "scope"
    _update_manifest_scope(base, run_id, repo_root)
    check = _resolve_installed_skill_check(Path(__file__).resolve().parents[2])
    _write_scope_doc(
        phase0 / "context.yaml",
        "runs.context",
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
    _write_scope_doc(phase0 / "installed_skill_check.yaml", "runs.installed_skill_check", check)

    # Always finish layout stubs — skill/version issues must not leave scope half-prepared.
    patterns = _load_operator_ignore_patterns(repo_root)
    _write_scope_doc(
        phase0 / "ignore_rules.yaml",
        "runs.ignore_rules",
        {"patterns": patterns},
    )
    for filename, artifact_type in (
        ("scope_scan.yaml", "runs.scope_scan"),
        ("semantic_enrichment.yaml", "runs.semantic_enrichment"),
    ):
        target = phase0 / filename
        if not target.exists():
            _write_scope_doc(target, artifact_type, _scope_pending_defaults(repo_root, op_name, artifact_type))

    if args.write_index_meta or args.cbm_project:
        scope = _current_scope_meta(base)
        status = {
            "available": bool(args.cbm_project),
            "retry_count": 0,
            "fallback": "" if args.cbm_project else "filesystem_scan",
            "last_error": "",
        }
        confirmed_files = scope.get("confirmed_file_list") or []
        write_index_meta(
            base,
            {
                "repo_root": str(repo_root),
                "op_name": op_name,
                "cbm_project": args.cbm_project,
                "indexed_via": "mcp",
                "cbm_mode": "full" if args.full else args.cbm_mode,
                "indexed_at": datetime.now(tz=timezone.utc).isoformat(),
                "project_confirmed": bool(args.cbm_project),
                "prefetch_mode": "mcp_index_repository",
                "index_summary": {},
                "indexed_scope_roots": scope.get("scope_roots") or [],
                "indexed_files": confirmed_files,
                "index_input": "confirmed_file_list",
                "operator_path": scope.get("operator_path") or "",
                "dependency_roots": scope.get("dependency_roots") or [],
                "scope_hash": scope.get("scope_hash") or "",
                "cbm_status": status,
            },
        )
        write_text(
            base / "cbm" / "cbm_mcp_log.md",
            "# CBM Index Log\n\n"
            f"- indexed_via: mcp\n"
            f"- cbm_project: {args.cbm_project or 'pending'}\n"
            f"- indexed_at: {datetime.now(tz=timezone.utc).isoformat()}\n"
            "- agent queries: MCP codebase-memory-mcp tools only\n",
        )

    stub = base / "cbm" / "cbm_mcp_log.md"
    if not stub.exists():
        write_text(
            stub,
            "# CBM Index Log\n\n"
            "Layout prepared. Waiting for scope confirmation before MCP `index_repository`.\n",
        )

    print(f"Prepared UO KB layout for {op_name}")
    print(f"Output: {base}")
    print(f"Run: {run_id}")
    print("CBM: use MCP index_repository only after scope confirmation; pass only confirmed_file_list")
    print("Next: acp uo-scope scan → checkpoint → stage → MCP index → "
          "acp uo-scope record-index --cbm-project <name> → finalize")

    if not check.get("skill_present", check.get("consistent")):
        print(
            "ERROR: installed skill `uo-init` is missing. Reinstall with install.ps1/install.sh.",
            file=sys.stderr,
        )
        print("Run: powershell -ExecutionPolicy Bypass -File install.ps1 opencode", file=sys.stderr)
        print(f"Details: {phase0 / 'installed_skill_check.yaml'}", file=sys.stderr)
        return 2

    if not check.get("consistent"):
        print(
            "WARNING: installed ascendc-pilot-plugin / uo-init is out of sync with this repository "
            "(layout prepared; scope may continue). Re-run install.ps1/install.sh to align.",
            file=sys.stderr,
        )
        print(f"Details: {phase0 / 'installed_skill_check.yaml'}", file=sys.stderr)
        return 3

    return 0


def _select_run_id(
    base: Path,
    *,
    resume: bool,
    force_new: bool,
    bound_run_id: str | None = None,
    allow_uo_run: bool = True,
) -> str:
    """Pick the scope confirmation run directory to write into.

    ACP / Pilot binds **one** run id per session via ``--run-id`` (state.run_id).
    When bound, that id is authoritative — never mint a second ``UO_RUN_*``.

    Without ``--run-id`` (standalone/tests): incomplete ``current_run_id`` is reused
    by default so later scope steps (especially ``--write-index-meta``) do not fork
    a new run and orphan ``scope_scan`` / ``scope_review`` / ``scope_confirmed``.
    """
    if resume and force_new:
        raise SystemExit("--resume and --force-new-run are mutually exclusive")
    if bound_run_id:
        if force_new:
            raise SystemExit(
                "--force-new-run is incompatible with --run-id "
                "(one ACP session uses one run id; start a new workflow for a new id)"
            )
        if not is_active_run_id(bound_run_id):
            raise SystemExit(f"invalid --run-id: {bound_run_id!r}")
        return bound_run_id.strip()
    if not allow_uo_run:
        raise SystemExit("PILOT_RUN_ID_REQUIRED: refuse to mint UO_RUN_* under active Pilot workflow")
    if force_new:
        return _new_run_id()

    current = _current_run_id(base)
    if current is not None:
        receipt = base / "runs" / current / "scope" / "receipt.yaml"
        if not _receipt_passed(receipt):
            # Default + --resume: keep writing into the unfinished run.
            return current
        if resume:
            raise SystemExit(f"current run {current} already has a pass receipt; create a new run instead")
        # Current run already finalized; start a fresh run for a new /uo-init.
        return _new_run_id()

    return _new_run_id()


def _load_active_pilot_state(repo_root: Path) -> dict[str, object] | None:
    """Return Pilot workflow.yaml when an active run is present."""
    candidates = [
        repo_root / ".ascendc-pilot" / "state" / "workflow.yaml",
        repo_root.parent / ".ascendc-pilot" / "state" / "workflow.yaml",
    ]
    # Also check if operator_root nests under project .ascendc-pilot/uo
    for parent in [repo_root, *repo_root.parents]:
        candidates.append(parent / ".ascendc-pilot" / "state" / "workflow.yaml")
    seen: set[str] = set()
    for path in candidates:
        key = path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        data = read_yaml_mapping(path)
        if isinstance(data, dict) and data.get("run_id") and data.get("workflow_id"):
            status = str(data.get("status") or "").lower()
            if status in {"", "running", "rework_required", "human_required", "blocked"}:
                return data
    return None


def _current_run_id(base: Path) -> str | None:
    manifest = base / "manifest.yaml"
    if manifest.exists():
        try:
            import yaml

            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            value = data.get("current_run_id")
            if is_active_run_id(value):
                return str(value).strip()
        except Exception:  # noqa: BLE001
            pass
    return None


def _new_run_id() -> str:
    # Standalone/legacy only. ACP paths must pass --run-id (Pilot state.run_id).
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


def _write_scope_doc(path: Path, artifact_type: str, data: object) -> None:
    base = path.parents[3]
    run_id = path.parents[1].name
    payload = {
        "version": 1,
        "artifact": {"type": artifact_type, "schema_version": 1, "owner": "deterministic-uo-engine"},
        "snapshot": scope_snapshot(base, run_id),
    }
    if isinstance(data, dict):
        payload.update(data)
    else:
        payload["payload"] = data
    write_text(path, _to_yaml(payload))


def _scope_pending_defaults(repo_root: Path, op_name: str, artifact_type: str) -> dict[str, object]:
    if artifact_type == "runs.scope_scan":
        return {
            "status": "pending",
            "op_name": op_name,
            "project_root": str(repo_root),
            "operator_path": "",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "scan_method": {
                "filesystem_tool": "",
                "cbm_project": "",
                "ignore_rules_applied": False,
                "max_dependency_depth": 0,
            },
            "directories": [],
            "operator_roots": [],
            "scope_roots": [],
            "dependency_roots": [],
            "include_search_paths": [],
            "uncertain_include_paths": [],
            "seed_files": {},
            "files": {
                "initial_operator_files": [],
                "dependency_files": [],
                "external_system_files": [],
                "third_party_files": [],
                "generated_files": [],
                "excluded_files": [],
                "uncertain_files": [],
            },
            "dependency_edges": [],
            "symbols": {},
            "global_candidates": {},
            "architecture_variants": [],
            "large_files": [],
            "warnings": [],
        }
    if artifact_type == "runs.semantic_enrichment":
        return {
            "status": "pending",
            "architecture_filter": {"included": [], "excluded": []},
            "cbm_queries": [],
            "architecture_variants": [],
            "excluded_architectures": [],
            "confirmed_scope_additions": [],
            "unresolved": [],
            "warnings": [],
            "fallback": "",
        }
    return {}


def _update_manifest_scope(base: Path, run_id: str, repo_root: Path) -> None:
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


def _current_scope_meta(base: Path) -> dict[str, Any]:
    try:
        run_id = _current_run_id(base)
    except Exception:  # noqa: BLE001
        return {}
    phase0 = base / "runs" / run_id / "scope"
    confirmed = read_yaml_mapping(phase0 / "scope_confirmed.yaml")
    if confirmed:
        files = confirmed.get("confirmed_file_list") if isinstance(confirmed.get("confirmed_file_list"), list) else []
        roots = _roots_for_confirmed_files(files)
        digest = hashlib.sha256()
        for item in files:
            digest.update(str(item).encode("utf-8"))
            digest.update(b"\0")
        return {
            "operator_path": "",
            "scope_roots": roots,
            "dependency_roots": [],
            "confirmed_file_list": files,
            "scope_hash": "sha256:" + digest.hexdigest(),
        }
    scan = read_yaml_mapping(phase0 / "scope_scan.yaml")
    if not scan:
        return {}
    scope_roots = scan.get("scope_roots") if isinstance(scan.get("scope_roots"), list) else []
    dependency_roots = scan.get("dependency_roots") if isinstance(scan.get("dependency_roots"), list) else []
    digest = hashlib.sha256()
    for item in scope_roots:
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\0")
    return {
        "operator_path": scan.get("operator_path") or "",
        "scope_roots": scope_roots,
        "dependency_roots": dependency_roots,
        "scope_hash": "sha256:" + digest.hexdigest(),
    }


def _roots_for_confirmed_files(files: list[Any]) -> list[dict[str, str]]:
    roots: dict[str, dict[str, str]] = {}
    for item in files:
        raw = item.get("path") if isinstance(item, dict) else item
        path = str(raw or "").replace("\\", "/")
        if not path:
            continue
        parent = str(Path(path).parent).replace("\\", "/")
        if parent == ".":
            parent = "."
        roots.setdefault(parent, {"path": parent, "kind": "confirmed_files", "reason": "human-confirmed scope"})
    return sorted(roots.values(), key=lambda item: item["path"])


def _load_operator_ignore_patterns(repo_root: Path) -> list[str]:
    base = repo_root / ".ascendc-pilot"
    base.mkdir(parents=True, exist_ok=True)
    path = base / ".ascendcagentignore"
    if not path.exists():
        lines = [
            "# ascendc-pilot ignore rules",
            "",
            "# Default ignored paths:",
            *[f"# {p}" for p in DEFAULT_IGNORE_PATTERNS],
            "",
            "# From .gitignore:",
        ]
        gitignore = repo_root / ".gitignore"
        if gitignore.exists():
            for line in gitignore.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    lines.append(stripped)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    for line in path.read_text(encoding="utf-8").splitlines():
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
