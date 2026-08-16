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


def test_init_confirmed_contract_includes_confirmation() -> None:
    paths = OUTPUT_CONTRACT_PATHS["init-confirmed-v1"]
    assert "tg/init/confirmation.yaml" in paths
    assert "tg/init/status.yaml" in paths
    assert "tg/init/kb_fingerprint.yaml" in paths


def test_plan_review_contract_is_only_plan_review_yaml() -> None:
    assert OUTPUT_CONTRACT_PATHS["plan-review-v1"] == ["ce/intent/plan_review.yaml"]


def test_plan_review_prompt_only_writes_plan_review_yaml() -> None:
    prompt = (
        Path(__file__).resolve().parents[2] / "prompts" / "tasks" / "ce" / "plan-review.md"
    ).read_text(encoding="utf-8")
    assert "ce/intent/plan_review.yaml" in prompt
    assert "写入 `ce/intent/feature_decomposition.yaml`" not in prompt
    assert "提升为 `ce/intent/feature_decomposition.yaml`" not in prompt


def test_feature_decomposition_unique_writer() -> None:
    from ascendc_pilot.ownership import ACTION_PRODUCER_WRITE_PATHS, ACTION_WRITE_PATHS

    writers = [
        (wid, aid)
        for wid, actions in ACTION_WRITE_PATHS.items()
        for aid, paths in actions.items()
        if any("feature_decomposition.yaml" in str(p) for p in paths)
    ]
    assert writers == [("ce-intent", "feature_promote")]
    staged = [
        (wid, aid)
        for wid, actions in ACTION_PRODUCER_WRITE_PATHS.items()
        for aid, paths in actions.items()
        if any("feature_decomposition.yaml" in str(p) for p in paths)
    ]
    assert staged == []


def test_scenario_set_not_written_by_knobs_producer() -> None:
    from ascendc_pilot.ownership import ACTION_PRODUCER_WRITE_PATHS, ACTION_WRITE_PATHS

    knobs_paths = (ACTION_PRODUCER_WRITE_PATHS.get("ce-impact") or {}).get("scenario_knobs") or []
    assert all("scenario_set.yaml" not in str(p) for p in knobs_paths)
    writers = {
        (wid, aid)
        for wid, actions in ACTION_WRITE_PATHS.items()
        for aid, paths in actions.items()
        if any(str(p).endswith("ce/scenarios/scenario_set.yaml") or str(p) == "ce/scenarios/scenario_set.yaml" for p in paths)
    }
    assert writers == {
        ("ce-impact", "scenario_infer"),
        ("ce-impact", "scenario_apply"),
        ("ce-intent", "scenario_infer"),
    }


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
