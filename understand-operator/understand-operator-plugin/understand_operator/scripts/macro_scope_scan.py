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
from understand_operator._operator.artifacts import operator_root, safe_op_name, write_text

ARCH_PATTERN = re.compile(r"arch22|arch35|regbase|ASCEND[0-9_]+", re.IGNORECASE)
ENTRY_PATTERN = re.compile(
    r"REGISTER_TILING|REGISTER_OP|TILING_KEY_IS|GET_TILING_DATA|__global__",
)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Phase 0.5-A macro scope scan.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--filesystem-tool", default="python", help="Recorded scan tool label")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name)
    patterns = _load_ignore_patterns(repo_root)
    rel_files = _iter_files(repo_root, patterns)
    cbm_meta = _read_index_meta(base)

    payload = {
        "version": 1,
        "op_name": op_name,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "scan_method": {
            "filesystem_tool": args.filesystem_tool,
            "cbm_project": cbm_meta.get("cbm_project") or "",
            "ignore_rules_applied": True,
        },
        "directories": _directories(rel_files),
        "files": _classify_files(rel_files),
        "architecture_variants": [],
        "entry_candidates": [],
        "large_files": [],
        "uncertain_items": [],
        "warnings": [],
    }

    _scan_contents(repo_root, rel_files, payload)
    write_text(base / "archive" / "runs" / "macro_scope_scan.yaml", _to_yaml(payload))
    print(f"Wrote {base / 'archive' / 'runs' / 'macro_scope_scan.yaml'}")
    return 0


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
                payload["entry_candidates"].append(
                    {
                        "item": entry_match.group(0),
                        "kind": _entry_kind(entry_match.group(0)),
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
    payload["entry_candidates"] = sorted(
        payload["entry_candidates"], key=lambda item: (item["file"], item["line"], item["item"])
    )
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
