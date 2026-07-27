"""Host contract gap：确定性生成候选边，LLM 仅裁决 candidate_edge_id。"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.host_configuration_builder import load_host_configuration
from uo.scripts.tiling_contract_builder import load_tiling_contract

GAP_VERSION = "1.0.0"


def _cid(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return "CAND_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def generate_candidate_edges(
    hcg: dict[str, Any],
    tcg: dict[str, Any],
) -> list[dict[str, Any]]:
    """从 unresolved 生成候选边（确定性），不发明新实体。"""
    candidates: list[dict[str, Any]] = []
    entities = {
        e["id"]: e
        for e in (hcg.get("entities") or []) + (tcg.get("entities") or [])
        if isinstance(e, dict) and e.get("id")
    }
    host_values = [
        e
        for e in entities.values()
        if e.get("kind") in {"HostValue", "HostDerivedValue"}
    ]
    field_writes = [e for e in entities.values() if e.get("kind") == "FieldWrite"]
    key_sels = [e for e in entities.values() if e.get("kind") == "KeyDimensionSelection"]

    for un in (tcg.get("unresolved") or []) + (hcg.get("unresolved") or []):
        code = str(un.get("reason_code") or "")
        if code == "VALUE_SOURCE_UNRESOLVED":
            sym = str(un.get("symbol") or "")
            edge_id = str(un.get("edge_id") or "")
            for hv in host_values:
                if sym and sym in str(hv.get("qualified_name") or "") or sym == hv.get("lhs_text"):
                    for fw in field_writes:
                        if edge_id and edge_id not in str(fw.get("id")):
                            # still allow as candidate to that write if symbol in rhs
                            rhs = (fw.get("rhs_expression_ir") or {}).get("source_text") or ""
                            if sym not in rhs:
                                continue
                        cand_id = _cid("DERIVES", hv["id"], fw["id"], sym)
                        candidates.append(
                            {
                                "candidate_edge_id": cand_id,
                                "proposed_type": "DERIVES",
                                "source_ids": [hv["id"]],
                                "target_ids": [fw["id"]],
                                "reason_code": code,
                                "allowed_entities": [hv["id"], fw["id"]],
                                "allowed_edges": [cand_id],
                                "evidence_refs": list(hv.get("evidence_refs") or [])
                                + list(fw.get("evidence_refs") or []),
                                "status": "pending",
                            }
                        )
        elif code == "TILING_KEY_ARGUMENT_UNGROUNDED":
            arg = str(un.get("argument") or "")
            for hv in host_values:
                if arg and (
                    arg == hv.get("qualified_name")
                    or arg == hv.get("lhs_text")
                    or arg in str(hv.get("qualified_name") or "")
                ):
                    for sel in key_sels:
                        if int(sel.get("argument_position", -1)) != int(un.get("position", -2)):
                            continue
                        cand_id = _cid("DERIVES", hv["id"], sel["id"], arg)
                        candidates.append(
                            {
                                "candidate_edge_id": cand_id,
                                "proposed_type": "DERIVES",
                                "source_ids": [hv["id"]],
                                "target_ids": [sel["id"]],
                                "reason_code": code,
                                "allowed_entities": [hv["id"], sel["id"]],
                                "allowed_edges": [cand_id],
                                "evidence_refs": list(hv.get("evidence_refs") or []),
                                "status": "pending",
                            }
                        )
        elif code in {
            "RECEIVER_IDENTITY_AMBIGUOUS",
            "HOST_CALL_TARGET_AMBIGUOUS",
            "MACRO_BINDING_BODY_UNAVAILABLE",
            "TILING_SCHEMA_VARIANT_AMBIGUOUS",
            "TILING_KEY_ARITY_MISMATCH",
            "COMPILE_CONDITION_UNKNOWN",
        }:
            # 无可安全候选边：保留 unresolved，不生成自由边
            candidates.append(
                {
                    "candidate_edge_id": _cid("NOEDGE", code, un.get("message")),
                    "proposed_type": None,
                    "source_ids": [],
                    "target_ids": [],
                    "reason_code": code,
                    "allowed_entities": [],
                    "allowed_edges": [],
                    "status": "unresolvable_by_llm",
                    "message": "该断链不允许 LLM 发明边，仅可标记 unresolved",
                    "unresolved_ref": un,
                }
            )
    return candidates


def prepare_host_contract_gaps(
    repo_root: Path,
    op_name: str,
    *,
    uo_root: Path | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    hcg = load_host_configuration(root)
    tcg = load_tiling_contract(root)
    candidates = generate_candidate_edges(hcg, tcg)
    pending = [c for c in candidates if c.get("status") == "pending"]
    doc = {
        "version": GAP_VERSION,
        "phase": "prepare",
        "candidates": candidates,
        "counts": {
            "candidates": len(candidates),
            "pending_llm": len(pending),
            "unresolvable": len(
                [c for c in candidates if c.get("status") == "unresolvable_by_llm"]
            ),
        },
        "snapshot": {
            "hcg_entity_count": len(hcg.get("entities") or []),
            "tcg_entity_count": len(tcg.get("entities") or []),
            "compile_context_id": hcg.get("compile_context_id") or tcg.get("compile_context_id"),
        },
    }
    out_dir = run_dir or (root / "ir")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(out_dir / "host_contract_gaps.yaml", doc)
    # LLM worker batches: only pending with real proposed edges
    batches = []
    for idx, cand in enumerate(pending):
        batches.append(
            {
                "batch_id": f"gap_{idx:03d}",
                "candidate_edge_id": cand["candidate_edge_id"],
                "allowed_entities": cand["allowed_entities"],
                "allowed_edges": cand["allowed_edges"],
                "reason_code": cand["reason_code"],
                "evidence_refs": cand.get("evidence_refs") or [],
                "instruction_zh": (
                    "仅裁决该 candidate_edge_id：confirmed / rejected / unresolved。"
                    "禁止输出自由 source/target/relation，禁止发明实体或表达式。"
                ),
            }
        )
    write_yaml(out_dir / "host_contract_gap_batches.yaml", {"batches": batches})
    return doc


def apply_gap_decisions(
    decisions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """校验 LLM 裁决：只能引用已有 candidate_edge_id。"""
    by_id = {c["candidate_edge_id"]: c for c in candidates}
    accepted_edges: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for dec in decisions:
        if not isinstance(dec, dict):
            rejected.append({"reason": "决策不是对象", "decision": dec})
            continue
        # Support nested decision: {decision: {...}}
        payload = dec.get("decision") if isinstance(dec.get("decision"), dict) else dec
        cid = str(payload.get("candidate_edge_id") or "")
        status = str(payload.get("status") or "")
        if cid not in by_id:
            rejected.append(
                {
                    "reason": "candidate_edge_id 不在白名单",
                    "candidate_edge_id": cid,
                }
            )
            continue
        if status not in {"confirmed", "rejected", "unresolved"}:
            rejected.append(
                {
                    "reason": "非法 status",
                    "candidate_edge_id": cid,
                    "status": status,
                }
            )
            continue
        # Forbid inventing source/target
        if any(k in payload for k in ("source", "target", "relation_type", "source_ids", "target_ids")):
            if payload.get("source_ids") or payload.get("target_ids") or payload.get("source"):
                rejected.append(
                    {
                        "reason": "禁止 LLM 输出 source/target/relation",
                        "candidate_edge_id": cid,
                    }
                )
                continue
        cand = by_id[cid]
        if status == "confirmed":
            if not cand.get("proposed_type"):
                rejected.append(
                    {
                        "reason": "该候选不可确认（无 proposed_type）",
                        "candidate_edge_id": cid,
                    }
                )
                continue
            accepted_edges.append(
                {
                    "id": cid,
                    "type": cand["proposed_type"],
                    "source_ids": list(cand.get("source_ids") or []),
                    "target_ids": list(cand.get("target_ids") or []),
                    "origin": "llm_confirmed",
                    "evidence_refs": list(payload.get("evidence_refs") or cand.get("evidence_refs") or []),
                    "confidence": "llm_confirmed",
                }
            )
        cand["status"] = status
        cand["llm_reason_code"] = payload.get("reason_code")
    return accepted_edges, rejected


def finalize_host_contract_gaps(
    repo_root: Path,
    op_name: str,
    *,
    uo_root: Path | None = None,
    run_dir: Path | None = None,
    decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Finalize：合并裁决到 tiling_contract_graph，禁止重扫源码。"""
    t0 = time.perf_counter()
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    work = run_dir or ir_dir
    gaps = read_yaml(work / "host_contract_gaps.yaml") or {}
    candidates = list(gaps.get("candidates") or [])
    if decisions is None:
        # load decision parts
        decisions = []
        parts_dir = work / "gap_decision_parts"
        if parts_dir.is_dir():
            for part in sorted(parts_dir.glob("*.yaml")):
                doc = read_yaml(part) or {}
                if isinstance(doc.get("decisions"), list):
                    decisions.extend(doc["decisions"])
                elif doc:
                    decisions.append(doc)
    accepted, rejected = apply_gap_decisions(decisions, candidates)

    tcg = load_tiling_contract(root)
    if accepted:
        edges = list(tcg.get("edges") or [])
        edge_ids = {e.get("id") for e in edges}
        for edge in accepted:
            if edge["id"] not in edge_ids:
                edges.append(edge)
                edge_ids.add(edge["id"])
        tcg["edges"] = edges
    tcg["gap_resolution"] = {
        "accepted": len(accepted),
        "rejected_decisions": rejected,
        "candidates": candidates,
    }
    write_yaml(ir_dir / "tiling_contract_graph.yaml", tcg)
    gaps["phase"] = "finalize"
    gaps["accepted_edges"] = accepted
    gaps["rejected_decisions"] = rejected
    gaps["timing_ms"] = int((time.perf_counter() - t0) * 1000)
    write_yaml(work / "host_contract_gaps.yaml", gaps)
    return gaps
