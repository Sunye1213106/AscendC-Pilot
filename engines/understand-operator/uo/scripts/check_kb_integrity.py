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
        "scope",
        "entrypoints",
        "extract_plan",
        "residual_resolve",
        "input_derivable",
        "export_graph",
        "none",
    }
)
# Normalize finding stages before Pilot reason bridging.
REWORK_STAGE_ALIASES = {
    "input_derivable": "residual_resolve",
    "entrypoints": "EXTRACT_REWORK",
    "extract_plan": "EXTRACT_REWORK",
}

# Domain rework_stage → Pilot transition reason_code (single bridge; no parallel FSM).
REWORK_STAGE_TO_REASON: dict[str, str] = {
    "scope": "SCOPE_REWORK",
    "entrypoints": "EXTRACT_REWORK",
    "extract_plan": "EXTRACT_REWORK",
    "residual_resolve": "INTEGRITY_REWORK",
    "input_derivable": "INTEGRITY_REWORK",
    "export_graph": "export_graph",
    "none": "none",
}


def map_rework_stage(stage: str) -> str:
    """Map integrity rework_stage to acp reason codes / aliases."""
    text = str(stage or "").strip()
    return str(REWORK_STAGE_ALIASES.get(text) or text)


def check_kb_integrity(repo_root: Path, op_name: str, *, write_outputs: bool = True) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    issues: list[dict[str, Any]] = []

    unresolved = read_yaml(uo_root / "ir" / "unresolved.yaml") or {}
    open_items = unresolved.get("items") if isinstance(unresolved.get("items"), list) else []
    open_count = len(open_items)
    blocking_unresolved = []
    degraded_unresolved = []
    for item in open_items:
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity") or "").lower()
        if sev in {"blocking", "error"} or sev == "":
            # Empty severity treated as blocking (legacy unresolved items).
            blocking_unresolved.append(item)
        elif sev == "degraded":
            degraded_unresolved.append(item)
    if blocking_unresolved:
        sample = [str(i.get("id")) for i in blocking_unresolved[:8]]
        issues.append(
            {
                "code": "OPEN_UNRESOLVED",
                "severity": "error",
                "rework_stage": "residual_resolve",
                "message": f"blocking unresolved={len(blocking_unresolved)}，须 disposition 入账后清零。样例: {sample}",
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

    ep_graph = read_yaml(uo_root / "ir" / "entrypoint_graph.yaml") or {}
    closure = ep_graph.get("closure") if isinstance(ep_graph.get("closure"), dict) else {}
    host_chain = str(closure.get("host_main_chain") or "")
    kernel_chain = str(closure.get("kernel_main_chain") or "")
    if not ep_graph:
        issues.append(
            {
                "code": "ENTRYPOINT_GRAPH_MISSING",
                "severity": "error",
                "rework_stage": "entrypoints",
                "message": "缺失 ir/entrypoint_graph.yaml；须先 resolve_entrypoints / build entrypoints 层",
            }
        )
    else:
        if host_chain != "closed":
            issues.append(
                {
                    "code": "ENTRYPOINT_HOST_CHAIN_OPEN",
                    "severity": "error",
                    "rework_stage": "entrypoints",
                    "message": f"entrypoint_graph.host_main_chain={host_chain or 'empty'}（须 closed）",
                }
            )
        if kernel_chain != "closed":
            issues.append(
                {
                    "code": "ENTRYPOINT_KERNEL_CHAIN_OPEN",
                    "severity": "error",
                    "rework_stage": "entrypoints",
                    "message": f"entrypoint_graph.kernel_main_chain={kernel_chain or 'empty'}（须 closed）",
                }
            )
        for block in closure.get("blocking_unresolved") or []:
            if not isinstance(block, dict):
                continue
            issues.append(
                {
                    "code": str(block.get("code") or "ENTRYPOINT_BLOCKING"),
                    "severity": "error",
                    "rework_stage": "entrypoints",
                    "message": str(block.get("reason") or "entrypoint blocking unresolved"),
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
        # Derived sqlite is the canonical *query* surface — must stay fresh vs YAML.
        try:
            from uo.scripts.kb_graph_query import index_status

            idx = index_status(uo_root)
            if idx.get("index_status") == "stale":
                issues.append(
                    {
                        "code": "SQLITE_STALE",
                        "severity": "error",
                        "rework_stage": "export_graph",
                        "message": (
                            "kb_graph.sqlite stale vs YAML source hashes; "
                            f"stale_keys={idx.get('stale_keys') or []}; re-run export_kb_graph"
                        ),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            issues.append(
                {
                    "code": "SQLITE_STATUS_ERROR",
                    "severity": "warning",
                    "rework_stage": "export_graph",
                    "message": f"kb_graph index_status failed: {exc}"[:240],
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
    coverage_stats = _collect_layered_coverage_issues(uo_root, issues)

    # Pilot KEY hard gates — script authority (cannot be skipped by soft prompts)
    try:
        from ascendc_pilot.gates import run_key_gates

        key_payload = run_key_gates(repo_root, op_name=op_name)
        if not key_payload.get("ok"):
            failed = [
                g.get("gate")
                for g in (key_payload.get("gates") or [])
                if isinstance(g, dict) and not g.get("ok")
            ]
            issues.append(
                {
                    "code": "HARNESS_KEY_GATES",
                    "severity": "error",
                    "rework_stage": "input_derivable",
                    "message": (
                        f"acp validate-key-gates failed: {failed}. "
                        "禁止跳过 triage / empty-only 假闭合 / 同文 bit-pack / 缺 confidence 原因审查。"
                    ),
                }
            )
    except ImportError:
        issues.append(
            {
                "code": "HARNESS_NOT_INSTALLED",
                "severity": "error",
                "rework_stage": "none",
                "message": "ascendc_pilot 未安装；integrity 无法执行 KEY 硬门禁（pip install -e ./pilot）",
            }
        )

    error_count = sum(1 for i in issues if i.get("severity") == "error")
    if error_count > 0:
        status = "fail"
    elif degraded_unresolved:
        status = "pass_with_degradation"
    else:
        status = "pass"

    boundary = read_yaml(uo_root / "ir" / "operator_boundary.yaml") or {}
    bridge = read_yaml(uo_root / "ir" / "bridge.yaml") or {}
    bridge_metrics = bridge.get("bridge_metrics") if isinstance(bridge.get("bridge_metrics"), dict) else {}
    id_true = int((id_stats or {}).get("true_count") or (id_stats or {}).get("input_derivable_true") or 0)
    id_false = int((id_stats or {}).get("false_count") or (id_stats or {}).get("input_derivable_false") or 0)
    id_unsolved = int((id_stats or {}).get("unsolved_count") or (id_stats or {}).get("input_derivable_unsolved") or 0)
    # Fallback: count from keys map if present
    if not (id_true or id_false or id_unsolved):
        id_doc = read_yaml(uo_root / "ir" / "input_derivable.yaml") or {}
        for entry in (id_doc.get("keys") or {}).values() if isinstance(id_doc.get("keys"), dict) else []:
            if not isinstance(entry, dict):
                continue
            v = entry.get("input_derivable")
            if v is True:
                id_true += 1
            elif v is False:
                id_false += 1
            else:
                id_unsolved += 1

    structural_ready = bool(
        host_chain == "closed"
        and kernel_chain == "closed"
        and (uo_root / "ir" / "host_subgraph.yaml").is_file()
        and (uo_root / "ir" / "kernel_subgraph.yaml").is_file()
    )
    boundary_ok = bool(boundary.get("inputs") or boundary.get("outputs"))
    semantic_ready = bool(
        structural_ready
        and boundary_ok
        and len(blocking_unresolved) == 0
        and error_count == 0
    )
    typed_bridge_count = int(bridge_metrics.get("host_produced_count") or 0)
    unknown_type_count = int(bridge_metrics.get("unknown_type_count") or 0)
    consumer_ready = bool(
        semantic_ready
        and typed_bridge_count > 0
        and not (id_true == 0 and id_false == 0 and id_unsolved > 0)
        and unknown_type_count < max(1, int(bridge_metrics.get("kernel_loaded_field_count") or 0))
    )
    if not boundary_ok:
        issues.append(
            {
                "code": "OPERATOR_BOUNDARY_EMPTY_OR_INVALID",
                "severity": "error",
                "rework_stage": "entrypoints",
                "message": "operator_boundary missing inputs/outputs; structural graph alone is not a complete KB",
            }
        )
        status = "fail"
        semantic_ready = False
        consumer_ready = False

    overall = "pass" if (structural_ready and semantic_ready and consumer_ready and status == "pass") else "fail"

    payload = {
        "version": 1,
        "status": status,
        "ok": status == "pass",
        "op_name": op_name,
        "open_unresolved_count": open_count,
        "blocking_unresolved_count": len(blocking_unresolved),
        "degraded_unresolved_count": len(degraded_unresolved),
        "entrypoint_closure": {
            "host_main_chain": host_chain,
            "kernel_main_chain": kernel_chain,
            "blocking_unresolved": list(closure.get("blocking_unresolved") or []),
            "closed": bool(host_chain == "closed" and kernel_chain == "closed" and not (closure.get("blocking_unresolved") or [])),
        },
        "ledger_count": len(ledger_items),
        "sqlite_orphan_src": orphan_src,
        "sqlite_orphan_dst": orphan_dst,
        "input_derivable": id_stats,
        "layered_coverage": coverage_stats,
        "bridge_metrics": bridge_metrics,
        "structural_status": "pass" if structural_ready else "fail",
        "semantic_status": "pass" if semantic_ready else "fail",
        "consumer_ready_status": "pass" if consumer_ready else "fail",
        "overall_status": overall,
        "structural_ready": structural_ready,
        "semantic_ready": semantic_ready,
        "tg_consumer_ready": consumer_ready,
        "issues": issues,
        "rework_reason": primary_rework_reason({"issues": issues}) if status != "pass" else "none",
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
        quality_path = uo_root / "quality.yaml"
        qdoc = read_yaml(quality_path) if quality_path.is_file() else {}
        if not isinstance(qdoc, dict):
            qdoc = {}
        qdoc.update(
            {
                "structural_status": payload.get("structural_status"),
                "semantic_status": payload.get("semantic_status"),
                "consumer_ready_status": payload.get("consumer_ready_status"),
                "overall_status": payload.get("overall_status"),
                "tg_consumer_ready": payload.get("tg_consumer_ready"),
                "integrity_status": status,
                "bridge_metrics": payload.get("bridge_metrics") or {},
            }
        )
        if status == "pass" and payload.get("overall_status") == "pass":
            qdoc["status"] = "pass"
            qdoc["decision"] = "pass"
        elif status != "pass":
            qdoc["status"] = "fail"
            qdoc["decision"] = "fail"
        write_yaml(quality_path, qdoc)
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
    """Normalize finding.rework_stage (applies REWORK_STAGE_ALIASES)."""
    stage = str(finding.get("rework_stage") or "none")
    stage = REWORK_STAGE_ALIASES.get(stage, stage)
    if stage not in REWORK_STAGES:
        return "none"
    return stage


def to_pilot_reason_code(finding: dict[str, Any] | str) -> str:
    """Map a domain finding (or stage string) to a Pilot transition reason_code."""
    if isinstance(finding, str):
        stage = REWORK_STAGE_ALIASES.get(finding, finding)
    else:
        stage = map_rework_stage(finding)
    return REWORK_STAGE_TO_REASON.get(stage, "INTEGRITY_REWORK")


def primary_rework_reason(integrity_payload: dict[str, Any]) -> str:
    """Pick the highest-priority acp reason from integrity issues."""
    priority = [
        "EXTRACT_REWORK",
        "SCOPE_REWORK",
        "INTEGRITY_REWORK",
        "export_graph",
    ]
    reasons: list[str] = []
    for issue in integrity_payload.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("severity") or "").lower() not in {"error", "blocking"}:
            continue
        reasons.append(to_pilot_reason_code(issue))
    for code in priority:
        if code in reasons:
            return code
    return reasons[0] if reasons else "INTEGRITY_REWORK"


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
                    f"uo-key-resolve / CBM 高置信补丁或标 not_input_derivable"
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
    for kid, entry in keys.items():
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


def _collect_layered_coverage_issues(uo_root: Path, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """⑧ Layered integrity: KEY / TilingData / CSV / main unit — not 'at least one chain'."""
    from uo.scripts.evidence_score import is_verified_confidence

    caps = read_yaml(uo_root / "ir" / "operator_capabilities.yaml") or {}
    graph = read_yaml(uo_root / "ir" / "operator_graph.yaml") or {}
    bridge = read_yaml(uo_root / "ir" / "bridge.yaml") or {}
    tilingkey = read_yaml(uo_root / "ir" / "tilingkey_space.yaml") or {}
    id_doc = read_yaml(uo_root / "ir" / "input_derivable.yaml") or {}
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    verified_edges = [e for e in edges if is_verified_confidence(e.get("confidence"))]

    stats: dict[str, Any] = {
        "has_tilingkey": caps.get("has_tilingkey"),
        "has_tilingdata": caps.get("has_tilingdata"),
        "verified_edge_count": len(verified_edges),
        "key_coverage_gaps": [],
        "tilingdata_gaps": [],
        "csv_gaps": [],
    }

    # 1) Each input_derivable=true KEY dimension needs a verified path.
    if caps.get("has_tilingkey") is True or caps.get("has_tilingkey") is None:
        keys = id_doc.get("keys") if isinstance(id_doc.get("keys"), dict) else {}
        for key_name, entry in keys.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("input_derivable") is True:
                has_path = bool(entry.get("host_parent") or entry.get("derivation_roots") or entry.get("graph_markers"))
                # Prefer verified-only markers when present.
                markers = entry.get("graph_markers") or []
                if markers and not any(
                    is_verified_confidence(m.get("confidence")) for m in markers if isinstance(m, dict)
                ):
                    # markers without confidence still accepted if host_parent exists
                    if not entry.get("host_parent"):
                        has_path = False
                if not has_path:
                    stats["key_coverage_gaps"].append(key_name)
        if stats["key_coverage_gaps"]:
            issues.append(
                {
                    "code": "KEY_COVERAGE_INCOMPLETE",
                    "severity": "error",
                    "rework_stage": "input_derivable",
                    "message": (
                        f"input_derivable KEY 缺完整 verified 路径: {stats['key_coverage_gaps'][:12]} "
                        f"（禁止仅靠一条弱链验收）"
                    ),
                }
            )
    elif caps.get("has_tilingkey") is False:
        stats["key_coverage_skipped"] = "capability_has_tilingkey_false"

    # 2) Each verified TilingData bridge needs host writer + kernel reader.
    if caps.get("has_tilingdata") is not False:
        for b in bridge.get("tilingdata_bridges") or bridge.get("bridge_edges") or []:
            if not isinstance(b, dict):
                continue
            if not is_verified_confidence(b.get("confidence")):
                continue
            has_host = bool(b.get("host_writer") or b.get("host_symbol") or b.get("writer"))
            has_kern = bool(b.get("kernel_reader") or b.get("kernel_symbol") or b.get("reader"))
            if not (has_host and has_kern):
                gap = b.get("field_path") or b.get("id") or "unknown_bridge"
                stats["tilingdata_gaps"].append(gap)
        if stats["tilingdata_gaps"]:
            issues.append(
                {
                    "code": "TILINGDATA_BRIDGE_INCOMPLETE",
                    "severity": "error",
                    "rework_stage": "extract_plan",
                    "message": f"verified TilingData bridge 缺 Host writer 或 Kernel reader: {stats['tilingdata_gaps'][:12]}",
                }
            )

    # 3) CSV-controllable determinants must trace to Input/Attr via verified edges.
    for det in tilingkey.get("csv_controllable_determinants") or graph.get("csv_controllable_determinants") or []:
        if not isinstance(det, dict):
            continue
        if det.get("traced_to_input"):
            continue
        # Look for verified reaches_input / determined_by
        name = str(det.get("name") or det.get("id") or "")
        linked = any(
            e.get("type") in {"reaches_input", "determined_by", "derives"}
            and name
            and name in str(e.get("source") or "") + str(e.get("target") or "")
            for e in verified_edges
        )
        if not linked:
            stats["csv_gaps"].append(name or "unnamed")
    if stats["csv_gaps"]:
        issues.append(
            {
                "code": "CSV_DETERMINANT_UNREACHABLE",
                "severity": "error",
                "rework_stage": "input_derivable",
                "message": f"CSV-controllable determinant 无法经 verified 边回溯 Input/Attr: {stats['csv_gaps'][:12]}",
            }
        )

    # 4) Main extraction unit needs at least one verified main chain (already gated via entrypoint closure).
    # 5) Open critical gaps must appear in blocking/degraded ledger — surface informational silence.
    llm = read_yaml(uo_root / "ir" / "llm_tasks.yaml") or {}
    open_blocking = [
        t for t in (llm.get("tasks") or []) if isinstance(t, dict) and t.get("status") == "open" and t.get("severity") == "blocking"
    ]
    if open_blocking:
        issues.append(
            {
                "code": "OPEN_BLOCKING_LLM_TASKS",
                "severity": "error",
                "rework_stage": "extract_plan",
                "message": f"存在未解决 blocking LLM tasks={len(open_blocking)}",
            }
        )

    # Candidate-only provenance must not satisfy reachability claims.
    candidate_provenance = [
        e
        for e in edges
        if e.get("type") in {"derives", "writes", "reaches_input"}
        and str(e.get("confidence") or "").casefold() in {"candidate", "structurally_inferred"}
    ]
    stats["candidate_provenance_edges"] = len(candidate_provenance)
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
    parser = argparse.ArgumentParser(description="KB integrity gate for UO")
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
    return 0 if result["status"] in {"pass", "pass_with_degradation"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
