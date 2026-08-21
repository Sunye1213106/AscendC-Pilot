"""Pilot TG engines write the three canonical products, not success markers."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS, invoke_engine
from ascendc_pilot.paths import ensure_agent_layout, tg_root, uo_root
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows.specs import WORKFLOWS

_ARCH = "arch35"


def _seed_manifest(root: Path) -> None:
    path = uo_root(root, arch=_ARCH) / "manifest.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("op_name: synth_tg\n", encoding="utf-8")


def test_validate_init_fails_without_init_yaml(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-init", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    result = invoke_engine(
        root,
        "tg-init",
        "validate_init",
        ctx={"op_name": "synth_tg", "architecture": _ARCH, "run_id": run_id},
    )
    assert result.get("ok") is False
    assert not (tg_root(root, arch=_ARCH) / "init.yaml").is_file()


def test_removed_legacy_actions_gone() -> None:
    ids = {a["id"] for a in WORKFLOWS["tg-init"]["actions"]} | {
        a["id"] for a in WORKFLOWS["tg-plan"]["actions"]
    } | {a["id"] for a in WORKFLOWS["tg-solve"]["actions"]}
    for dead in (
        "semantic_bind",
        "contract_build",
        "init_audit",
        "plan_intent",
        "plan_build",
        "lemma_mine",
        "closure_certify",
    ):
        assert dead not in ids


def test_output_contracts_are_three_products() -> None:
    assert OUTPUT_CONTRACT_PATHS["tg-init-v1"] == ["tg/init.yaml"]
    assert OUTPUT_CONTRACT_PATHS["tg-plan-v1"] == ["tg/plan.md"]
    assert OUTPUT_CONTRACT_PATHS["tg-worklog-v1"] == ["tg/worklog.md"]
    assert OUTPUT_CONTRACT_PATHS["tg-cases-v1"] == ["tg/cases.csv", "tg/cases.xls", "tg/cases.xlsx"]
    assert OUTPUT_CONTRACT_PATHS["plan-precheck-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["solve-precheck-v1"] == []
    assert "tilingkey-contract-v1" not in OUTPUT_CONTRACT_PATHS
    assert "lemma-mine-v1" not in OUTPUT_CONTRACT_PATHS


def test_tg_init_agents() -> None:
    agents = {a["id"] for a in WORKFLOWS["tg-init"]["agents"]}
    assert "tg-csv-contract" not in agents
    assert "tg-semantic-bind" not in agents
    assert "tg-analyst" in agents
    assert "deterministic-tg-engine" in agents


def test_start_persists_pilot_params(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    consumer = tmp_path / "scripts"
    consumer.mkdir()
    state = start_workflow(
        root,
        "tg-plan",
        op_name="synth_tg",
        test_script_root=consumer.as_posix(),
        level="L0",
        architecture="arch35",
    )
    assert state.get("op_name") == "synth_tg"
    assert Path(str(state.get("test_script_root") or "")).resolve() == consumer.resolve()
    from ascendc_pilot.context import build_context_pack

    pack = build_context_pack(root, intent="test", topic="plan")
    assert pack.get("op_name") == "synth_tg"
    assert Path(str(pack.get("test_script_root") or "")).resolve() == consumer.resolve()


_PLAN_BODY = """# why

```yaml
schema: tg-plan/v1
obligations:
- id: L0-dtype
  why: cover dtype
  class: derived
  control: {columns: [B], recipe: set dtype}
  hit: {pred: key}
  uo: {query: InputDType, span: "op_host/x.cpp:1"}
  cover: L0
```
"""


def test_plan_staging_contract_accepts_parts_plan_md(tmp_path: Path) -> None:
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_MATCH_ANY, OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import agent_root, ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    assert "tg-plan-staging-v1" in OUTPUT_CONTRACT_MATCH_ANY
    assert "staging.yaml" not in ",".join(OUTPUT_CONTRACT_PATHS["tg-plan-staging-v1"])
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    parts = agent_root(root, _ARCH) / "runs" / run_id / "actions" / "plan_fuse" / "parts"
    parts.mkdir(parents=True)
    (parts / "plan.md").write_text(_PLAN_BODY, encoding="utf-8")
    checked = _check_output_contract(
        root,
        "tg-plan-staging-v1",
        run_id=run_id,
        workflow_id="tg-plan",
        action_id="plan_fuse",
    )
    assert checked.get("ok") is True, checked
    out = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    assert (tg_root(root, arch=_ARCH) / "plan.md").read_text(encoding="utf-8") == _PLAN_BODY


def test_plan_staging_contract_accepts_legacy_staging_md(tmp_path: Path) -> None:
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import agent_root, ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    action = agent_root(root, _ARCH) / "runs" / run_id / "actions" / "plan_fuse"
    action.mkdir(parents=True)
    (action / "staging.md").write_text(_PLAN_BODY, encoding="utf-8")
    checked = _check_output_contract(
        root,
        "tg-plan-staging-v1",
        run_id=run_id,
        workflow_id="tg-plan",
        action_id="plan_fuse",
    )
    assert checked.get("ok") is True, checked
    out = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    assert (tg_root(root, arch=_ARCH) / "plan.md").read_text(encoding="utf-8") == _PLAN_BODY


def test_plan_staging_contract_fails_when_empty(tmp_path: Path) -> None:
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    checked = _check_output_contract(
        root,
        "tg-plan-staging-v1",
        run_id=run_id,
        workflow_id="tg-plan",
        action_id="plan_fuse",
    )
    assert checked.get("ok") is False
    assert "missing outputs" in str(checked.get("message") or "")


def test_analyze_staging_contract_accepts_parts_worklog_md(tmp_path: Path) -> None:
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_MATCH_ANY
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.actions.tg_product import run_analyze_promote
    from ascendc_pilot.paths import agent_root, ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    assert "tg-analyze-staging-v1" in OUTPUT_CONTRACT_MATCH_ANY
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-solve", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    parts = agent_root(root, _ARCH) / "runs" / run_id / "actions" / "analyze_round" / "parts"
    parts.mkdir(parents=True)
    body = "open: []\n\n## case-1\n场景与命中\n构造\n收窄\n引理线索\n"
    (parts / "worklog.md").write_text(body, encoding="utf-8")
    checked = _check_output_contract(
        root,
        "tg-analyze-staging-v1",
        run_id=run_id,
        workflow_id="tg-solve",
        action_id="analyze_round",
    )
    assert checked.get("ok") is True, checked
    out = run_analyze_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    assert (tg_root(root, arch=_ARCH) / "worklog.md").read_text(encoding="utf-8").startswith("open:")
