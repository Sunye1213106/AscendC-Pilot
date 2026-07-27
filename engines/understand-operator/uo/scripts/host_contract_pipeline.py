"""Host-only 合同抽取编排（测试与 host_contract_only profile）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts.ascendc_macro_facts import extract_macro_facts
from uo.scripts.host_compile_context import extract_host_compile_context
from uo.scripts.host_configuration_builder import build_host_configuration
from uo.scripts.host_contract_gates import run_host_contract_gates
from uo.scripts.macro_entrypoint_projection import project_macro_facts_to_entrypoint
from uo.scripts.materialize_extract_plan_view import materialize_extract_plan_view
from uo.scripts.resolve_host_contract_gaps import (
    finalize_host_contract_gaps,
    prepare_host_contract_gaps,
)
from uo.scripts.tiling_contract_builder import build_tiling_contract


def run_host_contract_pipeline(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
    materialize_view: bool = True,
    run_gaps: bool = True,
    gap_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """执行 Host 主链；不构建 Kernel，返回 partial KB 状态。"""
    from uo._operator.artifacts import existing_operator_root, operator_root

    root = uo_root or operator_root(repo_root, op_name)
    (root / "ir").mkdir(parents=True, exist_ok=True)

    facts = extract_macro_facts(
        repo_root, op_name, architecture=architecture, uo_root=root
    )
    # compile context needs macro_facts for registration — extract facts first without ccid then refresh
    ctx = extract_host_compile_context(
        repo_root, op_name, architecture=architecture, uo_root=root
    )
    # re-stamp macro facts with compile_context_id
    facts = extract_macro_facts(
        repo_root,
        op_name,
        architecture=architecture,
        uo_root=root,
        compile_context_id=str(ctx.get("compile_context_id") or ""),
    )
    proj = project_macro_facts_to_entrypoint(
        repo_root, op_name, architecture=architecture, uo_root=root, macro_facts=facts
    )
    hcg = build_host_configuration(
        repo_root, op_name, architecture=architecture, uo_root=root
    )
    tcg = build_tiling_contract(
        repo_root, op_name, architecture=architecture, uo_root=root
    )
    gaps = None
    if run_gaps:
        gaps = prepare_host_contract_gaps(repo_root, op_name, uo_root=root)
        if gap_decisions is not None or gaps.get("counts", {}).get("pending_llm", 0) == 0:
            gaps = finalize_host_contract_gaps(
                repo_root,
                op_name,
                uo_root=root,
                decisions=gap_decisions or [],
            )
    plan = None
    if materialize_view:
        plan = materialize_extract_plan_view(repo_root, op_name, uo_root=root)
    gates = run_host_contract_gates(repo_root, op_name, uo_root=root)

    return {
        "build_profile": "host_contract_only",
        "kb_status": "partial",
        "compile_context_id": ctx.get("compile_context_id"),
        "macro_facts": {"counts": facts.get("counts")},
        "entrypoint_projection": {
            "upgraded_nodes": proj.get("upgraded_nodes"),
            "emitted_edge_count": len(proj.get("emitted_edges") or []),
        },
        "host_configuration": {"counts": hcg.get("counts")},
        "tiling_contract": {
            "counts": tcg.get("counts"),
            "contract_status": tcg.get("contract_status"),
        },
        "gaps": gaps.get("counts") if isinstance(gaps, dict) else None,
        "extract_plan_view": plan.get("counts") if isinstance(plan, dict) else None,
        "gates": gates,
        "completed_capabilities": [
            "host_configuration",
            "tiling_contract_producer",
        ],
        "pending_capabilities": [
            "kernel_variant",
            "kernel_execution",
            "bridge_consumer",
        ],
    }
