from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo._operator.run_context import active_run_id
from uo.scripts._ir_io import read_yaml


def stage_cbm_scope(repo_root: Path, op_name: str, *, stage_root: Path | None = None) -> dict[str, Any]:
    """Materialize confirmed_file_list into a small tree for MCP index_repository.

    KB always lives under the operator subdirectory. Confirmed paths may be
    workspace-relative (e.g. common/... and <op>/op_host/...) when a sibling
    common library was discovered; resolve those against workspace_root from
    scope_scan.yaml, then stage into UO_ROOT/cbm/index_stage for a single MCP index.
    """
    repo_root = repo_root.resolve()
    op_name = safe_op_name(op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    run_id = active_run_id(uo_root)
    confirmed = read_yaml(uo_root / "runs" / run_id / "scope" / "scope_confirmed.yaml")
    scan = read_yaml(uo_root / "runs" / run_id / "scope" / "scope_scan.yaml")
    # CBM indexes sources only — never confirmed_build_files / documentation.
    files = (
        confirmed.get("confirmed_source_files")
        or confirmed.get("confirmed_file_list")
        or []
    )
    rels: list[str] = []
    for item in files:
        if isinstance(item, dict):
            path = str(item.get("path") or "").replace("\\", "/").strip()
            # Skip any build files accidentally left in the source list.
            kind = str(item.get("kind") or item.get("file_kind") or "").lower()
            if kind in {"build", "cmake", "documentation", "doc"}:
                continue
        else:
            path = str(item or "").replace("\\", "/").strip()
        if not path:
            continue
        name = Path(path).name.lower()
        if name == "cmakelists.txt" or path.endswith(".cmake"):
            continue
        rels.append(path)
    if not rels:
        raise FileNotFoundError(f"no confirmed_file_list under runs/{run_id}/scope/scope_confirmed.yaml")

    # Hard gate: if scan discovered common/, staging must include at least one common/ path.
    scan_wants_common = bool(
        scan.get("common_rel")
        or scan.get("common_library")
        or any(
            "common library" in str(n) or "ascendc_common" in str(n)
            for n in (scan.get("warnings") or scan.get("notes") or [])
        )
        or any(
            str((item.get("path") if isinstance(item, dict) else item) or "").replace("\\", "/").startswith("common/")
            for group in ("initial_operator_files", "dependency_files")
            for item in ((scan.get("files") or {}).get(group) or [])
        )
    )
    if scan_wants_common and not any(r.startswith("common/") for r in rels):
        raise RuntimeError(
            "COMMON_SCOPE_REQUIRED: scope_scan discovered common/, but confirmed_file_list has no common/ paths. "
            "Fix scope confirmation before indexing."
        )

    workspace_root = _workspace_root(repo_root, scan)
    stage = (stage_root or (uo_root / "cbm" / "index_stage")).resolve()
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    linked = 0
    copied = 0
    missing: list[str] = []
    for rel in rels:
        src = _resolve_source(workspace_root, repo_root, rel)
        if src is None or not src.is_file():
            missing.append(rel)
            continue
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
            linked += 1
        except OSError:
            shutil.copy2(src, dst)
            copied += 1

    manifest = {
        "version": 1,
        "op_name": op_name,
        "run_id": run_id,
        "repo_root": str(repo_root),
        "workspace_root": str(workspace_root),
        "stage_root": str(stage),
        "file_count": linked + copied,
        "hardlinked": linked,
        "copied": copied,
        "missing_count": len(missing),
        "missing_sample": missing[:20],
        "mcp_index_hint": {
            "repo_path": str(stage),
            "mode": "fast",
            "name": f"{op_name}-scope",
        },
    }
    (uo_root / "cbm").mkdir(parents=True, exist_ok=True)
    (uo_root / "cbm" / "index_stage_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _workspace_root(repo_root: Path, scan: dict[str, Any]) -> Path:
    raw = scan.get("workspace_root") or scan.get("project_root")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).resolve()
    return repo_root.resolve()


def _resolve_source(workspace_root: Path, repo_root: Path, rel: str) -> Path | None:
    rel = rel.replace("\\", "/").lstrip("/")
    candidates = [
        workspace_root / rel,
        repo_root / rel,
    ]
    # When rel is workspace-relative like flash_attention_score_grad/op_host/...
    # but CLI repo is already that operator dir, also try stripping the first segment.
    parts = Path(rel).parts
    if len(parts) >= 2 and parts[0] == repo_root.name:
        candidates.append(repo_root / Path(*parts[1:]))
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage confirmed scope files for narrow CBM indexing")
    parser.add_argument("repo", nargs="?", default=".", help="Operator package root (KB location)")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--stage-root", default="", help="Optional override stage directory")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    stage_root = Path(args.stage_root).resolve() if args.stage_root else None
    try:
        manifest = stage_cbm_scope(repo_root, args.op_name, stage_root=stage_root)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"staged_files={manifest['file_count']} "
        f"hardlinked={manifest['hardlinked']} copied={manifest['copied']} "
        f"missing={manifest['missing_count']}"
    )
    print(f"workspace_root={manifest['workspace_root']}")
    print(f"MCP index_repository repo_path={manifest['stage_root']}")
    print(f"MCP name={manifest['mcp_index_hint']['name']} mode=fast")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
