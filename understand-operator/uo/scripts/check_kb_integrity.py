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
    {
        "phase0_scope",
        "entrypoints",
        "extract_plan",
        "residual_resolve",
        "input_derivable",
        "export_graph",
        "none",
    }
)
# Parent action alias: input_derivable → residual_resolve + classify/escalate.
REWORK_STAGE_ALIASES = {
    "input_derivable": "residual_resolve",
}


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

    id_stats = _collect_input_derivable_issues(uo_root, issues)

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
        "input_derivable": id_stats,
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
    """Parent routing helper for kb-review findings.

    `input_derivable` is a first-class finding stage; parents may alias it to
    residual_resolve via REWORK_STAGE_ALIASES when reusing the resolve loop.
    """
    stage = str(finding.get("rework_stage") or "none")
    if stage not in REWORK_STAGES:
        return "none"
    return stage


def _collect_input_derivable_issues(uo_root: Path, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Machine checks for compact input-derivable product (review + integrity)."""
    id_path = uo_root / "ir" / "input_derivable.yaml"
    gaps_path = uo_root / "ir" / "input_derivable_gaps.yaml"
    stats: dict[str, Any] = {
        "file_present": id_path.is_file(),
        "true": 0,
        "false": 0,
        "unsolved": 0,
        "open_gaps": 0,
        "contract_checked": 0,
    }
    if not id_path.is_file():
        issues.append(
            {
                "code": "INPUT_DERIVABLE_MISSING",
                "severity": "error",
                "rework_stage": "input_derivable",
                "message": "缺失 ir/input_derivable.yaml；须先跑 classify_input_derivable",
            }
        )
        return stats

    id_doc = read_yaml(id_path) or {}
    keys = id_doc.get("keys") if isinstance(id_doc.get("keys"), dict) else {}
    markers = id_doc.get("graph_markers") if isinstance(id_doc.get("graph_markers"), list) else []
    file_stats = id_doc.get("stats") if isinstance(id_doc.get("stats"), dict) else {}
    stats["true"] = int(file_stats.get("true") or sum(1 for v in keys.values() if isinstance(v, dict) and v.get("input_derivable") is True))
    stats["false"] = int(file_stats.get("false") or sum(1 for v in keys.values() if isinstance(v, dict) and v.get("input_derivable") is False))
    stats["unsolved"] = int(
        file_stats.get("unsolved")
        or sum(1 for v in keys.values() if isinstance(v, dict) and v.get("input_derivable") == "unsolved")
    )

    # Open gaps report
    open_gap_ids: list[str] = []
    if gaps_path.is_file():
        gaps_doc = read_yaml(gaps_path) or {}
        gap_items = gaps_doc.get("gaps") if isinstance(gaps_doc.get("gaps"), list) else []
        for g in gap_items:
            if not isinstance(g, dict):
                continue
            gstatus = str(g.get("status") or "unresolved").lower()
            if gstatus in {"unresolved", "open", ""}:
                open_gap_ids.append(str(g.get("id") or g.get("target") or "?"))
        if str(gaps_doc.get("status") or "").lower() == "open" and not open_gap_ids and gap_items:
            open_gap_ids = [str(g.get("id") or "?") for g in gap_items if isinstance(g, dict)]
    elif stats["unsolved"] > 0:
        issues.append(
            {
                "code": "INPUT_DERIVABLE_GAPS_MISSING",
                "severity": "error",
                "rework_stage": "input_derivable",
                "message": f"有 unsolved={stats['unsolved']} 但缺失 ir/input_derivable_gaps.yaml",
            }
        )
    stats["open_gaps"] = len(open_gap_ids)
    if open_gap_ids:
        sample = open_gap_ids[:8]
        # reported leftovers: confidence_gate documented them → warning (not hard fail).
        # Otherwise open gaps block integrity (cannot claim pass + reported simultaneously as closed).
        conf = read_yaml(uo_root / "checks" / "confidence_gate.yaml") or {}
        conf_status = str(conf.get("status") or "").lower() if isinstance(conf, dict) else ""
        severity = "warning" if conf_status == "reported" else "error"
        issues.append(
            {
                "code": "INPUT_DERIVABLE_OPEN_GAPS",
                "severity": severity,
                "rework_stage": "input_derivable",
                "message": (
                    f"input_derivable 开放缺口={len(open_gap_ids)}，须 "
                    f"uo-semantic-resolve 任务 E / CBM 高置信补丁或标 not_input_derivable"
                    f"{'（confidence_gate=reported：已写报告，降为 warning）' if severity == 'warning' else ''}。"
                    f"样例: {sample}"
                ),
            }
        )

    # Compact schema: true must have parent or roots; ban full-chain dump fields
    bad_true: list[str] = []
    bloated: list[str] = []
    for kid, entry in keys.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("host_derivation_chain") or entry.get("function_chain"):
            bloated.append(str(kid))
        if entry.get("input_derivable") is True:
            parent = entry.get("host_parent")
            roots = entry.get("derivation_roots") or []
            if not parent and not roots:
                bad_true.append(str(kid))
    if bad_true:
        issues.append(
            {
                "code": "INPUT_DERIVABLE_TRUE_NO_PARENT",
                "severity": "error",
                "rework_stage": "input_derivable",
                "message": f"input_derivable=true 但缺 host_parent/derivation_roots: {bad_true[:8]}",
            }
        )
    if bloated:
        issues.append(
            {
                "code": "INPUT_DERIVABLE_CHAIN_BLOAT",
                "severity": "warning",
                "rework_stage": "none",
                "message": f"存在完整链字段（应只用一跳 parent+图标记）: {bloated[:8]}",
            }
        )

    # Cross-check ir/input_derivable ↔ tiling/key_space (contracts/** retired; never required).
    key_space = read_yaml(uo_root / "tiling" / "key_space.yaml") or {}
    space_keys = key_space.get("keys") if isinstance(key_space.get("keys"), dict) else {}
    if not space_keys and isinstance(key_space.get("items"), list):
        space_keys = {
            str(it.get("id") or it.get("key_id")): it
            for it in key_space["items"]
            if isinstance(it, dict) and (it.get("id") or it.get("key_id"))
        }
    mismatch: list[str] = []
    for kid, entry in list(keys.items())[:40]:
        if not isinstance(entry, dict):
            continue
        idv = entry.get("input_derivable")
        # true/unsolved keys should appear in exported key_space when present
        if space_keys and (idv in (True, "unsolved") or entry.get("needs_binding")):
            sk = space_keys.get(kid) if isinstance(space_keys.get(kid), dict) else None
            if sk is None:
                # tolerate KEY_ prefix drift
                alt = kid.removeprefix("KEY_") if kid.startswith("KEY_") else f"KEY_{kid}"
                sk = space_keys.get(alt) if isinstance(space_keys.get(alt), dict) else None
            if sk is None:
                mismatch.append(f"{kid}:missing_in_key_space")
                continue
            stats["key_space_checked"] = int(stats.get("key_space_checked") or 0) + 1
            if idv is True and sk.get("needs_binding") is False and entry.get("needs_binding") is not False:
                # soft: key_space may omit needs_binding; only flag explicit false vs true
                pass
            if (idv is False or entry.get("not_input_derivable")) and sk.get("needs_binding") is True:
                mismatch.append(f"{kid}:false_but_key_space_needs_binding")
        if idv is True and not (entry.get("host_parent") or entry.get("derivation_roots")):
            # already covered by INPUT_DERIVABLE_TRUE_NO_PARENT; skip duplicate
            pass
    # legacy alias for stats consumers
    stats["contract_checked"] = int(stats.get("key_space_checked") or 0)
    if mismatch:
        issues.append(
            {
                "code": "INPUT_DERIVABLE_KEY_SPACE_MISMATCH",
                "severity": "error",
                "rework_stage": "export_graph",
                "message": f"input_derivable 与 tiling/key_space 不一致: {mismatch[:10]}",
            }
        )

    # Markers present when any true keys
    if stats["true"] > 0 and not markers:
        issues.append(
            {
                "code": "INPUT_DERIVABLE_MARKERS_EMPTY",
                "severity": "warning",
                "rework_stage": "export_graph",
                "message": "有 input_derivable=true 的 KEY 但 graph_markers 为空（KB 图缺 determined_by/reaches_input）",
            }
        )

    return stats


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
