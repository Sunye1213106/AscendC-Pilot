"""detect_score_pre must materialize entrypoint_graph before scoring."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS, invoke_engine
from ascendc_pilot.actions.runtime import _check_output_contract
from ascendc_pilot.paths import ensure_agent_layout


def _prep_minimal_op(tmp_path: Path, op_name: str = "DemoPreScore") -> Path:
    root = tmp_path / op_name
    root.mkdir()
    ensure_agent_layout(root)
    uo = root / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    (uo / "manifest.yaml").write_text(f"op_name: {op_name}\ncurrent_run_id: UO_RUN_TEST\n", encoding="utf-8")
    run = uo / "runs" / "UO_RUN_TEST" / "scope"
    run.mkdir(parents=True)
    # Minimal host/kernel sources so resolve_entrypoints can at least run
    (root / "op_host").mkdir()
    (root / "op_kernel").mkdir()
    (root / "op_host" / "demo_tiling.cpp").write_text(
        "namespace optiling {\n"
        "ge::graphStatus DemoPreScoreTiling(gert::TilingContext* context) { return ge::GRAPH_SUCCESS; }\n"
        "IMPL_OP_OPTILING(DemoPreScore).Tiling(DemoPreScoreTiling);\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "op_host" / "demo_def.cpp").write_text(
        "REG_OP(DemoPreScore)\n"
        "    .OpType(\"DemoPreScore\")\n"
        "    .End();\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "demo_kernel.cpp").write_text(
        "extern \"C\" __global__ __aicore__ void demo_pre_score_kernel() {}\n",
        encoding="utf-8",
    )
    (run / "scope_confirmed.yaml").write_text(
        "confirmed_file_list:\n"
        "- path: op_host/demo_tiling.cpp\n"
        "- path: op_host/demo_def.cpp\n"
        "- path: op_kernel/demo_kernel.cpp\n"
        "confirmed_source_files:\n"
        "- path: op_host/demo_tiling.cpp\n"
        "- path: op_host/demo_def.cpp\n"
        "- path: op_kernel/demo_kernel.cpp\n",
        encoding="utf-8",
    )
    return root


def test_detect_score_pre_writes_entrypoint_graph(tmp_path: Path) -> None:
    root = _prep_minimal_op(tmp_path)
    ep = root / ".ascendc-pilot" / "uo" / "ir" / "entrypoint_graph.yaml"
    assert not ep.is_file()

    result = invoke_engine(
        root,
        "uo-init",
        "detect_score_pre",
        ctx={"op_name": "DemoPreScore", "architecture": "arch35", "run_id": "UO_RUN_TEST"},
    )
    assert result.get("ok") is True, result
    assert ep.is_file(), "detect_score_pre must create ir/entrypoint_graph.yaml"
    assert (root / ".ascendc-pilot" / "uo" / "ir" / "score_report_pre.yaml").is_file()
    assert (root / ".ascendc-pilot" / "uo" / "ir" / "llm_tasks.yaml").is_file()

    checked = _check_output_contract(root, "detect-score-pre-v1")
    assert checked.get("ok") is True, checked


def test_detect_score_pre_contract_includes_graph() -> None:
    paths = OUTPUT_CONTRACT_PATHS["detect-score-pre-v1"]
    assert "uo/ir/entrypoint_graph.yaml" in paths
    assert "uo/ir/score_report_pre.yaml" in paths
    assert "uo/ir/host_subgraph.yaml" in OUTPUT_CONTRACT_PATHS["extract-plan-v1"]
    assert "uo/ir/kernel_subgraph.yaml" in OUTPUT_CONTRACT_PATHS["extract-plan-v1"]
    assert "uo/ir/macro_semantics.yaml" in OUTPUT_CONTRACT_PATHS["extract-plan-v1"]
    assert "uo/ir/semantic_task_triage.yaml" in OUTPUT_CONTRACT_PATHS["detect-score-post-v1"]
