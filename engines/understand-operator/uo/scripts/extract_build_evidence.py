"""Deterministic CMake / build-config evidence extractor.

Build files are first-class evidence but must NOT be staged into CBM source
indexes. Controllability defaults to compile_time / platform_fixed so TG must
not treat them as CSV-controllable inputs.
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
from uo.scripts.semantic_identity import mint_edge_id

TARGET_SOURCES_RE = re.compile(
    r"target_sources\s*\(\s*([^\s\)]+)[^)]*?((?:PRIVATE|PUBLIC|INTERFACE)\s+[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
ADD_MODULES_RE = re.compile(r"add_modules_sources[^\(]*\(([^\)]*)\)", re.IGNORECASE | re.DOTALL)
ADD_OPS_COMPILE_RE = re.compile(r"add_ops_compile_options\s*\(([^\)]*)\)", re.IGNORECASE | re.DOTALL)
COMPUTE_UNIT_RE = re.compile(r"\bASCEND_COMPUTE_UNIT\b[^\n]*", re.IGNORECASE)
OPTION_RE = re.compile(r"\boption\s*\(\s*([A-Za-z0-9_]+)\s+\"([^\"]*)\"\s+(ON|OFF)\)", re.IGNORECASE)
D_MACRO_RE = re.compile(r"-D([A-Za-z_][A-Za-z0-9_]*)(?:=(\S+))?")
IF_PLATFORM_RE = re.compile(
    r"\bif\s*\(\s*(?:ASCEND_COMPUTE_UNIT|CMAKE_SYSTEM_PROCESSOR|BUILD_OPS_[A-Z0-9_]+)\b([^)]*)\)",
    re.IGNORECASE,
)
INCLUDE_DIR_RE = re.compile(r"(?:include_directories|target_include_directories)\s*\(([^\)]*)\)", re.IGNORECASE | re.DOTALL)


def extract_build_evidence(repo_root: Path, op_name: str) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    op_name = safe_op_name(op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    build_files = _collect_build_files(uo_root, repo_root)

    targets: list[dict[str, Any]] = []
    source_selections: list[dict[str, Any]] = []
    compile_options: list[dict[str, Any]] = []
    compute_units: list[dict[str, Any]] = []
    platform_predicates: list[dict[str, Any]] = []
    dependency_dirs: list[dict[str, Any]] = []
    determinants: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for rel in build_files:
        path = _resolve_path(repo_root, uo_root, rel)
        if path is None or not path.is_file():
            unresolved.append(
                {
                    "severity": "degraded",
                    "code": "build_file_missing",
                    "related_symbols": [],
                    "candidate_files": [rel],
                    "evidence_present": [],
                    "evidence_missing": ["file_content"],
                    "reason": f"confirmed build file not readable: {rel}",
                }
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in TARGET_SOURCES_RE.finditer(text):
            target = match.group(1).strip()
            body = match.group(2)
            files = _tokenize_cmake_args(body)
            source_selections.append(
                {
                    "kind": "target_sources",
                    "target": target,
                    "files": files,
                    "file_path": rel,
                    "line": text.count("\n", 0, match.start()) + 1,
                }
            )
            determinants.append(_det("SourceSelection", f"target_sources:{target}", rel, "compile_time"))
            targets.append({"name": target, "file_path": rel})
        for match in ADD_MODULES_RE.finditer(text):
            args = _tokenize_cmake_args(match.group(1))
            source_selections.append(
                {
                    "kind": "add_modules_sources",
                    "target": "",
                    "files": args,
                    "file_path": rel,
                    "line": text.count("\n", 0, match.start()) + 1,
                }
            )
            determinants.append(_det("SourceSelection", "add_modules_sources", rel, "compile_time"))
        for match in ADD_OPS_COMPILE_RE.finditer(text):
            args = match.group(1)
            macros = [{"name": m.group(1), "value": m.group(2) or "1"} for m in D_MACRO_RE.finditer(args)]
            compile_options.append(
                {
                    "kind": "add_ops_compile_options",
                    "raw": " ".join(args.split()),
                    "macros": macros,
                    "file_path": rel,
                    "line": text.count("\n", 0, match.start()) + 1,
                }
            )
            for macro in macros:
                determinants.append(
                    _det("CompileMacro", macro["name"], rel, "compile_time", value=macro["value"])
                )
            determinants.append(_det("BuildConfig", "add_ops_compile_options", rel, "compile_time"))
        for match in COMPUTE_UNIT_RE.finditer(text):
            compute_units.append(
                {
                    "raw": match.group(0).strip(),
                    "file_path": rel,
                    "line": text.count("\n", 0, match.start()) + 1,
                }
            )
            determinants.append(_det("PlatformInfo", "ASCEND_COMPUTE_UNIT", rel, "platform_fixed"))
        for match in OPTION_RE.finditer(text):
            name, _help, default = match.group(1), match.group(2), match.group(3)
            determinants.append(
                _det("BuildConfig", name, rel, "compile_time", value=default.upper())
            )
        for match in IF_PLATFORM_RE.finditer(text):
            platform_predicates.append(
                {
                    "raw": match.group(0).strip(),
                    "file_path": rel,
                    "line": text.count("\n", 0, match.start()) + 1,
                }
            )
            determinants.append(_det("PlatformInfo", match.group(0).strip()[:80], rel, "platform_fixed"))
        for match in INCLUDE_DIR_RE.finditer(text):
            dirs = _tokenize_cmake_args(match.group(1))
            for d in dirs:
                if d.upper() in {"PRIVATE", "PUBLIC", "INTERFACE"}:
                    continue
                dependency_dirs.append({"path": d, "file_path": rel})

    payload = {
        "version": 1,
        "op_name": op_name,
        "build_files": build_files,
        "targets": _dedupe_dicts(targets, key=lambda x: (x.get("name"), x.get("file_path"))),
        "source_selections": source_selections,
        "compile_options": compile_options,
        "compute_units": compute_units,
        "platform_predicates": platform_predicates,
        "dependency_dirs": _dedupe_dicts(dependency_dirs, key=lambda x: (x.get("path"), x.get("file_path"))),
        "determinants": determinants,
        "unresolved": unresolved,
        "csv_excluded_sources": ["BuildConfig", "CompileMacro", "PlatformInfo", "SourceSelection"],
    }
    write_yaml(uo_root / "ir" / "build_evidence.yaml", payload)
    write_yaml(uo_root / "ir" / "cmake_evidence.yaml", payload)  # alias per plan naming
    return payload


def _det(source: str, name: str, file_path: str, controllability: str, *, value: str = "") -> dict[str, Any]:
    return {
        "id": mint_edge_id("determinant", source, name, file_path),
        "source": source,
        "name": name,
        "value": value,
        "file_path": file_path,
        "controllability": controllability,
        "csv_controllable": False,
    }


def _collect_build_files(uo_root: Path, repo_root: Path) -> list[str]:
    run_id = active_run_id(uo_root)
    confirmed = read_yaml(uo_root / "runs" / run_id / "scope" / "scope_confirmed.yaml")
    explicit = confirmed.get("confirmed_build_files")
    if isinstance(explicit, list) and explicit:
        return [_as_rel(item) for item in explicit if _as_rel(item)]
    # Fallback: discover CMakeLists under confirmed sources' parents + repo.
    files: list[str] = []
    for item in confirmed.get("confirmed_file_list") or confirmed.get("confirmed_source_files") or []:
        rel = _as_rel(item)
        if not rel:
            continue
        parent = Path(rel).parent
        candidate = parent / "CMakeLists.txt"
        if (repo_root / candidate).is_file():
            files.append(candidate.as_posix())
    for path in list(repo_root.glob("CMakeLists.txt")) + list(repo_root.glob("**/CMakeLists.txt"))[:30]:
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if "test" in rel.lower() or "third_party" in rel.lower():
            continue
        files.append(rel)
    return sorted(set(files))


def _as_rel(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("path") or "").replace("\\", "/").strip()
    return str(item or "").replace("\\", "/").strip()


def _resolve_path(repo_root: Path, uo_root: Path, rel: str) -> Path | None:
    for base in (repo_root, uo_root.parent if uo_root.name == "uo" else repo_root):
        cand = base / rel
        if cand.is_file():
            return cand
    # workspace-relative via scan
    scan = {}
    run_id = active_run_id(uo_root)
    scan = read_yaml(uo_root / "runs" / run_id / "scope" / "scope_scan.yaml")
    root = scan.get("workspace_root")
    if root:
        cand = Path(str(root)) / rel
        if cand.is_file():
            return cand
    return None


def _tokenize_cmake_args(body: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.split(r"\s+", body.strip()):
        tok = raw.strip().strip('"').strip("'")
        if not tok or tok.startswith("#"):
            continue
        if tok.upper() in {"PRIVATE", "PUBLIC", "INTERFACE"}:
            continue
        tokens.append(tok)
    return tokens


def _dedupe_dicts(items: list[dict[str, Any]], *, key) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract CMake/build evidence (not for CBM indexing)")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    args = parser.parse_args(argv)
    payload = extract_build_evidence(Path(args.repo).resolve(), args.op_name)
    print(
        f"build_files={len(payload['build_files'])} "
        f"source_selections={len(payload['source_selections'])} "
        f"determinants={len(payload['determinants'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
