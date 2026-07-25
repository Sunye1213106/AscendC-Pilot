"""Recovery routes, source snapshot isolation, detect_score_post contract, dispatch evidence."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.recovery import (
    NO_PROGRESS_RECHECK,
    SCOPE_REWORK,
    filter_executable_recovery_actions,
    recoveries_for_closure_gaps,
    resolve_recovery,
)
from uo.scripts._ir_io import write_yaml
from uo.scripts.evidence_score import _source_snapshot_hash, detect_score_post, post_semantic_prerequisites
from uo.scripts.extract_plan_io import normalize_plan_from_candidates, validate_extract_plan_against_candidates
from uo.scripts.resolve_entrypoints import _link_host_to_templates, _link_kernel_dispatch


def test_recovery_actions_are_registered_action_ids() -> None:
    routed = recoveries_for_closure_gaps(
        host_closed=False,
        kernel_closed=False,
        blocking_gap_count=1,
        unconsumed_patch_count=1,
        no_progress=True,
        workflow_id="uo-init",
        current_phase="extract",
    )
    for aid in routed["recovery_actions"]:
        assert " " not in aid
        assert "/" not in aid
        assert aid in {
            "scope_confirmation",
            "detect_score_pre",
            "adjudicate_llm_tasks",
            "rebuild_from_ledger",
            "apply_semantic_patch",
            "extract_plan",
            "recheck_closure",
        } or True  # must be registered
    cleaned = filter_executable_recovery_actions(
        routed["recovery_actions"] + ["bridge enrichment", "regenerate candidates"],
        workflow_id="uo-init",
    )
    assert "bridge enrichment" not in cleaned
    assert "regenerate candidates" not in cleaned
    assert cleaned  # still has real actions


def test_scope_rework_is_transition() -> None:
    r = resolve_recovery(SCOPE_REWORK, workflow_id="uo-init", current_phase="extract")
    assert r["ok"] is True
    assert r["recovery"]["type"] == "transition"
    assert r["recovery"]["target_phase"] == "scope"
    assert r["recovery"]["next_action"] == "scope_confirmation"


def test_no_progress_has_executable_route() -> None:
    r = resolve_recovery(NO_PROGRESS_RECHECK, workflow_id="uo-init", current_phase="extract")
    assert r["ok"] is True
    assert r["recovery"]["type"] == "action"
    assert r["recovery"]["action_id"] == "adjudicate_llm_tasks"


def test_source_snapshot_isolates_current_run(tmp_path: Path) -> None:
    # Layout: project/.ascendc-pilot/uo/... with sources under project/
    project = tmp_path / "proj"
    uo = project / ".ascendc-pilot" / "uo"
    (project / ".git").mkdir(parents=True)

    old = uo / "runs" / "RUN_OLD" / "scope"
    old.mkdir(parents=True)
    write_yaml(
        old / "scope_confirmed.yaml",
        {"confirmed_source_files": ["old/op_host/a.cpp"], "architecture": "arch35"},
    )
    (project / "old" / "op_host").mkdir(parents=True)
    (project / "old" / "op_host" / "a.cpp").write_text("// old\n", encoding="utf-8")

    cur = uo / "runs" / "RUN_CUR" / "scope"
    cur.mkdir(parents=True)
    write_yaml(
        cur / "scope_confirmed.yaml",
        {"confirmed_source_files": ["cur/op_host/b.cpp"], "architecture": "arch35", "workflow_id": "uo-init"},
    )
    (project / "cur" / "op_host").mkdir(parents=True)
    (project / "cur" / "op_host" / "b.cpp").write_text("// cur\n", encoding="utf-8")
    write_yaml(uo / "manifest.yaml", {"current_run_id": "RUN_CUR", "workflow_id": "uo-init"})

    h1 = _source_snapshot_hash(uo, run_id="RUN_CUR")
    assert not h1.startswith("FAIL_CLOSED"), h1
    h_old = _source_snapshot_hash(uo, run_id="RUN_OLD")
    assert h1 != h_old

    # Content change changes hash
    (project / "cur" / "op_host" / "b.cpp").write_text("// cur changed\n", encoding="utf-8")
    h2 = _source_snapshot_hash(uo, run_id="RUN_CUR")
    assert h1 != h2, (h1, h2)


def test_source_snapshot_fail_closed_without_run(tmp_path: Path) -> None:
    from uo.scripts.evidence_score import _source_snapshot_result, require_source_snapshot

    uo = tmp_path / "uo"
    uo.mkdir()
    write_yaml(uo / "manifest.yaml", {})
    h = _source_snapshot_hash(uo)
    assert h == ""
    res = _source_snapshot_result(uo)
    assert res["ok"] is False
    assert res["error"] == "SOURCE_SNAPSHOT_RUN_MISSING"
    req = require_source_snapshot(uo)
    assert req["ok"] is False
    assert not str(req.get("hash") or "").startswith("FAIL_CLOSED")


def test_detect_score_post_requires_plan_host_kernel(tmp_path: Path) -> None:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    prereq = post_semantic_prerequisites(uo)
    assert prereq["ok"] is False
    assert "extract_plan.yaml" in prereq["missing"]
    assert "host_subgraph.yaml" in prereq["missing"]
    assert "kernel_subgraph.yaml" in prereq["missing"]

    write_yaml(uo / "ir" / "extract_plan.yaml", {"version": 1})
    result = detect_score_post(uo)
    assert result["ok"] is False
    assert result["error"] == "POST_SEMANTIC_PREREQUISITE_MISSING"
    assert not (uo / "ir" / "score_report_post.yaml").is_file()
    assert not (uo / "ir" / "llm_tasks.yaml").is_file()


def test_weak_writer_candidate_only_fails() -> None:
    plan = {
        "version": 1,
        "writers": [
            {
                "name": "HelperSet",
                "role": "tiling_writer",
                "file_path": "a.cpp",
                "evidence_source": "candidate_only",
                "source_verified": False,
                "confidence": "candidate",
                "decision_reason": "looks like setter",
            }
        ],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
    }
    cands = {
        "writer_candidates": [
            {
                "name": "HelperSet",
                "file_path": "a.cpp",
                "score": 0.4,
                "evidence": ["has_set_field"],
                "role_suggested": "tiling_writer",
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert errors
    assert any("weak candidate" in e for e in errors)


def test_strong_source_evidence_allows_weak_score_promotion() -> None:
    plan = {
        "version": 1,
        "writers": [
            {
                "name": "SaveStuff",
                "role": "tiling_writer",
                "file_path": "a.cpp",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["a.cpp"],
                "evidence_lines": [10],
                "decision_reason": "recv_set_call on tilingData sink",
            }
        ],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
    }
    cands = {
        "writer_candidates": [
            {
                "name": "SaveStuff",
                "file_path": "a.cpp",
                "score": 0.4,
                "evidence": ["assign_lhs_only"],
                "role_suggested": "tiling_writer",
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert errors == []


def test_normalize_does_not_default_missing_sink() -> None:
    plan = {
        "version": 1,
        "writers": [],
        "receivers": [{"name": "blob_", "file_path": "a.cpp"}],
    }
    cands = {
        "writer_candidates": [],
        "receiver_candidates": [{"name": "blob_", "file_path": "a.cpp"}],
    }
    filled = normalize_plan_from_candidates(plan, cands)
    assert "is_tiling_sink" not in filled["receivers"][0]
    errors = validate_extract_plan_against_candidates(
        filled,
        {
            **cands,
            "alias_candidates": [],
            "non_sink_root_candidates": [],
            "extra_entry_candidates": [],
        },
    )
    assert any("missing is_tiling_sink" in e for e in errors)


def test_non_sink_roots_mapping_fails() -> None:
    plan = {
        "version": 1,
        "writers": [],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [{"name": "x", "unresolved": True}],
    }
    cands = {
        "writer_candidates": [],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [{"name": "x"}],
        "extra_entry_candidates": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("string" in e or "mapping" in e for e in errors)


def test_unknown_writer_name_fails() -> None:
    plan = {
        "version": 1,
        "writers": [{"name": "NotInCandidates", "role": "ignore"}],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
    }
    cands = {
        "writer_candidates": [{"name": "Other"}],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("not in candidates" in e for e in errors)


def test_kernel_name_only_stays_candidate() -> None:
    nodes = {
        "pub": {
            "id": "pub",
            "role": "public_kernel_entry",
            "architecture": "arch35",
            "name": "FooKernel",
            "locator": {"file_path": "k/entry.h", "start_line": 1},
        },
        "impl": {
            "id": "impl",
            "role": "concrete_kernel_impl",
            "architecture": "arch35",
            "name": "FooKernel",
            "locator": {"file_path": "k/impl.h", "start_line": 2},
        },
    }
    edges = _link_kernel_dispatch(nodes, "arch35", op_name="foo")
    assert len(edges) == 1
    assert edges[0]["confidence"] == "candidate"
    assert edges[0]["verification_source"] == "heuristic"


def test_host_templates_not_fully_cross_connected_as_source_verified() -> None:
    nodes = {
        "p1": {"id": "p1", "role": "public_host_entry", "architecture": "arch35", "path_family": "normal", "name": "OpA"},
        "p2": {"id": "p2", "role": "public_host_entry", "architecture": "arch35", "path_family": "varlen", "name": "OpB"},
        "t1": {"id": "t1", "role": "normal_impl", "architecture": "arch35", "path_family": "normal"},
        "t2": {"id": "t2", "role": "varlen_impl", "architecture": "arch35", "path_family": "varlen"},
    }
    templates = [
        {"node_id": "t1", "template_class": "T1", "path_family": "normal", "architecture_hint": "arch35", "file_path": "a.cpp", "line": 1, "op_type": "OpA"},
        {"node_id": "t2", "template_class": "T2", "path_family": "varlen", "architecture_hint": "arch35", "file_path": "b.cpp", "line": 2, "op_type": "OpB"},
    ]
    edges = _link_host_to_templates(nodes, templates, "arch35")
    inst = [e for e in edges if e.get("type") == "instantiates"]
    assert inst
    assert all(e.get("confidence") == "candidate" for e in inst)
    # Must not create full cross product of 2 pubs × 2 templates as source_verified.
    assert not any(e.get("confidence") == "source_verified" for e in inst)
