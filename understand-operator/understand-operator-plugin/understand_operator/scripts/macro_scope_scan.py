from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._core.ignore import DEFAULT_IGNORE_PATTERNS, should_ignore
from understand_operator._operator.artifacts import existing_operator_root, safe_op_name, write_text
from understand_operator._operator.run_context import active_run_id, phase0_context, phase0_snapshot
from understand_operator._operator.spec import spec_bundle_hash
from understand_operator._operator.source_reader import SourceReader

ARCH_PATTERN = re.compile(r"arch22|arch35|regbase|ASCEND[0-9_]+", re.IGNORECASE)
ENTRY_PATTERN = re.compile(
    r"REGISTER_TILING|REGISTER_OP|TILING_KEY_IS|GET_TILING_DATA|__global__",
)
INCLUDE_PATTERN = re.compile(r"^\s*#\s*include\s*([<\"])([^>\"]+)[>\"]")
PY_IMPORT_PATTERN = re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)(?:\s+as\s+\w+)?")
PY_FROM_PATTERN = re.compile(r"^\s*from\s+([A-Za-z_.][\w.]*)\s+import\s+")
TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".md",
    ".txt",
    ".cmake",
    ".proto",
    ".ini",
    ".cfg",
    ".sh",
    ".ps1",
}
LARGE_FILE_BYTES = 512 * 1024
MAX_DEPENDENCY_DEPTH = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Phase 0.5-A macro scope scan.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--filesystem-tool", default="python", help="Recorded scan tool label")
    parser.add_argument("--seed", action="append", default=[], help="User-provided repo-relative seed file. May be repeated.")
    args = parser.parse_args(argv)

    operator_root = Path(args.repo).resolve()
    scan_root = _scan_root_for_operator(operator_root)
    op_name = safe_op_name(args.op_name, operator_root)
    base = existing_operator_root(operator_root, op_name)
    if not (base / "manifest.yaml").exists():
        print(f"KB not found: {base}", file=sys.stderr)
        print("Run prepare_operator.py before macro_scope_scan.py.", file=sys.stderr)
        return 2
    run_id = active_run_id(base)
    context = phase0_context(base, run_id)
    patterns = _load_ignore_patterns(scan_root)
    rel_files = _iter_files(scan_root, patterns)
    cbm_meta = _read_index_meta(base)
    operator_rel = operator_root.relative_to(scan_root).as_posix()
    if operator_rel == ".":
        operator_rel = ""
    include_result = _include_search_paths(scan_root, rel_files)
    include_paths = include_result["include_search_paths"]
    seeds_by_type = _seed_files(scan_root, rel_files, op_name, patterns, args.seed, operator_rel=operator_rel)
    seed_paths = sorted({item["path"] for values in seeds_by_type.values() for item in values})
    operator_roots = _operator_roots(seed_paths)
    dependency_result = _dependency_closure(scan_root, rel_files, seed_paths, operator_roots, include_paths)
    scope_roots = _scope_roots(operator_rel, seed_paths, dependency_result["dependency_files"], include_paths)

    payload = {
        "version": 1,
        "artifact": {"type": "runs.scope_scan", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": phase0_snapshot(base, run_id),
        "status": "complete",
        "op_name": op_name,
        "project_root": scan_root.as_posix(),
        "operator_path": operator_rel,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "scan_method": {
            "filesystem_tool": args.filesystem_tool,
            "cbm_project": cbm_meta.get("cbm_project") or "",
            "ignore_rules_applied": True,
            "max_dependency_depth": MAX_DEPENDENCY_DEPTH,
        },
        "directories": _directories(rel_files),
        "operator_roots": operator_roots,
        "scope_roots": scope_roots,
        "dependency_roots": [item for item in scope_roots if item["kind"] != "operator"],
        "include_search_paths": include_paths,
        "uncertain_include_paths": include_result["uncertain_include_paths"],
        "seed_files": seeds_by_type,
        "files": {
            "initial_operator_files": [_file_item(scan_root, rel, "initial_operator_file") for rel in seed_paths],
            "dependency_files": dependency_result["dependency_files"],
            "external_system_files": dependency_result["external_system_files"],
            "third_party_files": dependency_result["third_party_files"],
            "generated_files": [_file_item(scan_root, rel, "generated") for rel in rel_files if _classify(rel) == "generated"],
            "excluded_files": [],
            "uncertain_files": dependency_result["uncertain_files"],
        },
        "dependency_edges": dependency_result["dependency_edges"],
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
        "warnings": [],
    }

    scope_files = sorted(
        set(seed_paths)
        | {str(item.get("path")) for item in dependency_result["dependency_files"] if item.get("path")}
    )
    _scan_contents(scan_root, rel_files, payload, target="global_candidates")
    _scan_contents(scan_root, scope_files, payload, target="symbols")
    out_path = base / "runs" / run_id / "phase0" / "scope_scan.yaml"
    write_text(out_path, _to_yaml(payload))
    registry_path = base / "runs" / run_id / "phase0" / "source_encoding_registry.json"
    registry_path.write_text(json.dumps(_encoding_registry(scan_root, scope_files), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def _scan_root_for_operator(operator_root: Path) -> Path:
    parent = operator_root.parent
    if parent == operator_root:
        return operator_root
    sibling_markers = ("common", "CMakeLists.txt", "BUILD", "BUILD.bazel", "compile_commands.json")
    if any((parent / marker).exists() for marker in sibling_markers):
        return parent
    return operator_root


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _load_ignore_patterns(repo_root: Path) -> list[str]:
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        patterns.extend(_read_pattern_file(gitignore))
    uo_ignore = repo_root / ".understand-operator" / ".understandoperatorignore"
    if uo_ignore.exists():
        patterns.extend(_read_pattern_file(uo_ignore))
    return patterns


def _read_index_meta(base: Path) -> dict[str, Any]:
    path = base / "cbm" / "index_meta.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_pattern_file(path: Path) -> list[str]:
    result: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.append(stripped)
    return result


def _iter_files(repo_root: Path, patterns: list[str]) -> list[str]:
    result: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if should_ignore(rel, patterns):
            continue
        result.append(rel)
    return sorted(result)


def _directories(rel_files: list[str]) -> dict[str, list[str]]:
    dirs = sorted({str(Path(rel).parent).replace("\\", "/") for rel in rel_files if str(Path(rel).parent) != "."})
    excluded = [
        ".git",
        ".understand-operator",
        "build",
        "dist",
        "node_modules",
    ]
    return {"included": dirs, "excluded": excluded}


def _classify_files(rel_files: list[str]) -> dict[str, list[str]]:
    buckets = {
        "host": [],
        "kernel": [],
        "api": [],
        "proto": [],
        "golden": [],
        "tests": [],
        "examples": [],
        "generated": [],
        "docs_config": [],
        "unknown": [],
    }
    for rel in rel_files:
        bucket = _classify(rel)
        buckets[bucket].append(rel)
    return buckets


def _classify(rel: str) -> str:
    lower = rel.lower()
    parts = lower.split("/")
    suffix = Path(lower).suffix
    if any(part in {"build", "dist", "generated", "gen", "cmake-build-debug"} for part in parts):
        return "generated"
    if "op_host" in parts or "/host" in lower or lower.endswith("_tiling.cpp"):
        return "host"
    if "op_kernel" in parts or "/kernel" in lower:
        return "kernel"
    if "op_api" in parts or "/api" in lower:
        return "api"
    if suffix == ".proto" or "proto" in parts:
        return "proto"
    if "golden" in parts or "golden" in lower:
        return "golden"
    if any(part in {"test", "tests", "ut", "st"} for part in parts):
        return "tests"
    if any(part in {"example", "examples", "sample", "samples"} for part in parts):
        return "examples"
    if suffix in {".md", ".txt", ".yaml", ".yml", ".json", ".cmake"} or "cmakelists.txt" in lower:
        return "docs_config"
    return "unknown"


def _seed_files(repo_root: Path, rel_files: list[str], op_name: str, patterns: list[str], user_seeds: list[str], *, operator_rel: str) -> dict[str, list[dict[str, Any]]]:
    op_tokens = _name_tokens(op_name)
    seeds: dict[str, dict[str, dict[str, Any]]] = {
        "user_seeds": {},
        "operator_root_files": {},
        "name_matched_seeds": {},
        "registration_seeds": {},
        "api_proto_seeds": {},
        "golden_seeds": {},
    }
    rel_set = set(rel_files)
    for raw in user_seeds:
        rel = _validate_user_seed(repo_root, raw, rel_set, patterns)
        _add_seed(seeds["user_seeds"], rel, "user_seed", rel, rel, "user", "user-provided seed")
    for rel in rel_files:
        if operator_rel and not (rel == operator_rel or rel.startswith(operator_rel.rstrip("/") + "/")):
            continue
        lower = rel.lower()
        bucket = _classify(rel)
        if _is_operator_scope_file(rel, bucket):
            _add_seed(seeds["operator_root_files"], rel, "operator_root_file", operator_rel or ".", rel, "medium", "file is inside the operator root")
        if op_tokens and all(token in lower for token in op_tokens):
            _add_seed(seeds["name_matched_seeds"], rel, "name_match", "+".join(op_tokens), rel, "high", "file or directory name matches operator token(s)")
        path = repo_root / rel
        if path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size < LARGE_FILE_BYTES:
            text = "\n".join(_read_lines(repo_root, path))
            lowered_text = text.lower()
            entry = ENTRY_PATTERN.search(text)
            if entry and any(token and token in lowered_text for token in op_tokens):
                bucket_name = "api_proto_seeds" if bucket in {"api", "proto"} else "registration_seeds"
                _add_seed(seeds[bucket_name], rel, bucket_name[:-1], entry.group(0), rel, "high", "entry macro and operator token both match")
            elif bucket == "golden" and any(token and token in lower for token in op_tokens):
                _add_seed(seeds["golden_seeds"], rel, "golden_name", "+".join(op_tokens), rel, "medium", "golden/reference name matches operator")
    return {key: sorted(value.values(), key=lambda item: item["path"]) for key, value in seeds.items()}


def _is_operator_scope_file(rel: str, bucket: str) -> bool:
    suffix = Path(rel).suffix.lower()
    if suffix not in TEXT_EXTENSIONS:
        return False
    if bucket in {"tests", "examples", "generated", "docs_config"}:
        return False
    return bucket in {"host", "kernel", "api", "proto", "golden", "unknown"} or suffix == ".py"


def _validate_user_seed(repo_root: Path, raw: str, rel_set: set[str], patterns: list[str]) -> str:
    path = (repo_root / raw).resolve()
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise SystemExit(f"--seed must be inside repository: {raw}") from exc
    if rel not in rel_set or not path.is_file():
        raise SystemExit(f"--seed does not exist or is ignored: {raw}")
    if should_ignore(rel, patterns):
        raise SystemExit(f"--seed points to ignored path: {raw}")
    return rel


def _add_seed(bucket: dict[str, dict[str, Any]], path: str, seed_type: str, matched_token: str, source_location: str, confidence: str, reason: str) -> None:
    bucket.setdefault(
        path,
        {
            "path": path,
            "seed_type": seed_type,
            "matched_token": matched_token,
            "source_location": source_location,
            "confidence": confidence,
            "reason": reason,
        },
    )


def _name_tokens(op_name: str) -> list[str]:
    return [token.lower() for token in re.split(r"[^A-Za-z0-9]+", op_name) if token]


def _dependency_closure(repo_root: Path, rel_files: list[str], seeds: list[str], operator_roots: list[str], include_paths: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    rel_set = set(rel_files)
    by_name = _index_repo_modules(rel_files)
    dependency_files: dict[str, dict[str, Any]] = {}
    external_system: dict[str, dict[str, Any]] = {}
    third_party: dict[str, dict[str, Any]] = {}
    uncertain: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    queue: list[tuple[str, int, list[str]]] = [(seed, 0, [seed]) for seed in seeds]
    visited: set[tuple[str, int]] = set()
    while queue:
        rel, depth, chain = queue.pop(0)
        if (rel, depth) in visited or depth >= MAX_DEPENDENCY_DEPTH:
            continue
        visited.add((rel, depth))
        for dep in _dependencies_for(repo_root, rel, rel_set, by_name, operator_roots, include_paths):
            target = dep["target_file"]
            edge = {
                "source_file": rel,
                "target_file": target,
                "dependency_type": dep["dependency_type"],
                "source_location": dep["source_location"],
                "resolution_status": dep["resolution_status"],
                "reason": dep["reason"],
            }
            edges.append(edge)
            if dep["resolution_status"] in {"resolved", "resolved_repository"} and target in rel_set:
                next_chain = chain + [target]
                if depth + 1 >= MAX_DEPENDENCY_DEPTH:
                    uncertain[target] = {
                        "path": target,
                        "reason": "dependency depth limit reached",
                        "discovery_chain": next_chain,
                    }
                    continue
                dependency_files.setdefault(
                    target,
                    {
                        "path": target,
                        "role": _classify(target),
                        "discovered_from": rel,
                        "discovery_chain": next_chain,
                        "dependency_type": dep["dependency_type"],
                        "included_because": dep["reason"],
                        "outside_operator_directory": not _inside_operator_roots(target, operator_roots),
                    },
                )
                queue.append((target, depth + 1, next_chain))
            elif dep["resolution_status"] == "external_system":
                external_system[target] = {"path": target, "dependency_type": dep["dependency_type"], "discovered_from": rel}
            elif dep["resolution_status"] == "third_party":
                third_party[target] = {"path": target, "dependency_type": dep["dependency_type"], "discovered_from": rel}
            else:
                uncertain[target] = {"path": target, "reason": dep["reason"], "discovered_from": rel}
    return {
        "dependency_files": sorted(dependency_files.values(), key=lambda item: item["path"]),
        "external_system_files": sorted(external_system.values(), key=lambda item: item["path"]),
        "third_party_files": sorted(third_party.values(), key=lambda item: item["path"]),
        "uncertain_files": sorted(uncertain.values(), key=lambda item: item["path"]),
        "dependency_edges": sorted(edges, key=lambda item: (item["source_file"], item["target_file"], item["source_location"])),
    }


def _index_repo_modules(rel_files: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for rel in rel_files:
        path = Path(rel)
        if path.suffix == ".py":
            parts = list(path.with_suffix("").parts)
            result[".".join(parts)] = rel
            if path.name == "__init__.py":
                result[".".join(parts[:-1])] = rel
    return result


def _dependencies_for(repo_root: Path, rel: str, rel_set: set[str], by_name: dict[str, str], operator_roots: list[str], include_paths: list[dict[str, str]]) -> list[dict[str, Any]]:
    path = repo_root / rel
    if path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size >= LARGE_FILE_BYTES:
        return []
    try:
        lines = _read_lines(repo_root, path)
    except OSError:
        return []
    deps: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        include = INCLUDE_PATTERN.search(line)
        if include:
            delimiter, target = include.groups()
            resolved = _resolve_include(repo_root, rel, target, rel_set, operator_roots, include_paths)
            deps.append({**resolved, "source_location": f"{rel}:{lineno}", "dependency_type": "include"})
            continue
        py_import = PY_IMPORT_PATTERN.search(line) or PY_FROM_PATTERN.search(line)
        if py_import:
            module = py_import.group(1).lstrip(".")
            resolved = _resolve_python_import(module, by_name)
            deps.append({**resolved, "source_location": f"{rel}:{lineno}", "dependency_type": "python_import"})
    return deps


def _resolve_include(repo_root: Path, source_rel: str, target: str, rel_set: set[str], operator_roots: list[str], include_paths: list[dict[str, str]]) -> dict[str, Any]:
    candidates = [
        (repo_root / source_rel).parent / target,
    ]
    candidates.extend(repo_root / root / target for root in operator_roots)
    candidates.extend(repo_root / item["path"] / target for item in include_paths if item.get("path"))
    candidates.append(repo_root / target)
    parts = Path(target).parts
    if parts:
        for index in range(len(parts)):
            suffix = Path(*parts[index:])
            candidates.append(repo_root / suffix)
    for candidate in candidates:
        try:
            rel = candidate.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if rel in rel_set:
            return {"target_file": rel, "resolution_status": "resolved_repository", "reason": f'include "{target}" resolved by deterministic search order'}
    basename_matches = sorted(rel for rel in rel_set if Path(rel).name == Path(target).name)
    if len(basename_matches) == 1:
        return {"target_file": basename_matches[0], "resolution_status": "resolved_repository", "reason": f'include "{target}" resolved by unique repository filename'}
    if len(basename_matches) > 1:
        return {"target_file": target, "resolution_status": "ambiguous", "reason": "multiple repository include candidates: " + ", ".join(basename_matches[:8])}
    if "/" not in target and "\\" not in target:
        return {"target_file": target, "resolution_status": "external_system", "reason": "include could not be resolved in repository; treat as system or toolchain header"}
    return {"target_file": target, "resolution_status": "external_system", "reason": "include outside repository search roots"}


def _scope_roots(operator_rel: str, seed_paths: list[str], dependency_files: list[dict[str, Any]], include_paths: list[dict[str, str]]) -> list[dict[str, str]]:
    roots: dict[str, dict[str, str]] = {}
    op_root = operator_rel.strip("/")
    if op_root:
        roots[op_root] = {"path": op_root, "kind": "operator", "reason": "input operator path"}
    else:
        roots["."] = {"path": ".", "kind": "operator", "reason": "input operator path"}
    for item in dependency_files:
        path = str(item.get("path") or "")
        if not path:
            continue
        root = _dependency_root(path, op_root)
        if root and root != op_root:
            roots.setdefault(root, {"path": root, "kind": "dependency", "reason": "dependency closure"})
    for item in include_paths:
        path = str(item.get("path") or "")
        if path and path != op_root:
            roots.setdefault(path, {"path": path, "kind": "include_root", "reason": "build include path"})
    return sorted(roots.values(), key=lambda item: (item["kind"], item["path"]))


def _dependency_root(path: str, operator_rel: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "common" and parts[1] == "op_kernel":
        return "/".join(parts[:3])
    if parts:
        return parts[0]
    return operator_rel


def _resolve_python_import(module: str, by_name: dict[str, str]) -> dict[str, Any]:
    if module in by_name:
        return {"target_file": by_name[module], "resolution_status": "resolved", "reason": f"python import {module}"}
    root = module.split(".", 1)[0]
    for key, rel in by_name.items():
        if key == root:
            return {"target_file": rel, "resolution_status": "resolved", "reason": f"python import {module}"}
    return {"target_file": module, "resolution_status": "third_party", "reason": "python import not resolved to repo module"}


def _operator_roots(seed_paths: list[str]) -> list[str]:
    roots: set[str] = set()
    for rel in seed_paths:
        parts = rel.split("/")
        for marker in ("op_host", "op_kernel", "op_api"):
            if marker in parts:
                idx = parts.index(marker)
                if len(parts) > idx + 1:
                    roots.add("/".join(parts[: idx + 2]))
    return sorted(roots)


def _inside_operator_roots(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def _include_search_paths(repo_root: Path, rel_files: list[str]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, dict[str, str]] = {}
    uncertain: list[dict[str, str]] = []
    pattern = re.compile(r"(?:include_directories|target_include_directories)\s*\(([^)]*)\)|(?:^|\s)-I\s*([^\s)]+)")
    set_pattern = re.compile(r"^\s*set\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s+([^)]*?)\s*\)")
    for rel in rel_files:
        lower = rel.lower()
        if not (lower.endswith("cmakelists.txt") or lower.endswith(".cmake") or lower.endswith("build") or lower.endswith("build.bazel") or lower.endswith(".bzl")):
            continue
        path = repo_root / rel
        if path.stat().st_size >= LARGE_FILE_BYTES:
            continue
        lines = _read_lines(repo_root, path)
        variables: dict[str, str] = {
            "CMAKE_CURRENT_SOURCE_DIR": path.parent.as_posix(),
            "CMAKE_CURRENT_LIST_DIR": path.parent.as_posix(),
            "PROJECT_SOURCE_DIR": repo_root.as_posix(),
            "CMAKE_SOURCE_DIR": repo_root.as_posix(),
        }
        for line in lines:
            match = set_pattern.match(line)
            if match:
                raw_value = match.group(2).strip().strip('"').strip("'")
                if raw_value and not any(token in raw_value for token in ("$", "<", ">", ";")):
                    variables[match.group(1)] = raw_value
        for lineno, line in enumerate(lines, start=1):
            for match in pattern.finditer(line):
                raw = match.group(1) or match.group(2) or ""
                for token in re.split(r"\s+", raw):
                    token = token.strip().strip('"').strip("'")
                    if not token or token in {"PRIVATE", "PUBLIC", "INTERFACE", "SYSTEM"}:
                        continue
                    expanded = _expand_cmake_token(token, variables)
                    if expanded is None:
                        uncertain.append({"path": token, "source_file": rel, "source_location": f"{rel}:{lineno}", "reason": "dynamic or generator CMake include path"})
                        continue
                    token = expanded
                    candidate = (path.parent / token).resolve() if not Path(token).is_absolute() else Path(token)
                    try:
                        inc_rel = candidate.relative_to(repo_root).as_posix()
                    except ValueError:
                        continue
                    result.setdefault(
                        inc_rel,
                        {
                            "path": inc_rel,
                            "source_file": rel,
                            "source_location": f"{rel}:{lineno}",
                            "source_kind": "cmake_target_include_directories",
                        },
                    )
    return {"include_search_paths": sorted(result.values(), key=lambda item: item["path"]), "uncertain_include_paths": sorted(uncertain, key=lambda item: (item["source_file"], item["path"]))}


def _expand_cmake_token(token: str, variables: dict[str, str]) -> str | None:
    if "$<" in token or ">" in token:
        return None

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return variables.get(name, "")

    expanded = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, token)
    if "$" in expanded or not expanded:
        return None
    return expanded


def _file_item(repo_root: Path, rel: str, role: str) -> dict[str, Any]:
    path = repo_root / rel
    try:
        digest = "sha256:" + __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    except OSError:
        digest = ""
    return {"path": rel, "role": role, "file_hash": digest, "include_reason": "phase0 seed"}


def _read_lines(repo_root: Path, path: Path) -> list[str]:
    return list(SourceReader(repo_root).read(path.relative_to(repo_root)).lines)


def _encoding_registry(repo_root: Path, rel_files: list[str]) -> dict[str, Any]:
    reader = SourceReader(repo_root); entries: list[dict[str, Any]] = []
    for rel in sorted(set(rel_files)):
        try:
            entries.append(reader.registry_entry(rel))
        except Exception as exc:  # record a deterministic failed decode instead of corrupting facts
            entries.append({"path": rel, "decode_status": "failed", "error": str(exc)})
    return {"version": 1, "files": entries}


def _scan_contents(repo_root: Path, rel_files: list[str], payload: dict[str, Any], *, target: str) -> None:
    arch_hits: dict[str, dict[str, Any]] = {}
    for rel in rel_files:
        path = repo_root / rel
        try:
            size = path.stat().st_size
        except OSError as exc:
            payload["warnings"].append(f"stat failed for {rel}: {exc}")
            continue
        if size >= LARGE_FILE_BYTES:
            payload["large_files"].append(
                {"path": rel, "size_bytes": size, "read_policy": "line_scoped_only"}
            )
        if path.suffix.lower() not in TEXT_EXTENSIONS or size >= LARGE_FILE_BYTES:
            continue
        try:
            lines = _read_lines(repo_root, path)
        except OSError as exc:
            payload["warnings"].append(f"read failed for {rel}: {exc}")
            continue
        for lineno, line in enumerate(lines, start=1):
            for match in ARCH_PATTERN.finditer(line):
                name = match.group(0).lower()
                item = arch_hits.setdefault(
                    name,
                    {
                        "name": name,
                        "matched_paths": [],
                        "matched_lines": [],
                        "semantic_status": "candidate",
                        "cbm_evidence": [],
                    },
                )
                if rel not in item["matched_paths"]:
                    item["matched_paths"].append(rel)
                item["matched_lines"].append({"file": rel, "line": lineno, "text": line.strip()[:240]})
            entry_match = ENTRY_PATTERN.search(line)
            if entry_match:
                kind = _entry_kind(entry_match.group(0))
                bucket = _symbol_bucket(kind)
                item = {
                    "item": entry_match.group(0),
                    "kind": kind,
                    "file": rel,
                    "line": lineno,
                    "discovery_method": "python_regex",
                    "cbm_status": "pending",
                    "cbm_symbol": "",
                    "evidence": [],
                }
                if target == "global_candidates" and bucket in payload["global_candidates"]:
                    payload["global_candidates"][bucket].append(item)
                elif target == "symbols":
                    payload["symbols"][bucket].append(item)
    for item in arch_hits.values():
        item["matched_paths"].sort()
        item["matched_lines"] = sorted(item["matched_lines"], key=lambda hit: (hit["file"], hit["line"]))
    if target == "symbols":
        payload["architecture_variants"] = [arch_hits[key] for key in sorted(arch_hits)]
        for bucket, values in payload["symbols"].items():
            payload["symbols"][bucket] = sorted(_unique_dicts(values), key=lambda item: (item["file"], item["line"], item["item"]))
        payload["large_files"] = sorted(_unique_dicts(payload["large_files"]), key=lambda item: item["path"])
        payload["warnings"] = sorted(set(payload["warnings"]))
    else:
        for bucket, values in payload["global_candidates"].items():
            payload["global_candidates"][bucket] = sorted(_unique_dicts(values), key=lambda item: (item["file"], item["line"], item["item"]))


def _unique_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _entry_kind(item: str) -> str:
    if "TILING" in item:
        return "tiling_registration" if item == "REGISTER_TILING" else "macro"
    if item == "REGISTER_OP":
        return "operator_registration"
    if item == "__global__":
        return "kernel_entry"
    return "unknown"


def _symbol_bucket(kind: str) -> str:
    if kind == "operator_registration":
        return "registration_candidates"
    if kind == "kernel_entry":
        return "kernel_entry_candidates"
    if kind in {"tiling_registration", "macro"}:
        return "host_entry_candidates"
    return "api_candidates"


def _to_yaml(data: Any, indent: int = 0) -> str:
    lines = _yaml_lines(data, indent)
    return "\n".join(lines) + "\n"


def _yaml_lines(data: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                if value:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(_yaml_lines(value, indent + 2))
                else:
                    lines.append(f"{prefix}{key}: []" if isinstance(value, list) else f"{prefix}{key}: {{}}")
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
        return lines
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, dict):
                item_lines = _yaml_lines(item, indent + 2)
                lines.append(f"{prefix}- {item_lines[0].lstrip()}")
                lines.extend(item_lines[1:])
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines or [f"{prefix}[]"]
    return [f"{prefix}{_yaml_scalar(data)}"]


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#[]{}&,*?|-<>=!%@`\"'\\\n") or text.strip() != text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


if __name__ == "__main__":
    raise SystemExit(main())
