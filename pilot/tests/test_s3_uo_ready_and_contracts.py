"""S3: TG/CE must not write .uo; contracts and named gates stay aligned."""

from __future__ import annotations

import inspect
from pathlib import Path

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
from ascendc_pilot.gates import gate_uo_ready_tg, run_named_gate
import ascendc_pilot.gates as gates
from uo_init.ir.codemap import CodeMap
from uo_init.store.writer import write_codemap


def test_named_gate_uo_ready_is_tg_not_sqlite() -> None:
    assert not hasattr(gates, "gate_uo_ready")
    assert hasattr(gates, "gate_uo_ready_tg")
    sig = inspect.signature(gate_uo_ready_tg)
    assert "architecture" in sig.parameters
    named = inspect.signature(run_named_gate)
    assert "architecture" in named.parameters


def test_ce_plan_contract_is_named_markdown() -> None:
    assert OUTPUT_CONTRACT_PATHS["ce-plan-v1"] == ["ce/plan/*_plan.md"]
    assert OUTPUT_CONTRACT_PATHS["session-handoff-v1"] == ["session_handoff.md"]
    assert "intent-confirmed-v1" not in OUTPUT_CONTRACT_PATHS
    assert "plan-review-v1" not in OUTPUT_CONTRACT_PATHS
    for cid, paths in OUTPUT_CONTRACT_PATHS.items():
        for path in paths:
            p = str(path).replace("\\", "/")
            if p.startswith("ce/"):
                assert not p.endswith(".yaml"), (cid, path)


def test_ce_yaml_products_have_no_writers() -> None:
    from ascendc_pilot.ownership import ACTION_PRODUCER_WRITE_PATHS, ACTION_WRITE_PATHS

    banned = (
        "feature_decomposition.yaml",
        "scenario_set.yaml",
        "tg_plan_intent.yaml",
        "plan_review.yaml",
        "ledger.yaml",
        "confirmation.yaml",
    )
    writers = [
        (wid, aid, path)
        for wid, actions in ACTION_WRITE_PATHS.items()
        for aid, paths in actions.items()
        for path in paths
        if any(token in str(path) for token in banned)
    ]
    assert writers == []
    staged = [
        (wid, aid, path)
        for wid, actions in ACTION_PRODUCER_WRITE_PATHS.items()
        for aid, paths in actions.items()
        for path in paths
        if any(token in str(path) for token in banned)
    ]
    assert staged == []


def test_kb_ready_uses_requested_architecture(tmp_path: Path) -> None:
    from synthetic_uo import write_synthetic_uo

    incomplete = CodeMap(op_name="toy", architecture="arch22")
    write_codemap(
        incomplete,
        tmp_path / ".ascendc-pilot" / "arch22" / "uo" / "toy.arch22.uo",
    )
    write_synthetic_uo(tmp_path, op_name="toy", architecture="arch35")

    ready_35 = run_named_gate(
        tmp_path, "kb_ready", op_name="toy", architecture="arch35"
    )
    ready_22 = run_named_gate(
        tmp_path, "kb_ready", op_name="toy", architecture="arch22"
    )
    assert ready_35.get("ok") is True, ready_35
    assert ready_22.get("ok") is False, ready_22
    assert "/uo-init" in str(ready_22.get("message") or ready_22)


def test_generate_reference_docs_engine_cli_and_artifact_tree() -> None:
    import sys

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "scripts"))
    import generate_reference_docs as gen

    cli = gen.render_cli()
    assert "`tg-closure`" in cli
    assert "`tg-init`" not in cli
    assert "`tg-plan`" not in cli
    assert "`tg-solve`" not in cli
    artifacts = gen.render_artifacts()
    assert "<arch>/uo/<op>.<arch>.uo" in artifacts
    assert "uo/<op_name>.<arch>.uo" not in artifacts
