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
from understand_operator._operator.spec import spec_bundle_hash

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
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = existing_operator_root(repo_root, op_name)
    if not (base / "manifest.yaml").exists():
        print(f"KB not found: {base}", file=sys.stderr)
        print("Run prepare_operator.py before macro_scope_scan.py.", file=sys.stderr)
        return 2
    run_id = _current_run_id(base)
    context = _phase0_context(base, run_id)
    patterns = _load_ignore_patterns(repo_root)
    rel_files = _iter_files(repo_root, patterns)
    cbm_meta = _read_index_meta(base)
    seeds = _seed_files(repo_root, rel_files, op_name)
    dependency_result = _dependency_closure(repo_root, rel_files, seeds)

    payload = {
        "version": 1,
        "artifact": {"type": "runs.scope_scan", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": {
            "run_id": run_id,
            "source_snapshot_id": context.get("source_snapshot_id") or "SOURCE_PHASE0",
            "source_revision": context.get("source_revision") or "unknown",
            "spec_bundle_hash": spec_bundle_hash(),
        },
        "status": "complete",
        "op_name": op_name,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "scan_method": {
            "filesystem_tool": args.filesystem_tool,
            "cbm_project": cbm_meta.get("cbm_project") or "",
            "ignore_rules_applied": True,
            "max_dependency_depth": MAX_DEPENDENCY_DEPTH,
        },
        "directories": _directories(rel_files),
        "seed_files": seeds,
        "files": {
            "initial_operator_files": [_file_item(repo_root, rel, "initial_operator_file") for rel in seeds],
            "dependency_files": dependency_result["dependency_files"],
            "external_system_files": dependency_result["external_system_files"],
            "third_party_files": dependency_result["third_party_files"],
            "generated_files": [_file_item(repo_root, rel, "generated") for rel in rel_files if _classify(rel) == "generated"],
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
        "architecture_variants": [],
        "large_files": [],
        "warnings": [],
        "items": [],
        "relations": [],
        "unresolved": [],
    }

    _scan_contents(repo_root, rel_files, payload)
    out_path = base / "runs" / run_id / "phase0" / "scope_scan.yaml"
    write_text(out_path, _to_yaml(payload))
    print(f"Wrote {out_path}")
    return 0


def _current_run_id(base: Path) -> str:
    manifest = _load_yaml(base / "manifest.yaml")
    run_id = manifest.get("current_run_id") if isinstance(manifest, dict) else None
    if not isinstance(run_id, str) or not run_id.startswith("UO_RUN_") or run_id == "UO_RUN_PENDING":
        raise SystemExit(f"manifest.yaml.current_run_id is not active in {base}")
    return run_id


def _phase0_context(base: Path, run_id: str) -> dict[str, Any]:
    data = _load_yaml(base / "runs" / run_id / "phase0" / "context.yaml")
    if isinstance(data, dict):
        for item in data.get("items") or []:
            if isinstance(item, dict) and isinstance(item.get("data"), dict):
                return item["data"]
    manifest = _load_yaml(base / "manifest.yaml")
    source = manifest.get("source") if isinstance(manifest, dict) and isinstance(manifest.get("source"), dict) else {}
    return {
        "source_revision": source.get("revision") or "unknown",
        "source_snapshot_id": source.get("snapshot_id") or "SOURCE_PHASE0",
    }


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
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
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


def _seed_files(repo_root: Path, rel_files: list[str], op_name: str) -> list[str]:
    op_tokens = _name_tokens(op_name)
    seeds: set[str] = set()
    for rel in rel_files:
        lower = rel.lower()
        bucket = _classify(rel)
        if bucket in {"host", "kernel", "api", "proto", "golden"}:
            seeds.add(rel)
            continue
        if op_tokens and all(token in lower for token in op_tokens):
            seeds.add(rel)
            continue
        path = repo_root / rel
        if path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size < LARGE_FILE_BYTES:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if ENTRY_PATTERN.search(text) or any(token and token in text.lower() for token in op_tokens):
                seeds.add(rel)
    return sorted(seeds)


def _name_tokens(op_name: str) -> list[str]:
    return [token.lower() for token in re.split(r"[^A-Za-z0-9]+", op_name) if token]


def _dependency_closure(repo_root: Path, rel_files: list[str], seeds: list[str]) -> dict[str, list[dict[str, Any]]]:
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
        for dep in _dependencies_for(repo_root, rel, rel_set, by_name):
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
            if dep["resolution_status"] == "resolved" and target in rel_set:
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
                        "outside_operator_directory": not _same_top_directory(chain[0], target),
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


def _dependencies_for(repo_root: Path, rel: str, rel_set: set[str], by_name: dict[str, str]) -> list[dict[str, Any]]:
    path = repo_root / rel
    if path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size >= LARGE_FILE_BYTES:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    deps: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        include = INCLUDE_PATTERN.search(line)
        if include:
            delimiter, target = include.groups()
            resolved = _resolve_include(repo_root, rel, target, delimiter == "<", rel_set)
            deps.append({**resolved, "source_location": f"{rel}:{lineno}", "dependency_type": "include"})
            continue
        py_import = PY_IMPORT_PATTERN.search(line) or PY_FROM_PATTERN.search(line)
        if py_import:
            module = py_import.group(1).lstrip(".")
            resolved = _resolve_python_import(module, by_name)
            deps.append({**resolved, "source_location": f"{rel}:{lineno}", "dependency_type": "python_import"})
    return deps


def _resolve_include(repo_root: Path, source_rel: str, target: str, angle: bool, rel_set: set[str]) -> dict[str, Any]:
    if angle:
        return {
            "target_file": target,
            "resolution_status": "external_system",
            "reason": "system angle include recorded but not added to source-read scope",
        }
    candidates = [
        (repo_root / source_rel).parent / target,
        repo_root / target,
    ]
    for candidate in candidates:
        try:
            rel = candidate.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if rel in rel_set:
            return {"target_file": rel, "resolution_status": "resolved", "reason": f'quoted include "{target}"'}
    return {"target_file": target, "resolution_status": "unresolved", "reason": "quoted include could not be resolved in repository"}


def _resolve_python_import(module: str, by_name: dict[str, str]) -> dict[str, Any]:
    if module in by_name:
        return {"target_file": by_name[module], "resolution_status": "resolved", "reason": f"python import {module}"}
    root = module.split(".", 1)[0]
    for key, rel in by_name.items():
        if key == root:
            return {"target_file": rel, "resolution_status": "resolved", "reason": f"python import {module}"}
    return {"target_file": module, "resolution_status": "third_party", "reason": "python import not resolved to repo module"}


def _same_top_directory(a: str, b: str) -> bool:
    return a.split("/", 1)[0] == b.split("/", 1)[0]


def _file_item(repo_root: Path, rel: str, role: str) -> dict[str, Any]:
    path = repo_root / rel
    try:
        digest = "sha256:" + __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    except OSError:
        digest = ""
    return {"path": rel, "role": role, "file_hash": digest, "include_reason": "phase0 seed"}


def _scan_contents(repo_root: Path, rel_files: list[str], payload: dict[str, Any]) -> None:
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
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
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
                payload["symbols"][bucket].append(
                    {
                        "item": entry_match.group(0),
                        "kind": kind,
                        "file": rel,
                        "line": lineno,
                        "discovery_method": "python_regex",
                        "cbm_status": "pending",
                        "cbm_symbol": "",
                        "evidence": [],
                    }
                )
    for item in arch_hits.values():
        item["matched_paths"].sort()
        item["matched_lines"] = sorted(item["matched_lines"], key=lambda hit: (hit["file"], hit["line"]))
    payload["architecture_variants"] = [arch_hits[key] for key in sorted(arch_hits)]
    for bucket, values in payload["symbols"].items():
        payload["symbols"][bucket] = sorted(values, key=lambda item: (item["file"], item["line"], item["item"]))
    payload["large_files"] = sorted(payload["large_files"], key=lambda item: item["path"])
    payload["warnings"] = sorted(set(payload["warnings"]))


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
