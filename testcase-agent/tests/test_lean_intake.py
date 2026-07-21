"""TG intake of UO lean export (external artifact hashes)."""

from __future__ import annotations

from pathlib import Path

from testcase_agent.understand import _load_source_hashes
from testcase_agent.validation import REQUIRED_TESTCASE_CONTRACT_FILES, validate_intake


def test_load_source_hashes_prefers_artifact_file(tmp_path: Path) -> None:
    from testcase_agent.io import write_yaml

    uo = tmp_path / ".understand-operator" / "Demo"
    (uo / "checks").mkdir(parents=True)
    write_yaml(uo / "checks" / "artifact_hashes.yaml", {"hashes": {"contracts/testcase.yaml": "a" * 64}})
    contract = {"source": {"canonical_hashes": {}, "hashes_ref": "checks/artifact_hashes.yaml"}}
    hashes = _load_source_hashes(uo, contract, {})
    assert hashes["contracts/testcase.yaml"] == "a" * 64


def test_validate_intake_accepts_lean_external_hashes() -> None:
    files: dict = {
        "contracts/testcase.yaml": {
            "version": 2,
            "op_name": "Demo",
            "source": {"canonical_hashes": {}, "hashes_ref": "checks/artifact_hashes.yaml", "quality_status": "pass"},
            "interface": {},
            "variables": [],
            "input_realization": [],
            "kernel_branch_obligations": [],
            "coverage_obligations": {},
        },
        "checks/artifact_hashes.yaml": {"hashes": {"contracts/testcase.yaml": "b" * 64}},
        "quality.yaml": {"status": "pass"},
    }
    for rel in REQUIRED_TESTCASE_CONTRACT_FILES:
        files.setdefault(rel, {})
    export = {"files": files, "context_slice": {"testcase_contract": files["contracts/testcase.yaml"]}}
    final = {"status": "pass", "source_artifact_hashes": {"contracts/testcase.yaml": "b" * 64}}
    report = validate_intake(export, final)
    codes = [i.code for i in report.blocking_issues]
    assert "SOURCE_HASHES_MISSING" not in codes
