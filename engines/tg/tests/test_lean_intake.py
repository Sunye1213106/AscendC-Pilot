"""TG intake of UO lean export (external artifact hashes; no UO contracts)."""

from __future__ import annotations

from pathlib import Path

from testcase_agent.understand import _load_source_hashes
from testcase_agent.validation import REQUIRED_KB_EXPORT_FILES, validate_intake


def test_load_source_hashes_prefers_artifact_file(tmp_path: Path) -> None:
    from testcase_agent.io import write_yaml

    uo = tmp_path / ".ascendc-agent" / "uo"
    (uo / "checks").mkdir(parents=True)
    write_yaml(uo / "checks" / "artifact_hashes.yaml", {"hashes": {"tiling/key_space.yaml": "a" * 64}})
    hashes = _load_source_hashes(uo, {}, {})
    assert hashes["tiling/key_space.yaml"] == "a" * 64


def test_validate_intake_accepts_lean_external_hashes() -> None:
    files: dict = {
        "checks/artifact_hashes.yaml": {"hashes": {"tiling/key_space.yaml": "b" * 64}},
        "quality.yaml": {"status": "pass"},
    }
    for rel in REQUIRED_KB_EXPORT_FILES:
        files.setdefault(rel, {"version": 1})
    export = {"files": files, "context_slice": {"entities": [], "testcase_contract": None}}
    final = {"status": "pass", "source_artifact_hashes": {"tiling/key_space.yaml": "b" * 64}}
    report = validate_intake(export, final)
    codes = [i.code for i in report.blocking_issues]
    assert "SOURCE_HASHES_MISSING" not in codes
    assert "MISSING_TESTCASE_CONTRACT" not in codes


def test_validate_intake_ignores_legacy_uo_contract() -> None:
    files: dict = {
        "contracts/testcase.yaml": {"version": 2, "source": {}, "interface": {}},
        "checks/artifact_hashes.yaml": {"hashes": {"tiling/key_space.yaml": "c" * 64}},
        "quality.yaml": {"status": "pass"},
    }
    for rel in REQUIRED_KB_EXPORT_FILES:
        files.setdefault(rel, {"version": 1})
    report = validate_intake(
        {"files": files, "context_slice": {}},
        {"status": "pass", "source_artifact_hashes": {"tiling/key_space.yaml": "c" * 64}},
    )
    warn_codes = [i.code for i in report.warnings]
    assert "LEGACY_UO_CONTRACT_IGNORED" in warn_codes
    assert report.status != "fail"
