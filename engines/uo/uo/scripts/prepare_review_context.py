"""Prepare dual-graph review context pack (diff + kb_graph + CBM)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.cbm_impact import cbm_status, impact_from_files
from uo.scripts.export_kb_graph import export_kb_graph
from uo.scripts.kb_graph_query import index_status, query_kb_graph


def prepare_review_context(
    repo_root: Path,
    op_name: str,
    *,
    base: str | None = None,
    mode: str = "both",
    requirements: str | None = None,
    ensure_graphs: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    mode = (mode or "both").strip().lower()
    if mode not in {"both", "functional", "bug"}:
        raise ValueError("mode must be both|functional|bug")

    errors: list[str] = []
    kb_status = index_status(uo_root)
    if ensure_graphs and kb_status.get("index_status") != "fresh":
        try:
            export_kb_graph(repo_root, op_name, write=True)
            kb_status = index_status(uo_root)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"kb_graph export failed: {exc}")

    kb_status = index_status(uo_root)
    if kb_status.get("index_status") != "fresh":
        errors.append(f"kb_graph not fresh: {kb_status}")

    cbm = cbm_status(uo_root)
    if not cbm.get("available"):
        errors.append(
            f"CBM unavailable: {cbm.get('hint') or 'missing index'}; "
            "run /uo-init scope confirmation (MCP index_repository) — do not install code-review-graph"
        )

    diff_index = read_yaml(uo_root / "diff" / "index.yaml")
    change_set = read_yaml(uo_root / "diff" / "change_set.yaml")
    impact = read_yaml(uo_root / "diff" / "impact.yaml")

    changed_files = _changed_files(change_set, diff_index)
    base_rev = base or str(diff_index.get("base_revision") or change_set.get("base_revision") or "HEAD~1")
    head_rev = str(diff_index.get("head_revision") or change_set.get("head_revision") or "HEAD")

    kb_entities = query_kb_graph(
        uo_root,
        pattern="entities_in_files",
        target=",".join(changed_files) if changed_files else "",
        depth=1,
        limit=80,
    )
    kb_shapes = query_kb_graph(
        uo_root,
        pattern="affected_shapes",
        target=",".join(changed_files) if changed_files else "",
        depth=2,
        limit=80,
    )

    cbm_impact = impact_from_files(uo_root, changed_files) if cbm.get("available") else {
        "status": "missing",
        "error": "CBM unavailable",
        "changed_symbols": [],
        "callers": [],
        "impacted_files": [],
        "priority": [],
    }
    if cbm_impact.get("status") != "ok" and cbm.get("available"):
        errors.append(f"CBM impact failed: {cbm_impact.get('error') or cbm_impact}")

    req_meta = _requirements_meta(requirements)

    pack = {
        "version": 1,
        "kind": "review_context_pack",
        "op_name": op_name,
        "mode": mode,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "base_revision": base_rev,
        "head_revision": head_rev,
        "changed_files": changed_files,
        "diff": {
            "index": _slim(diff_index),
            "impact": _slim(impact),
            "change_set_file_count": len(change_set.get("files") or []) if isinstance(change_set, dict) else 0,
        },
        "kb_graph": {
            "status": kb_status,
            "entities_in_files": _slim_query(kb_entities),
            "affected_shapes": _slim_query(kb_shapes),
            "primary_for": ["functional", "semantic_completeness"],
            "supplement_for": ["bug"],
        },
        "cbm": {
            "status": cbm,
            "impact": _slim(cbm_impact),
            "primary_for": ["bug"],
            "supplement_for": ["functional", "semantic_completeness"],
            "agent_tools": [
                "codebase-memory-mcp.trace_path",
                "codebase-memory-mcp.search_graph",
                "codebase-memory-mcp.get_code_snippet",
                "codebase-memory-mcp.get_architecture",
            ],
        },
        "source_graph": {
            "backend": "cbm",
            "note": "Bug primary graph is CBM (scope confirmation index); code-review-graph is not required",
        },
        "requirements": req_meta,
        "graph_roles": {
            "bug": {"primary": "cbm", "supplement": "kb_graph"},
            "functional": {"primary": "kb_graph", "supplement": "cbm"},
        },
        "ready": len(errors) == 0,
        "errors": errors,
    }

    if write:
        run_id = "UO_REVIEW_" + datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S%f")
        run_dir = uo_root / "runs" / run_id / "review"
        run_dir.mkdir(parents=True, exist_ok=True)
        write_yaml(run_dir / "context_pack.yaml", pack)
        (run_dir / "context_pack.json").write_text(
            json.dumps(pack, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        pack["run_id"] = run_id
        pack["context_pack_path"] = str(run_dir / "context_pack.yaml")

    return pack


def _changed_files(change_set: dict[str, Any], diff_index: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for item in change_set.get("files") or []:
        if isinstance(item, dict):
            path = item.get("path") or item.get("file") or item.get("file_path")
            if path:
                files.append(str(path).replace("\\", "/"))
        elif isinstance(item, str):
            files.append(item.replace("\\", "/"))
    if not files and isinstance(diff_index.get("changed_files"), list):
        files = [str(p).replace("\\", "/") for p in diff_index["changed_files"]]
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _requirements_meta(requirements: str | None) -> dict[str, Any]:
    if not requirements:
        return {
            "input_type": "kb_semantic_completeness",
            "note": "未提供外部需求文档；功能路基于 KB 义务/变更实体做语义完整性检查",
            "path": None,
        }
    path = Path(requirements)
    if path.exists():
        return {"input_type": "external_requirements", "path": str(path.resolve()), "note": ""}
    return {"input_type": "external_requirements", "path": None, "inline_or_url": requirements, "note": ""}


def _slim(obj: Any, *, max_chars: int = 12000) -> Any:
    try:
        text = json.dumps(obj, ensure_ascii=False)
    except TypeError:
        return {"_repr": str(obj)[:2000]}
    if len(text) <= max_chars:
        return obj
    if isinstance(obj, dict):
        return {k: obj[k] for k in list(obj)[:20]} | {"_truncated": True, "_original_chars": len(text)}
    return {"_truncated": True, "_preview": text[:max_chars]}


def _slim_query(result: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "pattern",
        "index_status",
        "resolved_entities",
        "direct_relations",
        "neighbors",
        "affected_shapes",
        "files",
        "error",
    )
    out = {k: result.get(k) for k in keep_keys if k in result}
    for key in ("resolved_entities", "neighbors", "affected_shapes", "direct_relations"):
        items = out.get(key)
        if isinstance(items, list) and len(items) > 40:
            out[key] = items[:40]
            out[f"{key}_truncated"] = True
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare dual-graph code-review context pack (kb_graph + CBM)")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--mode", default="both", choices=["both", "functional", "bug"])
    parser.add_argument("--base", default=None)
    parser.add_argument("--requirements", default=None)
    parser.add_argument("--skip-ensure-graphs", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    try:
        pack = prepare_review_context(
            repo_root,
            op_name,
            base=args.base,
            mode=args.mode,
            requirements=args.requirements,
            ensure_graphs=not args.skip_ensure_graphs,
            write=not args.dry_run,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"uo-prepare-review-context failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"uo-prepare-review-context ready={pack.get('ready')} mode={pack.get('mode')} "
        f"files={len(pack.get('changed_files') or [])} run={pack.get('run_id')}"
    )
    if pack.get("errors"):
        for err in pack["errors"]:
            print(f"  error: {err}", file=sys.stderr)
    if not pack.get("ready"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
