from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from testcase_agent import init as init_mod
from testcase_agent.init import TgInitError, tg_init
from testcase_agent.io import read_json, read_yaml, write_json
from testcase_agent.planner import build_plan, tg_plan


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    uo = repo / ".understand-operator" / "DemoOp"
    uo.mkdir(parents=True)
    (uo / "marker.yaml").write_text("version: 1\n", encoding="utf-8")
    return repo, uo


def _validation(status: str = "pass") -> dict[str, Any]:
    return {
        "status": status,
        "phase": "final",
        "issues": [],
        "source_artifact_hashes": {
            "contracts/testcase.yaml": "a" * 64,
            "tiling/coverage_model.yaml": "b" * 64,
        },
        "entity_count": 1,
        "relation_count": 0,
        "unresolved_count": 0,
        "conflict_count": 0,
    }


def _contract(**updates: Any) -> dict[str, Any]:
    base = {
        "version": 2,
        "op_name": "DemoOp",
        "source": {
            "understand_phase": "phase7",
            "quality_status": "pass",
            "canonical_hashes": {"contracts/testcase.yaml": "a" * 64},
        },
        "interface": {
            "required_inputs": [],
            "optional_inputs": [],
            "outputs": [],
            "attrs": [],
            "dtype_layout_domains": [],
        },
        "typed_constraints": [],
        "coverage_obligations": {
            "tiling_keys": [],
            "tilingdata": [],
            "kernel_paths": [],
            "numerical": [],
            "negative": [],
        },
        "golden_contract": {"inputs": [], "outputs": [], "generation_policy": [], "tolerance_policy": []},
        "unresolved": [],
        "conflicts": [],
        "evidence_refs": [],
    }
    base.update(updates)
    return base


def _payload(contract: dict[str, Any] | None = None, quality: dict[str, Any] | None = None, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "op_name": "DemoOp",
        "uo_root": "/tmp/uo",
        "view": "testcase-contract",
        "files": {
            "contracts/testcase.yaml": contract or _contract(),
            "test/contract.yaml": {"input_domain": {}, "typed_constraints": [], "kernel_branch_obligations": []},
            "tiling/coverage_model.yaml": coverage or {"family_obligations": [], "key_field_obligations": {}, "key_relation_obligations": []},
            "kernel/branches.yaml": {"branches": []},
            "cross_layer/impact_graph.yaml": {"nodes": [], "edges": [], "impacts": []},
            "quality.yaml": quality or {"status": "pass", "decision": "pass"},
        },
    }


def _patch_intake(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], validation: dict[str, Any] | None = None) -> None:
    monkeypatch.setattr(init_mod, "run_final_validation", lambda project_root, op_name, uo_root: validation or _validation())
    monkeypatch.setattr(init_mod, "export_testcase_contract", lambda project_root, op_name, uo_root: payload)


def _snapshot(repo: Path, files: dict[str, Any]) -> None:
    root = repo / ".testcase-generator" / "DemoOp" / "snapshot"
    root.mkdir(parents=True)
    write_json(
        root / "understand_contract.json",
        {
            "version": 1,
            "op_name": "DemoOp",
            "view": "testcase-contract",
            "files": files,
            "source_artifact_hashes": {"contracts/testcase.yaml": "a" * 64},
            "snapshot_hash": "snapshot-hash",
        },
    )


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_contract_version_error_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    payload = _payload(_contract(version=1))
    _patch_intake(monkeypatch, payload)

    with pytest.raises(TgInitError):
        tg_init(repo, "DemoOp")

    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert report["status"] == "fail"
    assert any(item["code"] == "TESTCASE_CONTRACT_VERSION" for item in report["blocking_issues"])


def test_quality_fail_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload(quality={"status": "fail"}))

    with pytest.raises(TgInitError):
        tg_init(repo, "DemoOp")

    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert any(item["code"] == "QUALITY_FAIL" for item in report["blocking_issues"])


def test_hard_stable_id_reference_missing_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    contract = _contract(
        coverage_obligations={
            "kernel_paths": [
                {
                    "id": "COV_KERNEL_PATH_HARD",
                    "priority": "hard",
                    "target_refs": ["KPATH_MISSING"],
                }
            ]
        }
    )
    _patch_intake(monkeypatch, _payload(contract))

    with pytest.raises(TgInitError):
        tg_init(repo, "DemoOp")

    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert any(item["code"] == "DANGLING_HARD_REF" for item in report["blocking_issues"])


def test_warning_does_not_block_and_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    payload = _payload(quality={"status": "pass", "warnings": [{"severity": "warning", "message": "minor gap"}]})
    _patch_intake(monkeypatch, payload)

    result = tg_init(repo, "DemoOp")

    assert result["run"]["status"] == "warn"
    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert report["status"] == "warn"
    assert report["warnings"]


def test_snapshot_hash_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload())

    first = tg_init(repo, "DemoOp")["snapshot"]["snapshot_hash"]
    second = tg_init(repo, "DemoOp")["snapshot"]["snapshot_hash"]

    assert first == second
    meta = read_yaml(repo / ".testcase-generator" / "DemoOp" / "snapshot" / "snapshot_meta.yaml")
    assert meta["snapshot_hash"] == first


def test_same_input_repeated_plan_is_deterministic(tmp_path: Path) -> None:
    repo, _uo = _repo(tmp_path)
    files = _payload(
        coverage={
            "family_obligations": [{"family_id": "FAM_A", "reachability": "reachable"}],
            "key_field_obligations": {"mode": {"values": [0, 1], "independent": True}},
            "key_relation_obligations": [{"id": "COV_REL_MODE", "relation_type": "pairwise", "fields": ["mode"]}],
        }
    )["files"]
    _snapshot(repo, files)

    first = tg_plan(repo, "DemoOp")
    second = tg_plan(repo, "DemoOp")

    assert first["plan_hash"] == second["plan_hash"]
    assert first["obligations"] == second["obligations"]


def test_derived_field_is_not_free_obligation(tmp_path: Path) -> None:
    files = _payload(
        coverage={
            "family_obligations": [],
            "key_field_obligations": {
                "derived_mask": {"values": [0, 1], "independent": False, "kind": "derived"},
                "layout": {"values": ["ND"], "independent": True},
            },
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    fields = [item for item in plan["obligations"] if item["kind"] == "tiling_key_field"]
    assert len(fields) == 1
    assert fields[0]["target_refs"] == ["layout"]


def test_unreachable_and_reachable_are_distinguished(tmp_path: Path) -> None:
    files = _payload(
        coverage={
            "family_obligations": [
                {"family_id": "FAM_REACH", "reachability": "reachable"},
                {"family_id": "FAM_DEAD", "reachability": "unreachable", "reason": "compile-time folded"},
            ],
            "key_field_obligations": {},
            "key_relation_obligations": [],
        }
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    by_target = {item["target_refs"][0]: item for item in plan["obligations"] if item["kind"] == "family"}
    assert by_target["FAM_REACH"]["status"] == "pending"
    assert by_target["FAM_DEAD"]["status"] == "proof_required"
    assert by_target["FAM_DEAD"]["reachability"] == "unreachable"


def test_optional_input_does_not_replicate_all_families(tmp_path: Path) -> None:
    contract = _contract(interface={"optional_inputs": [{"name": "mask"}, {"name": "pse"}], "dtype_layout_domains": []})
    files = _payload(
        contract,
        coverage={
            "family_obligations": [{"family_id": "FAM_A"}, {"family_id": "FAM_B"}],
            "key_field_obligations": {},
            "key_relation_obligations": [],
        },
    )["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert len([item for item in plan["obligations"] if item["kind"] == "family"]) == 2
    assert len([item for item in plan["obligations"] if item["kind"] == "optional_input_mode"]) == 2


def test_conflicting_hard_obligation_blocks_approval(tmp_path: Path) -> None:
    contract = _contract(
        coverage_obligations={
            "kernel_paths": [
                {
                    "id": "COV_KERNEL_PATH_CONFLICT",
                    "priority": "hard",
                    "status": "conflicting",
                    "target_refs": ["KPATH_A"],
                    "reason": "two entries disagree",
                }
            ]
        }
    )
    files = _payload(contract)["files"]
    plan = build_plan({"op_name": "DemoOp", "files": files, "snapshot_hash": "s"})

    assert plan["unresolved"]["status"] == "blocked"
    assert plan["unresolved"]["blocking_hard_obligations"]
    assert "是否允许进入 SMT 阶段: 否" in plan["review"]


def test_testagent_does_not_modify_understand_operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, uo = _repo(tmp_path)
    _patch_intake(monkeypatch, _payload())
    before = _tree_hash(uo)

    tg_init(repo, "DemoOp")
    tg_plan(repo, "DemoOp")

    assert _tree_hash(uo) == before


def test_export_missing_has_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _uo = _repo(tmp_path)
    monkeypatch.setattr(init_mod, "run_final_validation", lambda project_root, op_name, uo_root: _validation())

    def missing_export(project_root: Path, op_name: str, uo_root: Path) -> dict[str, Any]:
        raise FileNotFoundError("testcase-contract export failed: Missing canonical files for view 'testcase-contract': contracts/testcase.yaml")

    monkeypatch.setattr(init_mod, "export_testcase_contract", missing_export)

    with pytest.raises(TgInitError) as exc:
        tg_init(repo, "DemoOp")

    assert "testcase-contract export failed" in str(exc.value)
    report = read_yaml(repo / ".testcase-generator" / "DemoOp" / "intake" / "validation_report.yaml")
    assert "Missing canonical files" in report["blocking_issues"][0]["message"]
