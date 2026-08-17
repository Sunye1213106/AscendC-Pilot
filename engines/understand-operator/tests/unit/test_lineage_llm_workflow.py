# -*- coding: utf-8 -*-
from uo_init.lineage import (
    LEGAL_ROOTS,
    mark_input_value_deps,
    run_gates,
    terminate,
    tnd_unroll,
    tpl_vs_host_diff,
)
from uo_init.operator_report import run_operator_report


def test_lineage_terminates_in_legal_root():
    L = terminate("ATTRIBUTE", "n1")
    assert L.root_kind in LEGAL_ROOTS


def test_input_value_marked():
    # TilingInputsDataDependency({12,13,14,15,16}) style
    names = [f"in{i}" for i in range(20)]
    m = mark_input_value_deps([12, 13, 14, 15, 16], names)
    assert all(v.startswith("INPUT_VALUE:") for v in m.values())


def test_tpl_vs_host_diff_empty_or_reported():
    d = tpl_vs_host_diff({(1, 2), (3, 4)}, {(1, 2), (5, 6)})
    assert d["declared_unreachable"] == [(3, 4)]
    assert d["reachable_undeclared"] == [(5, 6)]


def test_tnd_bounded_unroll():
    assert tnd_unroll(3) == [
        "actual_seq_qlen[0]",
        "actual_seq_qlen[1]",
        "actual_seq_qlen[2]",
    ]


def test_gates_emit_reason_codes():
    from uo_init.lineage import Lineage

    rep = run_gates(
        lineages=[
            terminate("CONSTANT", "a"),
            Lineage("b", "UNKNOWN", "", reason_code="OPEN"),
        ],
        template_ok=1,
        schema_ok=True,
    )
    assert rep.reasons
    assert "OPEN" in rep.reasons[0]


def test_coverage_baseline_row(fag_dir):
    from uo_init.registry_capable import build_arch35_competition

    c = build_arch35_competition(fag_dir / "op_host", op_name="FlashAttentionScoreGrad")
    # same_as_input=1 => tnd_softmax_in=TND => Normal false
    pred = c.preds[c.ordered[1]["class"]]
    assert pred.eval_arch35({"npu_arch": "DAV_3510", "tnd_softmax_in": "TND"}) is False


def test_e2e_report_nonempty(fag_dir):
    rep = run_operator_report(op_dir=str(fag_dir))
    assert rep["tpl_dims"] == 19
    assert rep["anchors_inputs"] == 27
    assert "deterministic_closure" in rep
    assert isinstance(rep["open_reasons"], list)
    assert rep["registry_order"]
