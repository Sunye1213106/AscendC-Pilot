from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._core.ignore import DEFAULT_IGNORE_PATTERNS, should_ignore
from uo._operator.artifacts import existing_operator_root, safe_op_name, write_text
from uo._operator.run_context import active_run_id, phase0_snapshot

SOURCE_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".py", ".proto"}
HOST_HINTS = ("op_host", "host", "tiling")
KERNEL_HINTS = ("op_kernel", "kernel")
INPUT_OUTPUT_HINTS = ("op_api", "proto", "infer", "register")
EXCLUDED_HINTS = ("test", "tests", "ut", "st", "example", "examples", "third_party", "build", "dist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 0 lightweight operator scope discovery.")
    parser.add_argument("repo", nargs="?", default=".", help="Operator package root (KB always stays here)")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--seed", action="append", default=[], help="User-provided repo-relative candidate file. May be repeated.")
    parser.add_argument("--filesystem-tool", default="rg/glob", help="Recorded discovery tool label")
    parser.add_argument(
        "--architecture",
        default="arch35",
        help="Keep only this architecture under op_host/op_kernel (other arch* dirs excluded). Empty to disable.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = existing_operator_root(repo_root, op_name)
    if not (base / "manifest.yaml").exists():
        print(f"KB not found: {base}", file=sys.stderr)
        print("Run prepare_operator.py before macro_scope_scan.py.", file=sys.stderr)
        return 2

    run_id = active_run_id(base)
    phase0 = base / "runs" / run_id / "phase0"
    patterns = _load_ignore_patterns(repo_root)

    # AscendC: discover sibling/parent common for indexing, but KB stays under operator subdir.
    workspace_root, op_rel_prefix, common_rel, common_notes = _resolve_workspace_with_common(repo_root, op_name)
    patterns = _load_ignore_patterns(workspace_root)
    all_files = _discover_file_names(workspace_root, patterns)
    candidate_paths = _candidate_paths(workspace_root, op_name, all_files, args.seed, op_rel_prefix=op_rel_prefix)
    architecture = str(args.architecture or "").strip()
    if architecture:
        before = len(candidate_paths)
        candidate_paths = _filter_architecture(candidate_paths, architecture, op_rel_prefix=op_rel_prefix)
        common_notes.append(
            f"architecture_filter={architecture}: kept {len(candidate_paths)}/{before} operator candidates"
        )
    if common_rel:
        common_files = _common_library_files(all_files, common_rel)
        if architecture:
            common_files = _filter_architecture(common_files, architecture, op_rel_prefix="")
        referenced = _prune_common_by_includes(workspace_root, candidate_paths, common_files)
        candidate_paths = sorted(set(candidate_paths) | set(referenced))
        common_notes.append(
            f"common library at {common_rel}: discovered={len(common_files)} referenced_by_includes={len(referenced)}"
        )

    proposal = _scope_proposal(
        base,
        run_id,
        repo_root,
        op_name,
        all_files,
        candidate_paths,
        args.filesystem_tool,
        extra_warnings=common_notes,
        workspace_root=workspace_root,
        operator_path=op_rel_prefix,
        architecture=architecture,
    )

    write_text(phase0 / "scope_proposal.yaml", _to_yaml(proposal))
    write_text(
        phase0 / "scope_scan.yaml",
        _to_yaml(
            _compat_scope_scan(
                base,
                run_id,
                repo_root,
                op_name,
                proposal,
                workspace_root=workspace_root,
                operator_path=op_rel_prefix,
                common_rel=common_rel,
            )
        ),
    )
    print(f"Wrote {phase0 / 'scope_proposal.yaml'}")
    print(f"KB_ROOT={base} (operator_subdir)")
    if workspace_root.resolve() != repo_root.resolve():
        print(f"WORKSPACE_ROOT={workspace_root} (common discovery only; do NOT move KB here)")
    if common_rel:
        print(f"Detected AscendC common library: {common_rel} (workspace={workspace_root})")
    if architecture:
        print(f"Architecture filter: {architecture}")
    print("Phase 0 scope proposal is ready. Stop here until the user confirms the scope.")
    return 0


def _load_ignore_patterns(repo_root: Path) -> list[str]:
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    for path in (repo_root / ".gitignore", repo_root / ".understand-operator" / ".understandoperatorignore"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    return patterns


def _discover_file_names(repo_root: Path, patterns: list[str]) -> list[str]:
    """Phase0 intentionally only performs lightweight scope discovery.

    Deep operator understanding starts after CBM indexing. This function records
    path names only, using rg --files when available and a glob-style fallback.
    It does not read source contents, build ASTs, or compute dependency graphs.
    """
    result = _rg_files(repo_root)
    if result is None:
        result = [
            path.relative_to(repo_root).as_posix()
            for path in repo_root.glob("**/*")
            if path.is_file()
        ]
    return sorted(rel for rel in result if not should_ignore(rel, patterns))


def _rg_files(repo_root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["rg", "--files"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in {0, 1}:
        return None
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _candidate_paths(
    repo_root: Path,
    op_name: str,
    all_files: list[str],
    user_seeds: list[str],
    *,
    op_rel_prefix: str = "",
) -> list[str]:
    tokens = _name_tokens(op_name)
    matched: set[str] = set()
    prefix = op_rel_prefix.replace("\\", "/").strip("/")
    for rel in all_files:
        lower = rel.lower()
        stem = Path(rel).stem.lower()
        if Path(rel).suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        # When workspace was expanded for sibling common/, keep operator package files only
        # in the primary match pass (common files are added via include pruning).
        if prefix and not (rel == prefix or rel.startswith(prefix + "/") or rel.startswith("common/")):
            # still allow loose name matches under workspace
            if not any(token in lower or token in stem for token in tokens):
                continue
        parts = set(lower.split("/"))
        if parts & {"op_host", "op_kernel", "op_api", "op_graph"}:
            # Skip foreign common dumps in this pass; common handled separately.
            if rel.startswith("common/"):
                continue
            matched.add(rel)
            continue
        if any(token in lower or token in stem for token in tokens):
            if not rel.startswith("common/"):
                matched.add(rel)
    for seed in user_seeds:
        rel_path = (repo_root / seed).resolve()
        try:
            seed_rel = rel_path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if seed_rel in all_files:
            matched.add(seed_rel)
    return sorted(matched)


def _resolve_workspace_with_common(repo_root: Path, op_name: str) -> tuple[Path, str, str, list[str]]:
    """Return (workspace_root, op_rel_prefix, common_rel, notes)."""
    notes: list[str] = []
    looks_like_op = (repo_root / "op_host").is_dir() or (repo_root / "op_kernel").is_dir()
    # 1) sibling common next to operator package
    sibling = repo_root.parent / "common"
    if looks_like_op and sibling.is_dir():
        notes.append(f"ascendc_common_upscan: sibling common at {sibling.as_posix()}")
        return repo_root.parent, repo_root.name, "common", notes
    # 2) repo_root itself is workspace containing op + common
    direct = repo_root / "common"
    op_dir = repo_root / op_name
    if direct.is_dir() and (op_dir.is_dir() or looks_like_op):
        notes.append(f"ascendc_common_upscan: workspace-local common at {direct.as_posix()}")
        prefix = op_name if op_dir.is_dir() else ""
        return repo_root, prefix, "common", notes
    # 3) walk parents (max 3) for */common beside an op-like folder
    cur = repo_root
    for _ in range(3):
        parent = cur.parent
        if parent == cur:
            break
        cand = parent / "common"
        if cand.is_dir() and ((parent / op_name).is_dir() or looks_like_op):
            notes.append(f"ascendc_common_upscan: parent common at {cand.as_posix()}")
            prefix = op_name if (parent / op_name).is_dir() else (repo_root.name if looks_like_op else "")
            return parent, prefix, "common", notes
        cur = parent
    return repo_root, "", "", notes


def _common_library_files(all_files: list[str], common_rel: str) -> list[str]:
    prefix = common_rel.replace("\\", "/").rstrip("/") + "/"
    out = []
    for rel in all_files:
        if not rel.startswith(prefix):
            continue
        if Path(rel).suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        if _is_excluded(rel):
            continue
        out.append(rel)
    return sorted(out)


_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]', re.MULTILINE)


def _prune_common_by_includes(workspace_root: Path, op_files: list[str], common_files: list[str]) -> list[str]:
    """Keep only common files referenced (directly/indirectly) via #include from operator files."""
    if not common_files:
        return []
    by_name: dict[str, list[str]] = {}
    by_rel: dict[str, str] = {}
    for rel in common_files:
        by_rel[rel.replace("\\", "/")] = rel
        by_name.setdefault(Path(rel).name.lower(), []).append(rel)

    selected: set[str] = set()
    frontier: list[str] = list(op_files)
    seen_sources: set[str] = set()
    # Bounded closure: operator files + newly accepted common headers.
    while frontier:
        src_rel = frontier.pop()
        if src_rel in seen_sources:
            continue
        seen_sources.add(src_rel)
        path = workspace_root / src_rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Only scan include lines (cheap); ignore huge bodies.
        for match in _INCLUDE_RE.finditer(text[:200_000]):
            inc = match.group(1).replace("\\", "/").strip()
            if not inc:
                continue
            hit = None
            if inc in by_rel:
                hit = by_rel[inc]
            elif inc.startswith("common/") and inc in by_rel:
                hit = by_rel[inc]
            else:
                # Suffix / trailing-path match only when the include has a directory
                # component. Never match on unique basename alone (shared names like
                # pse.h across sibling libs cause false hits).
                if "/" not in inc:
                    continue
                name = Path(inc).name.lower()
                cands = by_name.get(name) or []
                for cand in cands:
                    norm = cand.replace("\\", "/")
                    if norm.endswith("/" + inc) or norm == inc:
                        hit = cand
                        break
            if hit and hit not in selected:
                selected.add(hit)
                frontier.append(hit)
    return sorted(selected)


def _filter_architecture(paths: list[str], architecture: str, *, op_rel_prefix: str) -> list[str]:
    """Drop other arch* directories under op_host/op_kernel; keep non-arch paths and matching architecture."""
    arch = architecture.strip().lower()
    if not arch:
        return paths
    out: list[str] = []
    for rel in paths:
        parts = [p.lower() for p in Path(rel.replace("\\", "/")).parts]
        # Find archXX segment under host/kernel trees
        arch_idxs = [i for i, p in enumerate(parts) if re.fullmatch(r"arch\d+", p)]
        if not arch_idxs:
            out.append(rel)
            continue
        # Keep if any arch segment matches target; drop if only other arches
        if any(parts[i] == arch for i in arch_idxs):
            out.append(rel)
    return out


def _scope_proposal(
    base: Path,
    run_id: str,
    repo_root: Path,
    op_name: str,
    all_files: list[str],
    candidates: list[str],
    tool_label: str,
    *,
    extra_warnings: list[str] | None = None,
    workspace_root: Path | None = None,
    operator_path: str = "",
    architecture: str = "",
) -> dict[str, Any]:
    excluded = sorted({rel for rel in all_files if _is_excluded(rel)})
    candidate_files = {
        "input_output": [],
        "host": [],
        "tiling": [],
        "kernel": [],
        "headers": [],
        "other": [],
    }
    for rel in candidates:
        bucket = _bucket(rel)
        candidate_files[bucket].append(rel)
        if bucket == "host" and "tiling" in rel.lower() and rel not in candidate_files["tiling"]:
            candidate_files["tiling"].append(rel)

    warnings = list(extra_warnings or [])
    if not candidates:
        warnings.append(f"No source filename matched operator name {op_name!r}; add files manually during scope review.")

    ws = (workspace_root or repo_root).resolve()
    return {
        "version": 1,
        "artifact": {"type": "runs.scope_proposal", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": phase0_snapshot(base, run_id),
        "operator": op_name,
        "status": "proposed",
        # KB anchor: always the operator package (CLI repo), never parent workspace.
        "project_root": repo_root.as_posix(),
        "workspace_root": ws.as_posix(),
        "operator_path": operator_path,
        "architecture": architecture,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "discovery_policy": {
            "allowed_tools": ["rg", "glob", "find", "ls", "tree"],
            "used_tools": [tool_label],
            "source_read_policy": "path_names_and_include_lines_for_common_prune",
            "cbm_indexing": "blocked_until_human_confirmation",
            "ascendc_common_upscan": True,
            "kb_location": "operator_subdirectory_only",
        },
        "candidate_files": candidate_files,
        "candidate_directories": _candidate_dirs(candidates),
        "excluded": _excluded_labels(excluded),
        "excluded_files_sample": excluded[:50],
        "warnings": warnings,
    }


def _bucket(rel: str) -> str:
    lower = rel.lower()
    suffix = Path(lower).suffix
    if suffix in {".h", ".hh", ".hpp", ".hxx"}:
        return "headers"
    if any(hint in lower for hint in KERNEL_HINTS):
        return "kernel"
    if any(hint in lower for hint in HOST_HINTS):
        return "host"
    if any(hint in lower for hint in INPUT_OUTPUT_HINTS):
        return "input_output"
    return "other"


def _candidate_dirs(paths: list[str]) -> list[dict[str, str]]:
    dirs = sorted({Path(path).parent.as_posix() for path in paths if Path(path).parent.as_posix() != "."})
    return [{"path": directory, "reason": "contains operator-name candidate file"} for directory in dirs]


def _is_excluded(rel: str) -> bool:
    parts = {part.lower() for part in Path(rel).parts}
    return bool(parts.intersection(EXCLUDED_HINTS))


def _excluded_labels(paths: list[str]) -> list[str]:
    labels = []
    for label in ("tests", "examples", "third_party", "build", "dist"):
        if any(label in path.lower().split("/") for path in paths):
            labels.append(label)
    return labels


def _compat_scope_scan(
    base: Path,
    run_id: str,
    repo_root: Path,
    op_name: str,
    proposal: dict[str, Any],
    *,
    workspace_root: Path | None = None,
    operator_path: str = "",
    common_rel: str = "",
) -> dict[str, Any]:
    candidate_files = proposal["candidate_files"]
    initial = [
        {"path": path, "role": _role_for_path(path), "include_reason": "phase0 scope proposal"}
        for path in _flatten_candidate_files(candidate_files)
    ]
    scope_roots = proposal["candidate_directories"] or [{"path": ".", "kind": "operator", "reason": "repository root fallback"}]
    ws = (workspace_root or repo_root).resolve()
    return {
        "version": 1,
        "artifact": {"type": "runs.scope_scan", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": phase0_snapshot(base, run_id),
        "status": "complete",
        "op_name": op_name,
        "project_root": repo_root.as_posix(),
        "workspace_root": ws.as_posix(),
        "operator_path": operator_path or str(proposal.get("operator_path") or ""),
        "common_rel": common_rel or "",
        "generated_at": proposal["generated_at"],
        "scan_method": {
            "filesystem_tool": "rg/glob",
            "cbm_project": "",
            "ignore_rules_applied": True,
            "max_dependency_depth": 0,
            "policy": "lightweight_scope_discovery_only",
            "kb_location": "operator_subdirectory_only",
        },
        "directories": {"included": [item["path"] for item in proposal["candidate_directories"]], "excluded": proposal["excluded"]},
        "operator_roots": [item["path"] for item in proposal["candidate_directories"]],
        "scope_roots": scope_roots,
        "dependency_roots": [],
        "include_search_paths": [],
        "uncertain_include_paths": [],
        "seed_files": {"name_matched_seeds": initial},
        "files": {
            "initial_operator_files": initial,
            "dependency_files": [],
            "external_system_files": [],
            "third_party_files": [],
            "generated_files": [],
            "excluded_files": [{"path": path, "role": "excluded_by_phase0"} for path in proposal["excluded_files_sample"]],
            "uncertain_files": [],
        },
        "dependency_edges": [],
        "symbols": {
            "registration_candidates": [],
            "host_entry_candidates": [],
            "kernel_entry_candidates": [],
            "api_candidates": [],
            "proto_candidates": [],
            "golden_candidates": [],
        },
        "global_candidates": {
            "registration_candidates": [],
            "host_entry_candidates": [],
            "kernel_entry_candidates": [],
        },
        "architecture_variants": [],
        "large_files": [],
        "warnings": proposal["warnings"],
    }


def _flatten_candidate_files(candidate_files: dict[str, list[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in ("input_output", "host", "tiling", "kernel", "headers", "other"):
        for path in candidate_files.get(group, []):
            if path not in seen:
                result.append(path)
                seen.add(path)
    return result


def _role_for_path(path: str) -> str:
    bucket = _bucket(path)
    return "input_output" if bucket == "input_output" else bucket


def _name_tokens(op_name: str) -> list[str]:
    tokens = [token.lower() for token in re.split(r"[^A-Za-z0-9]+", op_name) if token]
    compact = re.sub(r"[^A-Za-z0-9]+", "", op_name).lower()
    if compact and compact not in tokens:
        tokens.append(compact)
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", op_name).lower()
    if snake and snake not in tokens:
        snake_tokens = [token for token in snake.split("_") if token]
        tokens.extend(token for token in snake_tokens if token not in tokens)
        acronym = "".join(token[0] for token in snake_tokens if token)
        if acronym and acronym not in tokens:
            tokens.append(acronym)
    return tokens


def _to_yaml(data: Any) -> str:
    try:
        import yaml

        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception:  # noqa: BLE001
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
