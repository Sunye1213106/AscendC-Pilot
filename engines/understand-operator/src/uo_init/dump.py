# -*- coding: utf-8 -*-
"""Reconstruct YAML view layers from the authoritative KB SQLite product."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from uo_init.kb_index import (
    get_meta,
    list_view_blobs,
    load_all_view_blobs,
    load_host_derivation_from_db,
    load_legal_keys_from_db,
    load_view_blob,
)

# Short aliases → view_blob names stored by export_kb / rebuild_index.
VIEW_ALIASES: dict[str, str] = {
    "manifest": "manifest.yaml",
    "quality": "quality.yaml",
    "operator": "operator.yaml",
    "operator_graph": "ir/operator_graph.yaml",
    "graph": "ir/operator_graph.yaml",
    "tilingdata": "views/tilingdata.yaml",
    "kernel": "views/kernel.yaml",
    "call_graph": "views/call_graph.yaml",
    "key_reachability": "tiling/key_reachability.yaml",
    "key_space": "tiling/key_space.yaml",
    "exhaustive_key_space": "tiling/exhaustive_key_space.yaml",
    "coverage_model": "tiling/coverage_model.yaml",
    "variables": "tiling/variables.yaml",
    "constraints": "tiling/constraints.yaml",
    "host_derivation": "ir/host_derivation.yaml",
    "tg_host_view": "ir/tg_host_view.yaml",
    "integrity": "checks/integrity.yaml",
    "artifact_hashes": "checks/artifact_hashes.yaml",
    "legal_key_index": "tiling/legal_key_index.jsonl",
}


def resolve_view_name(view: str) -> str:
    text = str(view or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("view name required")
    if text in VIEW_ALIASES:
        return VIEW_ALIASES[text]
    if text.endswith(".yaml") or text.endswith(".yml") or text.endswith(".jsonl"):
        return text
    # Allow bare layer stems like "tiling/key_space"
    if "/" in text and not text.endswith(".yaml"):
        return text + ".yaml"
    if text + ".yaml" in VIEW_ALIASES.values():
        return text + ".yaml"
    return VIEW_ALIASES.get(text, text)


def dump_view(
    uo_root: str | Path,
    view: str,
    *,
    out: str | Path | None = None,
) -> dict[str, Any]:
    """Load one view from DB and optionally write it to ``out`` (YAML/JSONL)."""
    root = Path(uo_root).expanduser().resolve()
    db = root / "indexes" / "kb_graph.sqlite"
    if not db.is_file():
        raise FileNotFoundError(f"missing KB database: {db}")

    name = resolve_view_name(view)
    if name == "tiling/legal_key_index.jsonl":
        rows = load_legal_keys_from_db(db)
        text = "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        )
        payload: Any = rows
        if out is not None:
            path = Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return {
            "ok": True,
            "view": name,
            "count": len(rows),
            "out": str(out) if out else "",
            "payload": payload,
        }

    if name in {"ir/host_derivation.yaml", "host_derivation"}:
        payload = load_view_blob(db, "ir/host_derivation.yaml")
        if payload is None:
            payload = load_host_derivation_from_db(db)
    else:
        payload = load_view_blob(db, name)

    if payload is None and name == "manifest.yaml":
        meta = get_meta(db)
        payload = {
            "version": int(meta.get("version") or 1),
            "status": meta.get("manifest_status") or "extracted",
            "authority": meta.get("authority") or "db",
            "product": "indexes/kb_graph.sqlite",
            "derived_index": "indexes/kb_graph.sqlite",
            "op_name": meta.get("op_name") or "",
            "architecture": meta.get("architecture") or "",
            "graph_fingerprint": meta.get("graph_fingerprint") or "",
            "schema": meta.get("schema") or "kb_schema-v1",
            "legal_key_count": int(meta.get("legal_key_count") or 0),
            "integrity_status": meta.get("integrity_status") or "",
        }

    if payload is None:
        available = list_view_blobs(db)
        raise KeyError(
            f"view not found in DB: {name}; available={available[:40]}"
        )

    if out is not None:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                sort_keys=True,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
    return {
        "ok": True,
        "view": name,
        "out": str(out) if out else "",
        "payload": payload,
    }


def dump_all_views(
    uo_root: str | Path, *, out_dir: str | Path | None = None
) -> dict[str, Any]:
    """Materialize every stored view_blob (and legal_key_index) under out_dir."""
    root = Path(uo_root).expanduser().resolve()
    db = root / "indexes" / "kb_graph.sqlite"
    if not db.is_file():
        raise FileNotFoundError(f"missing KB database: {db}")
    target = Path(out_dir).expanduser().resolve() if out_dir else root
    written: list[str] = []
    for name, payload in load_all_view_blobs(db).items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                sort_keys=True,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        written.append(name)
    keys = load_legal_keys_from_db(db)
    if keys:
        path = target / "tiling" / "legal_key_index.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                for row in keys
            ),
            encoding="utf-8",
        )
        written.append("tiling/legal_key_index.jsonl")
    return {"ok": True, "out_dir": target.as_posix(), "written": written}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m uo_init.dump",
        description="Dump a KB view from indexes/kb_graph.sqlite",
    )
    parser.add_argument(
        "view",
        nargs="?",
        default="",
        help="view name/alias (manifest, quality, tilingdata, kernel, …) or --all",
    )
    parser.add_argument(
        "--uo-root",
        default="",
        help="UO root containing indexes/kb_graph.sqlite",
    )
    parser.add_argument("--out", default="", help="output file path")
    parser.add_argument(
        "--all",
        action="store_true",
        help="dump every stored view into --out directory (or uo-root)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list available view_blob names and exit",
    )
    args = parser.parse_args(argv)

    uo = Path(args.uo_root).expanduser().resolve() if args.uo_root else Path.cwd()
    db = uo / "indexes" / "kb_graph.sqlite"
    if args.list:
        if not db.is_file():
            print(json.dumps({"ok": False, "error": f"missing {db}"}))
            return 1
        print(json.dumps({"ok": True, "views": list_view_blobs(db)}, ensure_ascii=False))
        return 0

    try:
        if args.all or args.view in {"all", "--all"}:
            result = dump_all_views(uo, out_dir=args.out or None)
            print(json.dumps({k: v for k, v in result.items() if k != "payload"}, ensure_ascii=False))
            return 0
        if not args.view:
            parser.error("view required (or pass --all / --list)")
        result = dump_view(uo, args.view, out=args.out or None)
        if args.out:
            print(json.dumps({k: v for k, v in result.items() if k != "payload"}, ensure_ascii=False))
        else:
            yaml.safe_dump(
                result.get("payload"),
                sys.stdout,
                allow_unicode=True,
                sort_keys=True,
                default_flow_style=False,
            )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
