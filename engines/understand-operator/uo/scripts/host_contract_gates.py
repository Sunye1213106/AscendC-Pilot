"""Host Configuration / Tiling Contract 专属 integrity gate。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.host_contract_schema import BINDING_TIMES, CONFIGURATION_ROOT_KINDS


def check_host_configuration_integrity(hcg: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    ccid = str(hcg.get("compile_context_id") or "")
    entities = [e for e in (hcg.get("entities") or []) if isinstance(e, dict)]
    edges = [e for e in (hcg.get("edges") or []) if isinstance(e, dict)]

    root_ids = {
        e["id"]
        for e in entities
        if e.get("kind") in CONFIGURATION_ROOT_KINDS or e.get("root_class") == "ConfigurationRoot"
    }

    for ent in entities:
        if ccid and ent.get("compile_context_id") and ent.get("compile_context_id") != ccid:
            errors.append(
                {
                    "code": "CROSS_COMPILE_CONTEXT",
                    "entity_id": ent.get("id"),
                    "message": "实体 compile_context_id 与图不一致",
                }
            )
        if ent.get("kind") in {"HostValue", "HostDerivedValue"}:
            if not ent.get("definition_site") and not (
                isinstance(ent.get("definition_site"), dict)
            ):
                # may be nested — check
                if "definition_site" not in ent:
                    errors.append(
                        {
                            "code": "MISSING_DEFINITION_SITE",
                            "entity_id": ent.get("id"),
                            "message": "HostValue 缺少 definition_site",
                        }
                    )
            bt = ent.get("binding_time")
            if bt and bt not in BINDING_TIMES:
                errors.append(
                    {
                        "code": "BAD_BINDING_TIME",
                        "entity_id": ent.get("id"),
                        "message": f"非法 binding_time: {bt}",
                    }
                )
        if ent.get("kind") in {"HostPredicate", "CompilePredicate"}:
            if not ent.get("binding_time"):
                errors.append(
                    {
                        "code": "MISSING_BINDING_TIME",
                        "entity_id": ent.get("id"),
                        "message": "条件节点缺少 binding_time",
                    }
                )

    for edge in edges:
        if edge.get("type") == "DERIVES":
            # expression_ir on edge.transform or sources
            has_expr = bool(edge.get("transform")) or bool(edge.get("expression_ir"))
            if not has_expr:
                # check source entities
                src_ok = False
                by_id = {e["id"]: e for e in entities if e.get("id")}
                for sid in edge.get("source_ids") or []:
                    src = by_id.get(sid) or {}
                    if src.get("expression_ir"):
                        src_ok = True
                if not src_ok and edge.get("source_ids"):
                    warnings.append(
                        {
                            "code": "DERIVES_WITHOUT_EXPRESSION_IR",
                            "edge_id": edge.get("id"),
                            "message": "DERIVES 边缺少 expression_ir",
                        }
                    )

    for un in hcg.get("unresolved") or []:
        if not un.get("reason_code"):
            errors.append({"code": "UNRESOLVED_WITHOUT_REASON", "item": un})

    return {
        "gate": "host_configuration_integrity",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "root_count": len(root_ids),
    }


def check_tiling_contract_integrity(tcg: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    entities = [e for e in (tcg.get("entities") or []) if isinstance(e, dict)]
    ccid = str(tcg.get("compile_context_id") or "")

    if tcg.get("contract_status") not in {
        "producer_only",
        "consumer_only",
        "matched",
        "conflicted",
        None,
        "",
    }:
        errors.append(
            {
                "code": "BAD_CONTRACT_STATUS",
                "message": f"非法 contract_status: {tcg.get('contract_status')}",
            }
        )

    # Must not treat producer_only as matched bridge
    if tcg.get("contract_status") == "producer_only" and tcg.get("kb_status") == "complete":
        errors.append(
            {
                "code": "FALSE_COMPLETE_KB",
                "message": "producer_only 不得标记 kb_status=complete",
            }
        )

    for ent in entities:
        if ccid and ent.get("compile_context_id") and ent.get("compile_context_id") != ccid:
            errors.append(
                {
                    "code": "CROSS_COMPILE_CONTEXT",
                    "entity_id": ent.get("id"),
                }
            )
        if ent.get("kind") == "FieldWrite":
            rhs = ent.get("rhs_expression_ir")
            if not rhs:
                # check unresolved covering this write
                covered = any(
                    u.get("reason_code")
                    for u in (tcg.get("unresolved") or [])
                    if ent.get("id") in str(u)
                )
                if not covered and not ent.get("unresolved"):
                    warnings.append(
                        {
                            "code": "FIELD_WRITE_WITHOUT_RHS",
                            "entity_id": ent.get("id"),
                        }
                    )
        if ent.get("kind") == "Receiver" and ent.get("canonical") is False:
            errors.append(
                {
                    "code": "PLACEHOLDER_RECEIVER",
                    "entity_id": ent.get("id"),
                    "message": "禁止 placeholder receiver binding",
                }
            )
        if ent.get("kind") == "HostContractEndpoint":
            if ent.get("contract_status") == "producer_only" and ent.get("consumer"):
                warnings.append(
                    {
                        "code": "PRODUCER_ONLY_WITH_CONSUMER",
                        "entity_id": ent.get("id"),
                    }
                )

    dims = (tcg.get("declared_key_space") or {}).get("dimensions") or []
    ords = [d.get("ordinal") for d in dims]
    if ords and ords != list(range(len(ords))):
        errors.append(
            {
                "code": "KEY_ORDINAL_NOT_CONTIGUOUS",
                "message": "dimension ordinal 必须唯一连续",
            }
        )

    for un in tcg.get("unresolved") or []:
        if not un.get("reason_code"):
            errors.append({"code": "UNRESOLVED_WITHOUT_REASON", "item": un})

    return {
        "gate": "tiling_contract_integrity",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "contract_status": tcg.get("contract_status"),
        "kb_status": tcg.get("kb_status"),
    }


def run_host_contract_gates(
    repo_root: Path,
    op_name: str,
    *,
    uo_root: Path | None = None,
) -> dict[str, Any]:
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    hcg = read_yaml(root / "ir" / "host_configuration_graph.yaml") or {}
    tcg = read_yaml(root / "ir" / "tiling_contract_graph.yaml") or {}
    host_gate = check_host_configuration_integrity(hcg)
    tiling_gate = check_tiling_contract_integrity(tcg)
    report = {
        "ok": host_gate["ok"] and tiling_gate["ok"],
        "host_configuration_integrity": host_gate,
        "tiling_contract_integrity": tiling_gate,
    }
    checks = root / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    write_yaml(checks / "host_configuration_integrity.yaml", host_gate)
    write_yaml(checks / "tiling_contract_integrity.yaml", tiling_gate)
    write_yaml(checks / "host_contract_gates.yaml", report)
    return report
