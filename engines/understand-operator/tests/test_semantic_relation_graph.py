"""Input-rooted Relation Graph tests (FAG-shaped patterns, no FAG hardcode in rules)."""
from __future__ import annotations

from uo.scripts.relation_evidence import validate_relation_evidence
from uo.scripts.semantic_graph_builder import (
    close_deterministic_relations,
    validate_input_root_grounding,
)
from uo.scripts.semantic_impact import impact_from_change_set
from uo.scripts.semantic_materializer import materialize_from_relations
from uo.scripts.semantic_obligations import build_semantic_obligations
from uo.scripts.semantic_observations import build_observations_from_candidates, observe_text
from uo.scripts.semantic_pipeline import build_relation_artifacts
from uo.scripts.semantic_relations import index_relations_by_type


def test_common_assign_observes_binds_not_writes() -> None:
    text = """
    #define TND_TILING_DATA_COMMON_ASSIGN(tilingData) \\
        do { \\
            s1s2BNGS1S2BaseParams_ = &tilingData->s1s2BNGS1S2BaseParams; \\
        } while (0)
    TND_TILING_DATA_COMMON_ASSIGN(tilingData);
    """
    obs = observe_text(text, function="TND_TILING_DATA_COMMON_ASSIGN")
    types = {o["type"] for o in obs}
    assert "common_assign_macro" in types
    assert "address_of_nested_member" in types
    # Must not claim writes from macro alone
    assert validate_relation_evidence("WRITES", text=text)["supported"] is False
    assert validate_relation_evidence("BINDS", text=text)["supported"] is True


def test_get_tiling_data_alone_not_writes() -> None:
    text = "FagTilingWithTemplateFFFF *tilingData = this->context_->GetTilingData<FagTilingWithTemplateFFFF>();"
    r = validate_relation_evidence("WRITES", text=text)
    assert r["supported"] is False
    assert r["reason_code"] == "get_tiling_data_not_writes"


def test_setter_is_writes_not_binds() -> None:
    text = "s1s2BNGS1S2BaseParams_->set_coreNum(fBaseParams.coreNum);"
    assert validate_relation_evidence("WRITES", text=text)["supported"] is True
    assert validate_relation_evidence("BINDS", text=text)["supported"] is False
    assert validate_relation_evidence("BINDS", text=text)["reason_code"] == "setter_cannot_prove_binds"


def test_recv_addr_binds() -> None:
    text = "s1s2BNGS1S2BaseParams_ = &tilingData->s1s2BNGS1S2BaseParams;"
    assert validate_relation_evidence("BINDS", text=text)["supported"] is True


def test_get_tiling_key_composes() -> None:
    text = "uint64_t tilingKey = GET_TPL_TILING_KEY(0, splitAxis, dtype); return tilingKey;"
    assert validate_relation_evidence("COMPOSES_KEY", text=text)["supported"] is True


def test_alias_vs_derive() -> None:
    eq = "qPreBlockFactor = tilingData->preTilingData.qPreBlockFactor;"
    der = "local_block_count = ceil_div(s1, blockFactor);"
    assert validate_relation_evidence("EQUIVALENT_TO", text=eq)["supported"] is True
    assert validate_relation_evidence("EQUIVALENT_TO", text=der)["supported"] is False
    assert validate_relation_evidence("DERIVES", text=der)["supported"] is True


def test_unknown_relation_fail_closed() -> None:
    r = validate_relation_evidence("TILING_WRITER", text="set_x(1);")
    assert r["supported"] is False
    assert r["reason_code"] == "unknown_relation_unsupported"


def test_pipeline_materializes_bindings_writers_key_conditions() -> None:
    candidates = {
        "architecture": "arch35",
        "writer_candidates": [
            {
                "candidate_id": "CAND_init",
                "name": "InitTilingData",
                "file_path": "op_host/x.cpp",
                "start_line": 10,
                "source_window": {
                    "text": (
                        "FagTilingWithTemplateFFFF *tilingData = "
                        "this->context_->GetTilingData<FagTilingWithTemplateFFFF>();\n"
                        "BASE_TILING_DATA_COMMON_ASSIGN(tilingData);\n"
                        "s1s2BNGS1S2BaseParams_ = &tilingData->s1s2BNGS1S2BaseParams;\n"
                        "if (layoutType == INPUT_FORMAT_TND) { }\n"
                        "if (isDeterministic) { }\n"
                    ),
                    "sha256": "a" * 64,
                },
            },
            {
                "candidate_id": "CAND_save",
                "name": "SaveToTilingData",
                "file_path": "op_host/x.cpp",
                "start_line": 40,
                "source_window": {
                    "text": "s1s2BNGS1S2BaseParams_->set_coreNum(fBaseParams.coreNum);\n"
                    "s1s2BNGS1S2BaseParams_->set_b(fBaseParams.b);\n",
                    "sha256": "b" * 64,
                },
            },
            {
                "candidate_id": "CAND_key",
                "name": "GetTilingKey",
                "file_path": "op_host/x.cpp",
                "start_line": 80,
                "source_window": {
                    "text": (
                        "uint64_t tilingKey = GET_TPL_TILING_KEY(0, splitAxis, "
                        "fBaseParams.inputDtype, isTnd);\n"
                        "return tilingKey;\n"
                    ),
                    "sha256": "c" * 64,
                },
            },
        ],
        "alias_candidates": [
            {
                "candidate_id": "CAND_alias",
                "local": "qPreBlockFactor",
                "tdf_leaf": "qPreBlockFactor",
                "tdf_path": "preTilingData.qPreBlockFactor",
                "file_path": "op_kernel/x.h",
                "start_line": 5,
                "source_window": {
                    "text": "qPreBlockFactor = tilingData->preTilingData.qPreBlockFactor;",
                    "sha256": "d" * 64,
                },
            }
        ],
        "receiver_binding_candidates": [],
        "receiver_candidates": [],
    }
    art = build_relation_artifacts(candidates)
    graph = art["graph"]
    plan = art["plan"]
    by_type = index_relations_by_type(graph)

    assert by_type["BINDS"], "expected BINDS from COMMON_ASSIGN / addr assign"
    assert by_type["WRITES"], "expected WRITES from setters"
    assert by_type["COMPOSES_KEY"], "expected COMPOSES_KEY from GetTilingKey"
    assert by_type["GUARDS"], "expected GUARDS from layout/deter conditions"
    assert by_type["GROUNDED_IN"], "expected GROUNDED_IN to input roots"
    assert graph.get("input_roots"), "input_roots must exist"

    # Roots are only input_root kind
    for eid in graph["input_roots"]:
        assert str(eid).startswith("input_root:")

    # Materialized surfaces
    assert any(b.get("receiver") == "s1s2BNGS1S2BaseParams_" for b in plan["receiver_bindings"])
    assert any(w.get("role") == "tiling_writer" and w.get("name") == "SaveToTilingData" for w in plan["writers"])
    assert any(w.get("role") == "key_writer" and w.get("name") == "GetTilingKey" for w in plan["writers"])
    assert plan.get("condition_nodes") or plan.get("groundings")
    assert any(a.get("local") == "qPreBlockFactor" for a in plan["aliases"])

    # COMMON_ASSIGN function must not become tiling_writer solely from binds
    bind_only_writers = [
        w for w in plan["writers"] if w.get("name") == "InitTilingData" and w.get("role") == "tiling_writer"
    ]
    assert not bind_only_writers

    errs = validate_input_root_grounding(graph)
    # Conditions/templates should be grounded; allow empty errors
    hard = [e for e in errs if "condition:" in e or "template:" in e or "key_dimension:" in e]
    assert not hard, hard


def test_given_inputs_derive_template_and_guards() -> None:
    """Acceptance: layout/deter inputs ground templates and conditions."""
    obs = build_observations_from_candidates(
        {
            "writer_candidates": [
                {
                    "candidate_id": "CAND_1",
                    "name": "InitTilingData",
                    "source_window": {
                        "text": (
                            "if (layoutType == INPUT_FORMAT_TND) {\n"
                            "  auto *td = context_->GetTilingData<TilingWithTemplateTFTF>();\n"
                            "}\n"
                            "if (isDeterministic) { }\n"
                        )
                    },
                }
            ]
        }
    )
    obl = build_semantic_obligations(obs)
    graph = close_deterministic_relations(obs, obl)
    plan = materialize_from_relations(graph)
    assert plan["input_roots"]
    grounded_syms = {
        str(g.get("input_root") or "").split(":")[-1] for g in plan.get("groundings") or []
    }
    assert "layout" in grounded_syms or any(
        r.get("symbol") == "layout" for r in plan["input_roots"]
    )
    assert plan.get("template_nodes") or index_relations_by_type(graph).get("SELECTS_TEMPLATE")


def test_impact_lists_fields_keys_and_input_roots() -> None:
    candidates = {
        "writer_candidates": [
            {
                "candidate_id": "CAND_save",
                "name": "SaveToTilingData",
                "source_window": {
                    "text": "baseParams_->set_s1(s1);\n",
                },
            },
            {
                "candidate_id": "CAND_key",
                "name": "GetTilingKey",
                "source_window": {
                    "text": "uint64_t key = GET_TPL_TILING_KEY(0, dtype); return key;\n",
                },
            },
        ]
    }
    art = build_relation_artifacts(candidates)
    impact = impact_from_change_set(
        art["graph"],
        touched_symbols=["SaveToTilingData", "GetTilingKey"],
    )
    assert impact["seed_count"] >= 1
    assert impact["affected_tiling_fields"] or impact["affected_key_dimensions"]
    assert impact["dependent_input_roots"] or impact["coverage_obligations"]
    # coverage obligations must carry input_root when present
    for obl in impact.get("coverage_obligations") or []:
        assert obl.get("input_root")
