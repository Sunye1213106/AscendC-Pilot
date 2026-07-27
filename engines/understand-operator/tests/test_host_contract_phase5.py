"""阶段5：gaps 裁决 / gates / 物化视图 / 删 plan 仍可重建。"""
from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.host_contract_gates import run_host_contract_gates
from uo.scripts.host_contract_pipeline import run_host_contract_pipeline
from uo.scripts.materialize_extract_plan_view import materialize_extract_plan_view
from uo.scripts.resolve_host_contract_gaps import apply_gap_decisions, generate_candidate_edges


def _mini_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "op"
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_host" / "t.cpp").write_text(
        """
REG_OP(DemoOp);
IMPL_OP_OPTILING(DemoOp).Tiling(DoTiling);
ASCENDC_TPL_BOOL_DECL(IsTnd, 0, 1);
BEGIN_TILING_DATA_DEF(DemoTD)
TILING_DATA_FIELD_DEF(uint32_t, s1);
END_TILING_DATA_DEF
ge::graphStatus DoTiling(gert::TilingContext *context) {
    auto layout = context->GetAttr("input_layout");
    auto *root = context->GetTilingData<DemoTD>();
    auto *td = &root->base;
    uint32_t s1 = context->GetInputShape(0)->GetDim(1);
    td->set_s1(s1);
    auto key = GET_TPL_TILING_KEY(isTnd);
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
            "nodes": [
                {
                    "id": "N_IMPL",
                    "macro": "IMPL_OP_OPTILING",
                    "locator": {"file_path": "op_host/t.cpp", "start_line": 3},
                }
            ],
            "edges": [{"type": "binds_tiling", "source": "N_IMPL", "target": "DoTiling"}],
        },
    )
    return repo, uo


def test_pipeline_and_delete_plan_rebuild(tmp_path: Path):
    repo, uo = _mini_repo(tmp_path)
    result = run_host_contract_pipeline(repo, "Demo", uo_root=uo, gap_decisions=[])
    assert result["kb_status"] == "partial"
    assert result["build_profile"] == "host_contract_only"
    assert (uo / "ir" / "host_configuration_graph.yaml").is_file()
    assert (uo / "ir" / "tiling_contract_graph.yaml").is_file()
    assert (uo / "ir" / "extract_plan.yaml").is_file()
    plan = read_yaml(uo / "ir" / "extract_plan.yaml")
    assert plan.get("materialized_view") is True
    assert plan.get("authoritative") is False

    # 删除 extract_plan 后 HCG/TCG 仍在；可重新物化
    (uo / "ir" / "extract_plan.yaml").unlink()
    assert not (uo / "ir" / "extract_plan.yaml").is_file()
    assert (uo / "ir" / "host_configuration_graph.yaml").is_file()
    materialize_extract_plan_view(repo, "Demo", uo_root=uo)
    assert (uo / "ir" / "extract_plan.yaml").is_file()

    gates = run_host_contract_gates(repo, "Demo", uo_root=uo)
    assert (uo / "checks" / "host_configuration_integrity.yaml").is_file()
    assert (uo / "checks" / "tiling_contract_integrity.yaml").is_file()
    assert gates["tiling_contract_integrity"]["contract_status"] == "producer_only"


def test_llm_cannot_invent_edges():
    candidates = [
        {
            "candidate_edge_id": "CAND_1",
            "proposed_type": "DERIVES",
            "source_ids": ["a"],
            "target_ids": ["b"],
            "allowed_entities": ["a", "b"],
            "allowed_edges": ["CAND_1"],
            "status": "pending",
        }
    ]
    accepted, rejected = apply_gap_decisions(
        [
            {
                "decision": {
                    "candidate_edge_id": "CAND_FAKE",
                    "status": "confirmed",
                }
            }
        ],
        candidates,
    )
    assert not accepted
    assert rejected

    accepted2, rejected2 = apply_gap_decisions(
        [
            {
                "decision": {
                    "candidate_edge_id": "CAND_1",
                    "status": "confirmed",
                    "source_ids": ["hack"],
                }
            }
        ],
        candidates,
    )
    assert not accepted2
    assert rejected2

    accepted3, rejected3 = apply_gap_decisions(
        [{"decision": {"candidate_edge_id": "CAND_1", "status": "confirmed"}}],
        candidates,
    )
    assert len(accepted3) == 1
    assert not rejected3


def test_no_operator_name_hardcode_in_new_modules():
    root = Path(__file__).resolve().parents[1] / "uo" / "scripts"
    forbidden = (
        "FlashAttentionScoreGrad",
        "RegbaseFAG",
        "flash_attention_score_grad",
    )
    files = [
        "host_contract_schema.py",
        "ascendc_macro_facts.py",
        "host_configuration_builder.py",
        "tiling_contract_builder.py",
        "tiling_key_declaration.py",
        "tiling_key_composition.py",
        "host_contract_pipeline.py",
    ]
    for name in files:
        text = (root / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{name} 含算子名硬编码 {token}"
