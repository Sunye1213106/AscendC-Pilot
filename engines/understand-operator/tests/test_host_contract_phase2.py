"""阶段2：Host Configuration Graph 单测。"""
from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.ascendc_macro_facts import extract_macro_facts
from uo.scripts.host_compile_context import extract_host_compile_context
from uo.scripts.host_configuration_builder import (
    build_configuration_roots,
    build_host_configuration,
    summarize_function,
)


def test_configuration_roots_from_boundary():
    boundary = {
        "inputs": [
            {"name": "query", "index": 0},
            {"name": "pse", "index": 3, "optional": True},
        ],
        "attributes": [{"name": "input_layout"}],
    }
    roots = build_configuration_roots(boundary, compile_context_id="cc", architecture="arch35")
    kinds = {r["kind"] for r in roots}
    assert "OperatorInputRoot" in kinds
    assert "OptionalInputRoot" in kinds
    assert "OperatorAttributeRoot" in kinds
    assert "PlatformRoot" in kinds
    assert "ShapeRoot" in kinds
    assert all(r.get("compile_context_id") == "cc" for r in roots)


def test_function_summary_reads_attr_and_shape():
    body = """
    auto layout = context->GetAttr("input_layout");
    auto shape = context->GetInputShape(0);
    this->s1_ = shape->GetDim(1);
    if (layout == "TND") {
        this->isTnd_ = true;
    }
    return ge::GRAPH_SUCCESS;
"""
    summary = summarize_function(
        function_name="DoTiling",
        body=body,
        file_path="op_host/t.cpp",
        start_line=10,
        params=["gert::TilingContext *context"],
        compile_context_id="cc",
        architecture="arch35",
    )
    kinds = {v["kind"] for v in summary["values"]}
    assert "HostValue" in kinds
    assert "HostPredicate" in kinds or any(
        v.get("kind") == "HostPredicate" for v in summary["values"]
    )
    assert summary["member_writes"]


def test_build_host_configuration_end_to_end(tmp_path: Path):
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_host" / "tiling.cpp").write_text(
        """
#include "reg.h"
ge::graphStatus DoTiling(gert::TilingContext *context) {
    auto layout = context->GetAttr("input_layout");
    auto qShape = context->GetInputShape(0);
    uint32_t s1 = qShape->GetDim(1);
    auto *platform = context->GetPlatformInfo();
    uint32_t aivNum = platform->GetCoreNumAiv();
    if (layout == "TND") {
        s1 = s1 + 1;
    }
    return ge::GRAPH_SUCCESS;
}
""",
        encoding="utf-8",
    )
    uo = repo / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(
        uo / "ir" / "operator_boundary.yaml",
        {
            "inputs": [{"name": "query", "index": 0}],
            "attributes": [{"name": "input_layout"}],
        },
    )
    write_yaml(
        uo / "ir" / "entrypoint_graph.yaml",
        {
            "nodes": [],
            "edges": [{"type": "binds_tiling", "source": "impl", "target": "DoTiling"}],
        },
    )
    extract_macro_facts(repo, "Demo", uo_root=uo)
    extract_host_compile_context(repo, "Demo", uo_root=uo)
    hcg = build_host_configuration(repo, "Demo", uo_root=uo)
    assert hcg["compile_context_id"]
    kinds = {e["kind"] for e in hcg["entities"]}
    assert "OperatorInputRoot" in kinds
    assert "HostFunction" in kinds
    assert "HostValue" in kinds
    assert hcg["function_summaries"]
    # DERIVES/READS edges exist
    types = {e["type"] for e in hcg["edges"]}
    assert "READS_INPUT" in types or "READS_PLATFORM" in types
