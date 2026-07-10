from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understand_operator._operator.artifacts import init_operator_layout, operator_root
from understand_operator._operator.kb_compiler import compile_kb, promote_kb, validate_kb
from understand_operator.scripts.kb_query_export import export_context_slice, export_view
from understand_operator.scripts.update_operator import _build_stale_artifacts, _build_update_plan


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = operator_root(repo, "DemoOp")
    init_operator_layout(base, "DemoOp", repo)
    return repo, base


def test_layout_creates_v2_slices_and_query_exports(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)

    for rel in (
        "manifest.yaml",
        "registry/variables.yaml",
        "kernel/compile_model.yaml",
        "cross_layer/impact_graph.yaml",
        "query/routes.yaml",
        "contracts/code_change.yaml",
        "contracts/testcase.yaml",
    ):
        assert (base / rel).exists(), rel

    payload = export_view(base, "DemoOp", "code-change")
    assert payload["view"] == "code-change"
    assert "contracts/code_change.yaml" in payload["files"]


def test_compiler_detects_alias_conflict_and_dangling_evidence(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "registry" / "variables.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "variables": [
                    {
                        "id": "VAR_MASK_PRESENT",
                        "kind": "derived_variable",
                        "canonical_name": "mask_present",
                        "scope": "host",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                    },
                    {
                        "id": "VAR_OTHER_MASK",
                        "kind": "derived_variable",
                        "canonical_name": "other_mask",
                        "scope": "kernel",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "input_to_tiling.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "relations": [
                    {
                        "id": "REL_MASK_TO_KEY",
                        "type": "implies",
                        "expression": {"op": "eq", "var": "VAR_MASK_PRESENT", "value": True},
                        "evidence_refs": ["EV_MISSING"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = compile_kb(base, "DemoOp", write_outputs=True)

    codes = {issue.code for issue in result.issues}
    assert result.status == "fail"
    assert "ALIAS_CONFLICT" in codes
    assert "DANGLING_EVIDENCE_REF" in codes
    assert (base / "archive" / "runs" / "kb_compile_report.yaml").exists()


def test_update_plan_marks_v2_dependencies_stale() -> None:
    plan = _build_update_plan(
        {
            "status": "ok",
            "changed_files": ["op_kernel/foo_kernel.cpp", "op_host/foo_tiling.cpp"],
            "changed_symbols": ["Process", "SetTilingKey"],
        }
    )
    stale = _build_stale_artifacts(plan)

    invalidated = {
        item
        for values in plan["artifact_invalidations"].values()
        for item in values
    }
    stale_paths = {item["path"] for item in stale["stale_artifacts"]}
    assert "kernel/compile_model.yaml" in invalidated
    assert "cross_layer/tiling_to_kernel.yaml" in stale_paths
    assert "contracts/code_change.yaml" in stale_paths
    assert "phase4" in plan["phases_to_rerun"]
    assert plan["dependency_hash"]


def test_compiler_accepts_registry_evidence_line_formats(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "registry" / "variables.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "variables": [
                    {
                        "id": "VAR_ATTEN_MASK_PRESENT",
                        "kind": "derived_variable",
                        "canonical_name": "atten_mask_present",
                        "scope": "host",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "registry" / "evidence.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "evidence": [
                    {
                        "id": "EV_HOST_017",
                        "file": "op_host/foo.cpp",
                        "lines": {"start": 10, "end": 12},
                        "symbol": "Foo",
                        "kind": "source_span",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "input_to_tiling.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "relations": [
                    {
                        "id": "REL_MASK_TO_KEY",
                        "type": "implies",
                        "expression": {"op": "eq", "var": "VAR_ATTEN_MASK_PRESENT", "value": True},
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = compile_kb(base, "DemoOp", write_outputs=False)
    assert not any(issue.code == "BAD_EVIDENCE_LINES" for issue in result.issues)
    assert not any(issue.code == "DANGLING_EVIDENCE_REF" for issue in result.issues)


def test_proposal_promotion_success_and_deterministic(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    for rel in ("flow/compute_graph.yaml", "flow/dataflow.yaml"):
        (base / rel).write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "op_name": "DemoOp",
                    "status": "not_applicable",
                    "reason": "minimal promotion unit test",
                    "evidence_refs": ["EV_HOST_017"],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    proposal = {
        "version": 1,
        "op_name": "DemoOp",
        "proposal_id": "PROP_HOST_001",
        "producer": {"agent": "uo-host-extraction", "phase": "phase2"},
        "generated_at": "2026-01-01T00:00:00Z",
        "status": "proposed",
        "canonical_updates": [
            {
                "target": "registry/evidence.yaml",
                "section": "evidence",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "EV_HOST_017",
                        "file": "op_host/foo.cpp",
                        "lines": [10, 12],
                        "symbol": "Foo",
                        "kind": "source_span",
                    }
                ],
            },
            {
                "target": "registry/symbols.yaml",
                "section": "symbols",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "SYM_HOST_FOO",
                        "kind": "function",
                        "canonical_name": "Foo",
                        "scope": "host",
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            {
                "target": "registry/variables.yaml",
                "section": "variables",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "VAR_ATTEN_MASK_PRESENT",
                        "kind": "derived_variable",
                        "canonical_name": "atten_mask_present",
                        "scope": "host",
                        "data_type": "bool",
                        "aliases": ["hasMask"],
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            {
                "target": "tiling/key_space.yaml",
                "section": "fields",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "KEY_MASK_MODE",
                        "kind": "tiling_key_field",
                        "canonical_name": "mask_mode",
                        "scope": "tiling",
                        "domain": [0, 1],
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            {
                "target": "tiling/constraints.yaml",
                "section": "relations",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "REL_MASK_CONSTRAINT",
                        "type": "implies",
                        "source_ids": ["VAR_ATTEN_MASK_PRESENT"],
                        "target_ids": ["KEY_MASK_MODE"],
                        "expression": {"op": "implies", "args": []},
                        "status": "confirmed",
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
            {
                "target": "cross_layer/input_to_tiling.yaml",
                "section": "relations",
                "merge_mode": "by_id",
                "entries": [
                    {
                        "id": "REL_MASK_TO_KEY",
                        "type": "implies",
                        "source_ids": ["VAR_ATTEN_MASK_PRESENT"],
                        "target_ids": ["KEY_MASK_MODE"],
                        "expression": {"op": "eq", "var": "VAR_ATTEN_MASK_PRESENT", "value": False},
                        "status": "confirmed",
                        "evidence_refs": ["EV_HOST_017"],
                    }
                ],
            },
        ],
        "unresolved": [],
        "conflicts": [],
    }
    p1 = base / "archive" / "proposals" / "host.yaml"
    p1.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")

    result1 = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    result2 = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    content_after_second = {
        rel: (base / rel).read_text(encoding="utf-8")
        for rel in ("registry/variables.yaml", "cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml")
    }
    result3 = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    content_after_third = {
        rel: (base / rel).read_text(encoding="utf-8")
        for rel in ("registry/variables.yaml", "cross_layer/behavior_graph.yaml", "cross_layer/impact_graph.yaml")
    }

    assert not any(issue.code == "BAD_PROMOTION_TARGET" for issue in result1.issues)
    assert result1.promotion_report["status"] == "promoted"
    assert result2.promotion_report["status"] == "promoted"
    assert result3.promotion_report["status"] == "promoted"
    assert content_after_second == content_after_third
    variables = yaml.safe_load((base / "registry" / "variables.yaml").read_text(encoding="utf-8"))
    assert variables["variables"][0]["id"] == "VAR_ATTEN_MASK_PRESENT"


def test_promotion_rejects_bad_target_and_is_atomic(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    original = (base / "registry" / "variables.yaml").read_text(encoding="utf-8")
    proposal = {
        "version": 1,
        "op_name": "DemoOp",
        "proposal_id": "PROP_BAD",
        "producer": {"agent": "uo-host-extraction", "phase": "phase2"},
        "canonical_updates": [
            {
                "target": "../skills/bad.yaml",
                "section": "variables",
                "merge_mode": "by_id",
                "entries": [{"id": "VAR_BAD"}],
            }
        ],
    }
    p1 = base / "archive" / "proposals" / "bad.yaml"
    p1.write_text(yaml.safe_dump(proposal, sort_keys=False), encoding="utf-8")
    result = promote_kb(base, "DemoOp", phase="phase2", proposal_paths=[p1])
    assert result.status == "fail"
    assert any(issue.code == "BAD_PROMOTION_TARGET" for issue in result.issues)
    assert (base / "registry" / "variables.yaml").read_text(encoding="utf-8") == original


def test_phase_validation_is_phase_aware(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    phase2 = validate_kb(base, "DemoOp", phase="phase2", write_outputs=False)
    assert not any(issue.artifact.startswith("kernel/") for issue in phase2.issues)
    phase5 = validate_kb(base, "DemoOp", phase="phase5", write_outputs=False)
    assert any(issue.code == "PLACEHOLDER_ARTIFACT" and issue.artifact.startswith("kernel/") for issue in phase5.issues)


def test_query_context_slice_variable_trace(tmp_path: Path) -> None:
    _repo_root, base = _repo(tmp_path)
    (base / "registry" / "variables.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "variables": [
                    {
                        "id": "VAR_ATTEN_MASK_PRESENT",
                        "kind": "derived_variable",
                        "canonical_name": "atten_mask_present",
                        "scope": "host",
                        "data_type": "bool",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (base / "cross_layer" / "behavior_graph.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "op_name": "DemoOp",
                "nodes": [{"id": "VAR_ATTEN_MASK_PRESENT", "kind": "variable", "label": "mask"}],
                "edges": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    payload = export_context_slice(base, "DemoOp", "variable-trace", "VAR_ATTEN_MASK_PRESENT")
    assert payload["query"]["intent"] == "variable-trace"
    assert payload["entities"][0]["stable_id"] == "VAR_ATTEN_MASK_PRESENT"


def test_tilingdata_numeric_update_can_be_local() -> None:
    plan = _build_update_plan(
        {
            "status": "ok",
            "changed_files": ["op_host/foo_tilingdata.cpp"],
            "changed_symbols": ["SetTilingData"],
        }
    )
    assert "tilingdata_numeric_local" in plan["impacted_areas"]
    assert "phase4" not in plan["phases_to_rerun"]
