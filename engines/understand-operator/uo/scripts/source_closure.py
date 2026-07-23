"""Controlled source-closure restage / re-index loop.

Discovers missing include / cmake / registration / type dependencies with hard
limits. Never scans the whole parent repo or all sibling operators.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo._operator.run_context import active_run_id
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.arch_path import arch_compatible
from uo.scripts.stage_cbm_scope import stage_cbm_scope

INCLUDE_RE = re.compile(r'#\s*include\s+"([^"]+)"')
DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_NEW = 40
ALLOWED_EVIDENCE = {
    "include",
    "cmake_source",
    "cmake_dependency",
    "registration",
    "macro_provider",
    "type_declaration",
    "template_declaration",
    "template_instantiation",
    "tilingdata_definition",
    "tilingkey_schema",
}


def run_source_closure(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_new_files_per_round: int = DEFAULT_MAX_NEW,
    restage: bool = True,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    op_name = safe_op_name(op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    run_id = active_run_id(uo_root)
    scope_dir = uo_root / "runs" / run_id / "scope"
    confirmed = read_yaml(scope_dir / "scope_confirmed.yaml")
    scan = read_yaml(scope_dir / "scope_scan.yaml")
    workspace = Path(str(scan.get("workspace_root") or repo_root)).resolve()

    source_files = _normalize_list(
        confirmed.get("confirmed_source_files") or confirmed.get("confirmed_file_list") or []
    )
    build_files = _normalize_list(confirmed.get("confirmed_build_files") or [])
    doc_files = _normalize_list(confirmed.get("confirmed_documentation_files") or [])
    allowed_roots = list(confirmed.get("closure", {}).get("allowed_roots") or [])
    if not allowed_roots:
        allowed_roots = _default_allowed_roots(workspace, repo_root, op_name, scan)

    closure_meta = {
        "round": int((confirmed.get("closure") or {}).get("round") or 0),
        "max_rounds": int(max_rounds),
        "max_new_files_per_round": int(max_new_files_per_round),
        "allowed_roots": allowed_roots,
        "allowed_evidence_types": sorted(ALLOWED_EVIDENCE),
    }
    unresolved: list[dict[str, Any]] = []
    rounds_log: list[dict[str, Any]] = []

    for _ in range(int(max_rounds)):
        missing = _discover_missing_includes(
            workspace,
            repo_root,
            source_files,
            architecture=architecture,
            allowed_roots=allowed_roots,
        )
        # cmake-selected sources
        build_ev = read_yaml(uo_root / "ir" / "build_evidence.yaml")
        for sel in build_ev.get("source_selections") or []:
            for f in sel.get("files") or []:
                rel = _maybe_resolve_dep(workspace, repo_root, f, allowed_roots, architecture)
                if rel and rel not in source_files and rel not in build_files:
                    missing.append({"path": rel, "evidence_type": "cmake_source", "from": sel.get("file_path")})

        # dedupe missing
        uniq: dict[str, dict[str, Any]] = {}
        for item in missing:
            path = item["path"]
            if path in source_files or path in build_files:
                continue
            if item.get("evidence_type") not in ALLOWED_EVIDENCE:
                continue
            uniq[path] = item
        missing = list(uniq.values())
        if not missing:
            break

        if len(missing) > max_new_files_per_round:
            kept = missing[:max_new_files_per_round]
            for item in missing[max_new_files_per_round:]:
                unresolved.append(
                    {
                        "severity": "blocking" if item.get("evidence_type") in {"tilingdata_definition", "tilingkey_schema", "registration"} else "degraded",
                        "code": "missing_scope_dependency_round_limit",
                        "related_symbols": [],
                        "candidate_files": [item["path"]],
                        "evidence_present": [item.get("evidence_type"), item.get("from")],
                        "evidence_missing": ["scope_expansion_capacity"],
                        "reason": f"exceeded max_new_files_per_round={max_new_files_per_round}",
                    }
                )
            missing = kept

        added_source: list[str] = []
        added_build: list[str] = []
        for item in missing:
            path = item["path"]
            if path.endswith("CMakeLists.txt") or path.endswith(".cmake"):
                if path not in build_files:
                    build_files.append(path)
                    added_build.append(path)
            else:
                if path not in source_files:
                    source_files.append(path)
                    added_source.append(path)

        closure_meta["round"] = int(closure_meta["round"]) + 1
        rounds_log.append(
            {
                "round": closure_meta["round"],
                "added_source_files": added_source,
                "added_build_files": added_build,
            }
        )
        if not added_source and not added_build:
            break

        _write_confirmed(
            scope_dir,
            confirmed,
            source_files=source_files,
            build_files=build_files,
            doc_files=doc_files,
            closure_meta=closure_meta,
        )
        if restage and added_source:
            stage_cbm_scope(repo_root, op_name)

    # still-missing includes after loop → unresolved
    still = _discover_missing_includes(
        workspace, repo_root, source_files, architecture=architecture, allowed_roots=allowed_roots
    )
    for item in still:
        if item["path"] in source_files:
            continue
        unresolved.append(
            {
                "severity": "degraded",
                "code": "missing_scope_dependency",
                "related_symbols": [],
                "candidate_files": [item["path"]],
                "evidence_present": [item.get("evidence_type"), item.get("from")],
                "evidence_missing": ["in_scope_file"],
                "reason": "dependency not added within closure limits or outside allowed_roots",
            }
        )

    _write_confirmed(
        scope_dir,
        confirmed,
        source_files=source_files,
        build_files=build_files,
        doc_files=doc_files,
        closure_meta=closure_meta,
    )
    result = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "confirmed_source_files": source_files,
        "confirmed_build_files": build_files,
        "confirmed_documentation_files": doc_files,
        "closure": closure_meta,
        "rounds": rounds_log,
        "unresolved": unresolved,
    }
    write_yaml(scope_dir / "source_closure.yaml", result)
    if unresolved:
        _merge_unresolved(uo_root, unresolved)
    return result


def _write_confirmed(
    scope_dir: Path,
    previous: dict[str, Any],
    *,
    source_files: list[str],
    build_files: list[str],
    doc_files: list[str],
    closure_meta: dict[str, Any],
) -> None:
    payload = dict(previous or {})
    payload["confirmed_source_files"] = [{"path": p} for p in source_files]
    payload["confirmed_build_files"] = [{"path": p} for p in build_files]
    payload["confirmed_documentation_files"] = [{"path": p} for p in doc_files]
    # CBM staging continues to read confirmed_file_list = sources only
    payload["confirmed_file_list"] = [{"path": p} for p in source_files]
    payload["closure"] = closure_meta
    write_yaml(scope_dir / "scope_confirmed.yaml", payload)


def _discover_missing_includes(
    workspace: Path,
    repo_root: Path,
    source_files: list[str],
    *,
    architecture: str,
    allowed_roots: list[str],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    known = set(source_files)
    for rel in list(source_files):
        path = _resolve(workspace, repo_root, rel)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in INCLUDE_RE.finditer(text):
            inc = match.group(1).strip()
            resolved = _resolve_include(path, workspace, repo_root, inc, allowed_roots, architecture)
            if resolved and resolved not in known:
                missing.append({"path": resolved, "evidence_type": "include", "from": rel})
    return missing


def _resolve_include(
    from_path: Path,
    workspace: Path,
    repo_root: Path,
    include_name: str,
    allowed_roots: list[str],
    architecture: str,
) -> str | None:
    candidates = [
        from_path.parent / include_name,
        workspace / include_name,
        repo_root / include_name,
    ]
    # sibling search under allowed roots only
    for root in allowed_roots:
        base = workspace / root if not Path(root).is_absolute() else Path(root)
        candidates.append(base / include_name)
        candidates.append(base / Path(include_name).name)
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        try:
            rel = resolved.relative_to(workspace).as_posix()
        except ValueError:
            try:
                rel = resolved.relative_to(repo_root).as_posix()
            except ValueError:
                continue
        if not _within_allowed(rel, allowed_roots):
            continue
        if not arch_compatible(rel, architecture):
            continue
        return rel
    return None


def _maybe_resolve_dep(
    workspace: Path,
    repo_root: Path,
    token: str,
    allowed_roots: list[str],
    architecture: str,
) -> str | None:
    token = token.strip().strip('"')
    if not token or token.startswith("$") or token.startswith("<"):
        return None
    for base in (workspace, repo_root):
        cand = base / token
        if cand.is_file():
            try:
                rel = cand.resolve().relative_to(workspace).as_posix()
            except ValueError:
                try:
                    rel = cand.resolve().relative_to(repo_root).as_posix()
                except ValueError:
                    return None
            if _within_allowed(rel, allowed_roots) and arch_compatible(rel, architecture):
                return rel
    return None


def _within_allowed(rel: str, allowed_roots: list[str]) -> bool:
    rel_n = rel.replace("\\", "/")
    if not allowed_roots:
        return True
    for root in allowed_roots:
        root_n = str(root).replace("\\", "/").rstrip("/") + "/"
        if rel_n == str(root).replace("\\", "/").rstrip("/") or rel_n.startswith(root_n):
            return True
    return False


def _default_allowed_roots(workspace: Path, repo_root: Path, op_name: str, scan: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    op_rel = str(scan.get("operator_path") or op_name or repo_root.name).replace("\\", "/").strip("/")
    if op_rel:
        roots.append(op_rel)
    common = str(scan.get("common_rel") or "").replace("\\", "/").strip("/")
    if common:
        roots.append(common)
    # when repo_root IS the operator package
    try:
        rel = repo_root.resolve().relative_to(workspace).as_posix()
        if rel and rel not in roots:
            roots.append(rel)
    except ValueError:
        roots.append(".")
    return roots


def _resolve(workspace: Path, repo_root: Path, rel: str) -> Path | None:
    for base in (workspace, repo_root):
        cand = base / rel
        if cand.is_file():
            return cand
    return None


def _normalize_list(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            path = str(item.get("path") or "").replace("\\", "/").strip()
        else:
            path = str(item or "").replace("\\", "/").strip()
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _merge_unresolved(uo_root: Path, items: list[dict[str, Any]]) -> None:
    path = uo_root / "ir" / "unresolved.yaml"
    data = read_yaml(path)
    existing = list(data.get("items") or [])
    codes = {(x.get("code"), tuple(x.get("candidate_files") or [])) for x in existing}
    for item in items:
        key = (item.get("code"), tuple(item.get("candidate_files") or []))
        if key in codes:
            continue
        existing.append(item)
    write_yaml(path, {"version": 1, "items": existing})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controlled source closure restage loop")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument("--max-new-files", type=int, default=DEFAULT_MAX_NEW)
    parser.add_argument("--no-restage", action="store_true")
    args = parser.parse_args(argv)
    result = run_source_closure(
        Path(args.repo).resolve(),
        args.op_name,
        architecture=args.architecture,
        max_rounds=args.max_rounds,
        max_new_files_per_round=args.max_new_files,
        restage=not args.no_restage,
    )
    print(
        f"closure_round={result['closure']['round']} "
        f"sources={len(result['confirmed_source_files'])} "
        f"build={len(result['confirmed_build_files'])} "
        f"unresolved={len(result['unresolved'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
