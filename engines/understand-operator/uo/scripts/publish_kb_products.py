"""Shared KB product publishing (sqlite, human views, integrity, testcase contracts)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from uo._operator.artifacts import existing_operator_root
from uo.scripts._ir_io import read_yaml, write_yaml_if_changed


def publish_kb_products(
    repo_root: Path,
    op_name: str,
    *,
    graph: dict[str, Any] | None = None,
    write: bool = True,
    include_testcase_contract: bool = True,
    include_integrity: bool = True,
) -> dict[str, Any]:
    """Publish derived KB products after structural IR is complete.

    Order: testcase contract → sqlite → integrity (no human views) → human views once.
    """
    uo_root = existing_operator_root(repo_root, op_name)
    if graph is None:
        graph = read_yaml(uo_root / "ir" / "operator_graph.yaml") or {}

    result: dict[str, Any] = {"op_name": op_name, "status": "ok", "ok": True}
    timing_ms: dict[str, int] = {}

    if include_testcase_contract and graph:
        t0 = time.perf_counter()
        try:
            from uo.scripts.kb_query_export import materialize_testcase_contract_files

            materialize_testcase_contract_files(uo_root, graph)
            result["testcase_contract"] = "ok"
        except Exception as exc:  # noqa: BLE001
            result["testcase_contract"] = {"status": "error", "error": str(exc)[:300]}
            result["ok"] = False
        timing_ms["testcase_contract"] = int((time.perf_counter() - t0) * 1000)

    if not write:
        result["timing_ms"] = timing_ms
        return result

    t0 = time.perf_counter()
    try:
        from uo.scripts.export_kb_graph import export_kb_graph

        kb_stats = export_kb_graph(repo_root, op_name, write=True)
        result["kb_graph"] = kb_stats
        if kb_stats.get("status") == "skipped":
            result["sqlite_skipped"] = True
    except Exception as exc:  # noqa: BLE001
        result["kb_graph"] = {"status": "error", "error": str(exc)[:300]}
        result["ok"] = False
    timing_ms["sqlite_export"] = int((time.perf_counter() - t0) * 1000)

    if include_integrity:
        t0 = time.perf_counter()
        try:
            from uo.scripts.check_kb_integrity import check_kb_integrity

            integrity = check_kb_integrity(
                repo_root,
                op_name,
                write_outputs=True,
                refresh_human_views=False,
            )
            result["integrity"] = integrity
            if isinstance(integrity, dict) and integrity.get("status") == "fail":
                result["ok"] = False
        except Exception as exc:  # noqa: BLE001
            result["integrity"] = {"status": "error", "error": str(exc)[:300]}
            result["ok"] = False
        timing_ms["integrity_check"] = int((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    try:
        from uo.scripts.export_human_views import export_human_views

        human_stats = export_human_views(uo_root, write=True)
        result["human_views"] = human_stats
    except Exception as exc:  # noqa: BLE001
        result["human_views"] = {"status": "error", "error": str(exc)[:300]}
        result["ok"] = False
    timing_ms["human_view_export"] = int((time.perf_counter() - t0) * 1000)

    result["timing_ms"] = timing_ms
    write_yaml_if_changed(
        uo_root / "ir" / "publish_receipt.yaml",
        {
            "version": 1,
            "op_name": op_name,
            "ok": result.get("ok"),
            "timing_ms": timing_ms,
            "sqlite_status": (result.get("kb_graph") or {}).get("status")
            if isinstance(result.get("kb_graph"), dict)
            else None,
            "integrity_status": (result.get("integrity") or {}).get("status")
            if isinstance(result.get("integrity"), dict)
            else None,
        },
    )
    return result
