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

from understand_operator._core.config import load_config
from understand_operator._operator.artifacts import operator_root, safe_op_name, write_text
from understand_operator._operator.cbm_client import OperatorCbmClient, load_index_meta, summarize_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect code changes vs last KB state and write an incremental update plan",
    )
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name. Defaults to repository name.")
    parser.add_argument("--full", action="store_true", help="Force CBM index_repository before detect_changes")
    parser.add_argument("--cbm-binary", help="Path to codebase-memory-mcp binary")
    parser.add_argument("--cbm-mode", choices=["full", "moderate", "fast"], help="CBM index mode")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    config = load_config(repo_root)
    scanner_cfg = config.setdefault("scanner", {})
    if args.cbm_binary:
        scanner_cfg["cbm_binary"] = args.cbm_binary
    if args.cbm_mode:
        scanner_cfg["cbm_mode"] = args.cbm_mode

    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name)
    if not base.exists():
        print(f"KB not found: {base}")
        print("Run /uo-init first to build the operator knowledge base.")
        return 2

    meta = load_index_meta(base)
    client = OperatorCbmClient(repo_root, base, config)
    if meta.get("cbm_project"):
        client.project_name = str(meta["cbm_project"])

    index_notes: dict[str, Any] = {}
    if args.full:
        mode = str(scanner_cfg.get("cbm_mode") or "fast")
        index_result = client.call(
            "index_repository",
            {"repo_path": str(repo_root), "mode": mode},
            persist=False,
        )
        client.remember_project(index_result.get("result"))
        index_notes["index_repository"] = summarize_result(index_result.get("result"))
    else:
        status_result = client.call("index_status", {"repo_path": str(repo_root)}, persist=False)
        client.remember_project(status_result.get("result"))
        index_notes["index_status"] = summarize_result(status_result.get("result"))
        if not client.project_name:
            listed = client.call("list_projects", {}, persist=False)
            client.remember_project(listed.get("result"))

    detect = client.call("detect_changes", {"repo_path": str(repo_root)}, persist=False)
    change_payload = detect.get("result")
    change_set = _normalize_change_set(change_payload, repo_root=repo_root, op_name=op_name)
    update_plan = _build_update_plan(change_set)

    write_text(base / "cbm" / "change_set.yaml", _to_yaml(change_set))
    write_text(base / "archive" / "runs" / "update_plan.yaml", _to_yaml(update_plan))
    _append_update_history(base, change_set, update_plan)

    # Keep index_meta stamped so query/update share the same baseline pointer.
    from understand_operator._operator.cbm_client import write_index_meta

    write_index_meta(
        base,
        {
            **meta,
            "repo_root": str(repo_root),
            "op_name": op_name,
            "cbm_project": client.project_name or meta.get("cbm_project"),
            "cbm_binary": str(client.binary) if client.binary else meta.get("cbm_binary"),
            "indexed_at": datetime.now(tz=timezone.utc).isoformat(),
            "last_update_at": datetime.now(tz=timezone.utc).isoformat(),
            "index_summary": {**(meta.get("index_summary") or {}), **index_notes},
            "last_change_detect": summarize_result(change_payload),
        },
    )
    client.write_log()

    print(f"Incremental update plan for {op_name}")
    print(f"KB: {base}")
    print(f"change_set: {base / 'cbm' / 'change_set.yaml'}")
    print(f"update_plan: {base / 'archive' / 'runs' / 'update_plan.yaml'}")
    print(f"impacted_areas: {', '.join(update_plan.get('impacted_areas') or ['none'])}")
    print("Next: agent re-runs only impacted phases (see /uo-update skill), then quality_gate.py")
    return 0


def _normalize_change_set(payload: Any, *, repo_root: Path, op_name: str) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    files: list[str] = []
    symbols: list[str] = []
    raw_preview = ""

    if isinstance(payload, dict):
        for key in ("changed_files", "files", "file_paths", "paths"):
            val = payload.get(key)
            if isinstance(val, list):
                files.extend(str(x) for x in val)
        for key in ("symbols", "changed_symbols", "functions"):
            val = payload.get(key)
            if isinstance(val, list):
                symbols.extend(str(x) for x in val)
        raw_preview = json.dumps(payload, ensure_ascii=False)[:2000]
    elif isinstance(payload, list):
        files = [str(x) for x in payload]
        raw_preview = json.dumps(payload, ensure_ascii=False)[:2000]
    elif payload is not None:
        raw_preview = str(payload)[:2000]

    files = _unique(files)
    symbols = _unique(symbols)
    return {
        "version": 1,
        "op_name": op_name,
        "repo_root": str(repo_root),
        "detected_at": now,
        "changed_files": files,
        "changed_symbols": symbols,
        "raw_preview": raw_preview,
        "status": "ok" if (files or symbols or raw_preview) else "empty",
    }


def _build_update_plan(change_set: dict[str, Any]) -> dict[str, Any]:
    files = [f.lower().replace("\\", "/") for f in change_set.get("changed_files") or []]
    symbols = [s.lower() for s in change_set.get("changed_symbols") or []]
    blob = " ".join(files + symbols)

    areas: list[str] = []
    phases: list[str] = []

    def hit(*needles: str) -> bool:
        return any(n in blob for n in needles)

    if hit("proto", "op_api", "acl_op", "operator_io", "def.cpp", "def.h"):
        areas.append("boundary_io")
        phases.append("phase1")
    if hit("tiling", "op_host", "tilingdata", "tiling_key"):
        areas.append("tiling_host")
        phases.append("phase2_host")
    if hit("datacopy", "setflag", "waitflag", "pipe_", "dataflow", "compute"):
        areas.append("compute_dataflow")
        phases.append("phase2_flow")
    if hit("op_kernel", "kernel", "process(", "init("):
        areas.append("kernel")
        phases.extend(["phase3", "phase3.5", "phase4", "phase5"])
    if hit("golden", "test", "accuracy"):
        areas.append("test_contract")
        phases.append("phase7")

    if not areas and change_set.get("status") != "empty":
        areas.append("unknown_needs_review")
        phases.extend(["phase1", "phase2_host", "phase2_flow"])

    phases = _unique(phases)
    if phases:
        phases.extend(["phase6", "phase7", "phase8"])
        phases = _unique(phases)

    return {
        "version": 1,
        "status": "planned",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "impacted_areas": areas,
        "phases_to_rerun": phases,
        "preserve_untouched_artifacts": True,
        "full_rebuild_recommended": False,
        "notes": [
            "Agent should re-run only listed phases using the same prompts as /uo-init.",
            "Keep human review gates when boundary or kernel dispatch plans change.",
            "Source lookups remain CBM-first; whole-file Read only after CBM failure.",
        ],
    }


def _append_update_history(base: Path, change_set: dict[str, Any], update_plan: dict[str, Any]) -> None:
    path = base / "archive" / "runs" / "update_history.yaml"
    entry = (
        f"- at: {update_plan.get('created_at')}\n"
        f"  changed_files: {len(change_set.get('changed_files') or [])}\n"
        f"  impacted_areas: {update_plan.get('impacted_areas')}\n"
        f"  phases_to_rerun: {update_plan.get('phases_to_rerun')}\n"
    )
    if path.exists():
        prev = path.read_text(encoding="utf-8", errors="ignore")
        if not prev.startswith("version:"):
            prev = "version: 1\nentries:\n" + prev
        if "entries:" not in prev:
            prev = prev.rstrip() + "\nentries:\n"
        write_text(path, prev.rstrip() + "\n" + entry)
    else:
        write_text(path, "version: 1\nentries:\n" + entry)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _to_yaml(data: Any, indent: int = 0) -> str:
    """Minimal YAML emitter for nested dict/list/scalars (no external deps)."""
    sp = "  " * indent
    if isinstance(data, dict):
        if not data:
            return sp + "{}\n"
        lines: list[str] = []
        for key, val in data.items():
            if isinstance(val, (dict, list)):
                lines.append(f"{sp}{key}:")
                lines.append(_to_yaml(val, indent + 1).rstrip("\n"))
            else:
                lines.append(f"{sp}{key}: {_yaml_scalar(val)}")
        return "\n".join(lines) + "\n"
    if isinstance(data, list):
        if not data:
            return sp + "[]\n"
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{sp}-")
                lines.append(_to_yaml(item, indent + 1).rstrip("\n"))
            else:
                lines.append(f"{sp}- {_yaml_scalar(item)}")
        return "\n".join(lines) + "\n"
    return sp + _yaml_scalar(data) + "\n"


def _yaml_scalar(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    text = str(val)
    if text == "" or any(ch in text for ch in ":#{}[]&*!|>'\"%@`\n"):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


if __name__ == "__main__":
    raise SystemExit(main())
