from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from understand_operator._operator.artifacts import init_operator_layout, operator_root
from understand_operator._operator.kb_compiler import compile_kb
from understand_operator.scripts.kb_query_export import export_view
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
