from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml

SOURCE_SUFFIXES = {".cpp", ".cc", ".c", ".h", ".hpp", ".py", ".cuh", ".cu"}
OPERATOR_PATH_MARKERS = ("op_host", "op_kernel", "op_api", "common", "tiling")


def detect_kb_changes(
    repo_root: Path,
    op_name: str,
    *,
    base: str | None = None,
    head: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    if not (uo_root / "manifest.yaml").exists():
        raise FileNotFoundError(f"KB missing at {uo_root}; run /uo-init first")

    manifest = read_yaml(uo_root / "manifest.yaml")
    base_revision = (base or str((manifest.get("source") or {}).get("revision") or "")).strip()
    if not base_revision or base_revision == "unknown":
        raise ValueError("manifest.source.revision is unknown; run /uo-init first")

    head_revision = (head or _git_revision(repo_root)).strip() or "unknown"
    if head_revision == "unknown":
        raise ValueError("cannot resolve git HEAD")

    scope_index = _load_scope_index(uo_root)
    name_status = _git_name_status(repo_root, base_revision, head_revision)

    files: list[dict[str, Any]] = []
    needs_phase0_review = False
    for status, path in name_status:
        norm = path.replace("\\", "/")
        if _is_kb_artifact_path(norm):
            continue
        role = scope_index.get(norm, "")
        in_scope = norm in scope_index
        suspicious = (not in_scope) and _looks_like_operator_source(norm)
        if suspicious:
            needs_phase0_review = True
        files.append(
            {
                "path": norm,
                "status": status,
                "in_scope": in_scope,
                "role": role or _infer_role(norm),
                "suspicious_out_of_scope": suspicious,
            }
        )

    payload = {
        "version": 1,
        "op_name": op_name,
        "base_revision": base_revision,
        "head_revision": head_revision,
        "needs_phase0_review": needs_phase0_review,
        "scoped_change_count": sum(1 for item in files if item["in_scope"]),
        "files": files,
    }
    if write:
        out = uo_root / "diff" / "change_set.yaml"
        write_yaml(out, payload)
        summary = uo_root / "summary"
        summary.mkdir(parents=True, exist_ok=True)
        write_yaml(summary / "change_set.yaml", payload)
    return payload


def _load_scope_index(uo_root: Path) -> dict[str, str]:
    run_id = str(read_yaml(uo_root / "manifest.yaml").get("current_run_id") or "")
    candidates = []
    if run_id:
        candidates.append(uo_root / "runs" / run_id / "phase0" / "receipt.yaml")
        candidates.append(uo_root / "runs" / run_id / "phase0" / "scope_confirmed.yaml")
    # Fall back to any latest receipt / confirmed under runs/
    for path in sorted((uo_root / "runs").glob("*/phase0/receipt.yaml"), reverse=True):
        candidates.append(path)
    for path in sorted((uo_root / "runs").glob("*/phase0/scope_confirmed.yaml"), reverse=True):
        candidates.append(path)

    for path in candidates:
        doc = read_yaml(path)
        if not doc:
            continue
        files = _extract_file_list(doc)
        if files:
            return files
    return {}


def _extract_file_list(doc: dict[str, Any]) -> dict[str, str]:
    raw: list[Any] = []
    frozen = doc.get("frozen_scope")
    if isinstance(frozen, dict):
        raw = frozen.get("confirmed_file_list") or frozen.get("files") or []
    if not raw:
        raw = doc.get("confirmed_file_list") or []
    out: dict[str, str] = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            out[item.replace("\\", "/")] = _infer_role(item)
            continue
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("file") or "").replace("\\", "/")
        if not path:
            continue
        role = str(item.get("role") or "").strip() or _infer_role(path)
        out[path] = role
    return out


def _git_name_status(repo_root: Path, base: str, head: str) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "diff", "--name-status", f"{base}..{head}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip() or result.stdout.strip()}")
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0].upper()
        # renames: R100\told\tnew → treat as new path
        path = parts[-1].replace("\\", "/")
        rows.append((status, path))
    return rows


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


def _is_kb_artifact_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.startswith(".understand-operator/") or "/.understand-operator/" in f"/{norm}"


def _looks_like_operator_source(path: str) -> bool:
    lower = path.lower()
    if Path(path).suffix.lower() not in SOURCE_SUFFIXES:
        return False
    return any(marker in lower for marker in OPERATOR_PATH_MARKERS)


def _infer_role(path: str) -> str:
    lower = path.replace("\\", "/").lower()
    if "template_tiling_key" in lower or lower.endswith("tiling_key.h"):
        return "tilingkey"
    if "/op_kernel/" in f"/{lower}" or lower.startswith("op_kernel/"):
        return "kernel"
    if "/op_host/" in f"/{lower}" or lower.startswith("op_host/"):
        return "host"
    if "tiling" in lower:
        return "tiling"
    if "/op_api/" in f"/{lower}" or lower.startswith("op_api/"):
        return "api"
    if "/common/" in f"/{lower}" or lower.startswith("common/"):
        return "common"
    if lower.endswith(".py") and ("cpu_impl" in lower or "golden" in lower):
        return "golden"
    if lower.endswith((".h", ".hpp")):
        return "headers"
    return "other"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect git changes vs KB source.revision")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--base", default=None)
    parser.add_argument("--head", default=None)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = detect_kb_changes(
        repo_root,
        op_name,
        base=args.base,
        head=args.head,
        write=not args.no_write,
    )
    print(
        f"change_set files={len(payload['files'])} scoped={payload['scoped_change_count']} "
        f"phase0_review={payload['needs_phase0_review']} {payload['base_revision'][:8]}..{payload['head_revision'][:8]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
