from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_phase1_authoring_contract_is_wired_into_runtime_prompts() -> None:
    contract_rel = "prompts/common/11_phase1_boundary_yaml_authoring.md"
    assert (ROOT / contract_rel).is_file()

    for rel in (
        "agents/uo-boundary-agent.md",
        "prompts/01_workflow_orchestrator.md",
        "prompts/common/08_agent_io_protocol.md",
        "skills/uo-init/SKILL.md",
    ):
        assert "11_phase1_boundary_yaml_authoring.md" in _read(rel), rel


def test_phase1_authoring_contract_explains_model_yaml_boundary_and_schema() -> None:
    contract = _read("prompts/common/11_phase1_boundary_yaml_authoring.md")
    normalized = " ".join(contract.lower().split())

    assert "model may write small temporary yaml batch files" in normalized
    assert "must not write or replace the final fact documents directly" in normalized
    assert "interface.yaml" in contract
    assert "source_files.yaml" in contract
    assert "entrypoints.yaml" in contract
    assert "source_text" in contract
    assert "code_hash" in contract
    assert "file_hash" in contract
    assert "status: pass" in contract


def test_boundary_agent_requires_incremental_validation_and_repair() -> None:
    boundary = _read("agents/uo-boundary-agent.md")

    assert "one minimum-valid batch" in boundary
    assert "repair by stable ID" in boundary
    assert "outside `PROJECT_ROOT` and `UO_ROOT`" in boundary
    assert "write YAML directly" not in boundary
