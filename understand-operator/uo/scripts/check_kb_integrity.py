from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo._operator.kb_compiler import validate_kb
from uo.scripts._ir_io import read_yaml, write_yaml

REWORK_STAGES = frozenset(
    {"phase0_scope", "entrypoints", "extract_plan", "residual_resolve", "export_graph", "none"}
)


def check_kb_integrity(repo_root: Path, op_name: str, *, write_outputs: bool = True) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    issues: list[dict[str, Any]] = []

    unresolved = read_yaml(uo_root / "ir" / "unresolved.yaml") or {}
    open_items = unresolved.get("items") if isinstance(unresolved.get("items"), list) else []
    open_count = len(open_items)
    if open_count > 0:
        sample = [str(i.get("id")) for i in open_items[:8]]
        issues.append(
            {
                "code": "OPEN_UNRESOLVED",
                "severity": "error",
                "rework_stage": "residual_resolve",
                "message": f"开放 unresolved={open_count}，须 disposition 入账后清零。样例: {sample}",
            }
        )

    ledger = read_yaml(uo_root / "ir" / "resolution_ledger.yaml") or {}
    ledger_items = ledger.get("items") if isinstance(ledger.get("items"), list) else []
    if open_count == 0 and not ledger_items:
        # Fresh build with zero diagnostics is ok; only warn.
        issues.append(
            {
                "code": "LEDGER_EMPTY",
                "severity": "warning",
                "rework_stage": "none",
                "message": "resolution_ledger 为空（若 build 曾产出 DIAG，应有入账）",
            }
        )

    entrypoints = read_yaml(uo_root / "ir" / "entrypoints.yaml") or {}
    roles = entrypoints.get("roles") if isinstance(entrypoints.get("roles"), dict) else {}
    for role in ("host_tiling_entry", "kernel_entry"):
        body = roles.get(role) if isinstance(roles.get(role), dict) else {}
        if not body and isinstance(entrypoints.get(role), dict):
            body = entrypoints[role]
        status = str(body.get("status") or "").lower()
        selected = body.get("selected") if isinstance(body.get("selected"), dict) else {}
        name = selected.get("name") or selected.get("qualified_name") or body.get("name") or body.get("qualified_name")
        confirmed = status == "confirmed" or bool(body.get("confirmed_by") or selected.get("confirmed_by"))
        if not confirmed or not name or str(name).lower() == "unknown":
            issues.append(
                {
                    "code": "ENTRYPOINT_UNCONFIRMED",
                    "severity": "error",
                    "rework_stage": "entrypoints",
                    "message": f"入口角色 {role} 未确认（status={status or 'empty'}, name={name!r}）",
                }
            )

    db_path = uo_root / "indexes" / "kb_graph.sqlite"
    orphan_src = orphan_dst = 0
    if db_path.is_file():
        orphan_src, orphan_dst = _sqlite_orphan_counts(db_path)
        if orphan_src or orphan_dst:
            issues.append(
                {
                    "code": "SQLITE_ORPHAN_EDGES",
                    "severity": "error",
                    "rework_stage": "export_graph",
                    "message": f"kb_graph.sqlite 断头边 orphan_src={orphan_src} orphan_dst={orphan_dst}",
                }
            )
    else:
        issues.append(
            {
                "code": "SQLITE_MISSING",
                "severity": "error",
                "rework_stage": "export_graph",
                "message": "indexes/kb_graph.sqlite 缺失，请先 export_kb_graph",
            }
        )

    blockers = read_yaml(uo_root / "ir" / "integrity_blockers.yaml") or {}
    blocker_items = blockers.get("items") if isinstance(blockers.get("items"), list) else []
    if blocker_items:
        issues.append(
            {
                "code": "INTEGRITY_BLOCKERS",
                "severity": "error",
                "rework_stage": "residual_resolve",
                "message": f"存在 integrity_blockers={len(blocker_items)}，每条须写清无法判定原因",
            }
        )

    error_count = sum(1 for i in issues if i.get("severity") == "error")
    status = "pass" if error_count == 0 else "fail"
    payload = {
        "version": 1,
        "status": status,
        "op_name": op_name,
        "open_unresolved_count": open_count,
        "ledger_count": len(ledger_items),
        "sqlite_orphan_src": orphan_src,
        "sqlite_orphan_dst": orphan_dst,
        "issues": issues,
    }

    # Fold into validate_kb / final
    final_result = validate_kb(uo_root, op_name, phase="final", write_outputs=write_outputs)
    if status == "fail" and write_outputs:
        final_path = uo_root / "checks" / "final.yaml"
        final_doc = read_yaml(final_path) or {}
        if isinstance(final_doc, dict):
            final_doc["status"] = "fail"
            merged_issues = list(final_doc.get("issues") or [])
            for issue in issues:
                if issue.get("severity") == "error":
                    merged_issues.append(
                        {
                            "code": issue.get("code"),
                            "severity": "error",
                            "message": issue.get("message"),
                        }
                    )
            final_doc["issues"] = merged_issues
            final_doc["integrity_status"] = status
            write_yaml(final_path, final_doc)
            # quality.yaml mirror if present
            quality = uo_root / "quality.yaml"
            if quality.is_file():
                write_yaml(
                    quality,
                    {
                        "status": "fail",
                        "decision": "fail",
                        "checks": ["layered_ir", "final", "integrity"],
                        "integrity_status": status,
                    },
                )

    if write_outputs:
        out = uo_root / "checks" / "integrity.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_yaml(out, payload)
        # Refresh overview so integrity status is visible (not stuck at "unknown").
        try:
            from uo.scripts.export_human_views import export_human_views

            export_human_views(uo_root, write=True)
            payload["overview_refreshed"] = True
        except Exception as exc:  # noqa: BLE001
            payload["overview_refreshed"] = False
            payload["overview_refresh_error"] = str(exc)

    payload["final_status"] = final_result.status
    return payload


def map_rework_stage(finding: dict[str, Any]) -> str:
    """Parent routing helper for kb-review findings."""
    stage = str(finding.get("rework_stage") or "none")
    return stage if stage in REWORK_STAGES else "none"


def _sqlite_orphan_counts(db_path: Path) -> tuple[int, int]:
    con = sqlite3.connect(str(db_path))
    try:
        orphan_src = con.execute(
            "SELECT COUNT(*) FROM relations WHERE source_id NOT IN (SELECT id FROM entities)"
        ).fetchone()[0]
        orphan_dst = con.execute(
            "SELECT COUNT(*) FROM relations WHERE target_id NOT IN (SELECT id FROM entities)"
        ).fetchone()[0]
        return int(orphan_src), int(orphan_dst)
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KB integrity gate for understand-operator")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    result = check_kb_integrity(repo_root, op_name, write_outputs=not args.no_write)
    print(
        f"integrity status={result['status']} open_unresolved={result['open_unresolved_count']} "
        f"orphan_src={result['sqlite_orphan_src']} orphan_dst={result['sqlite_orphan_dst']} "
        f"issues={len(result.get('issues') or [])}"
    )
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
