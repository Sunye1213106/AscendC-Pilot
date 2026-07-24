"""Run isolation and fail-closed coverage for semantic task/patch APIs."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from uo.scripts._ir_io import write_yaml
from uo.scripts.llm_tasks import (
    apply_patches_batch,
    apply_task_patch,
    compute_semantic_stats,
    load_llm_tasks,
    recheck_does_not_increment,
    resolve_patches_for_apply,
    sync_tasks_from_materialization,
    validate_semantic_patch_set,
    validate_task_patch,
)
from uo.scripts.semantic_patches import validate_typed_patch
from uo.scripts.semantic_resolution_ledger import (
    apply_ledger_to_entrypoint_graph,
    load_ledger,
    rebuild_derived_graphs,
)

RUN_TEST = "RUN_TEST"
RUN_A = "RUN_A"
RUN_B = "RUN_B"
SNAP = "snap1"


def _uo(tmp_path: Path) -> Path:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    return uo


def _repo_uo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    uo = repo / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(uo / "manifest.yaml", {"op_name": "op", "current_run_id": RUN_B, "workflow_id": "uo-init"})
    return repo, uo


def _tasks_doc(run_id: str, tasks: list[dict[str, Any]], *, batches: int = 0) -> dict[str, Any]:
    return {
        "version": 1,
        "artifact_identity": {"run_id": run_id, "workflow_id": "uo-init"},
        "active_run_id": run_id,
        "total_semantic_batches": batches,
        "tasks": tasks,
    }


def _task(task_id: str = "TASK_1", *, run_id: str = RUN_TEST, **extra: Any) -> dict[str, Any]:
    task = {
        "task_id": task_id,
        "run_id": run_id,
        "workflow_id": "uo-init",
        "status": "open",
        "task_status": "open",
        "severity": "blocking",
        "blocking": True,
        "semantic_status": "unresolved",
        "type": "choose_edge",
        "object_type": "call_edge",
        "target": "edge_real",
        "candidates": [{"id": "edge_real"}],
        "allowed_actions": ["accept_edge", "mark_missing"],
        "source_snapshot_hash": SNAP,
        "candidate_set_hash": "cset1",
        "task_attempts": 0,
    }
    task.update(extra)
    return task


def _patch(task_id: str = "TASK_1", *, run_id: str = RUN_TEST, **extra: Any) -> dict[str, Any]:
    patch = {
        "task_id": task_id,
        "run_id": run_id,
        "action": "accept_edge",
        "edge_id": "edge_real",
        "accepted_candidate_ids": ["edge_real"],
        "rejected_candidate_ids": [],
        "source_snapshot_hash": SNAP,
        "candidate_set_hash": "cset1",
    }
    patch.update(extra)
    return patch


def _ledger_patch(task_id: str, *, run_id: str = RUN_TEST, **extra: Any) -> dict[str, Any]:
    patch = {
        "task_id": task_id,
        "run_id": run_id,
        "workflow_id": "uo-init",
        "phase": "extract",
        "control_action_id": "adjudicate_llm_tasks",
        "actor_id": "uo-semantic-resolve",
        "role_id": "producer",
        "action_session_id": "AS_TEST",
        "lease_id": "LEASE_TEST",
        "status": "active",
        "semantic_action": "accept_edge",
        "action": "accept_edge",
        "patch_type": "edge_resolution",
        "edge_id": "edge_real",
        "accepted_candidate_ids": ["edge_real"],
        "rejected_candidate_ids": [],
        "source_snapshot_hash": SNAP,
        "candidate_set_hash": "cset1",
        "apply_status": "pending",
    }
    patch.update(extra)
    return patch


def test_validate_patch_requires_current_run_id() -> None:
    doc = _tasks_doc(RUN_TEST, [_task()])
    with pytest.raises(TypeError):
        validate_task_patch(doc, _patch(), current_source_hash=SNAP)  # type: ignore[call-arg]


def test_missing_task_run_id_fails_closed() -> None:
    task = _task()
    task.pop("run_id")
    out = validate_task_patch(_tasks_doc(RUN_TEST, [task]), _patch(), current_source_hash=SNAP, current_run_id=RUN_TEST)
    assert out["ok"] is False
    assert out["error"] == "SEMANTIC_TASK_RUN_ID_MISSING"


def test_missing_patch_run_id_fails_closed() -> None:
    patch = _patch()
    patch.pop("run_id")
    out = validate_task_patch(_tasks_doc(RUN_TEST, [_task()]), patch, current_source_hash=SNAP, current_run_id=RUN_TEST)
    assert out["ok"] is False
    assert out["error"] == "SEMANTIC_PATCH_RUN_ID_MISSING"


def test_old_run_task_not_seen_by_resolve(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_B, [_task("TASK_A", run_id=RUN_A)]))
    out = resolve_patches_for_apply(uo, current_run_id=RUN_B)
    assert out["ok"] is True
    assert out["skipped"] is True
    assert out["reason"] == "no_open_blocking"


def test_old_run_task_not_seen_by_apply(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_B, [_task("TASK_A", run_id=RUN_A)]))
    out = apply_task_patch(uo, _patch("TASK_A", run_id=RUN_B), current_run_id=RUN_B, current_source_hash=SNAP)
    assert out["ok"] is False
    assert out["error"] == "SEMANTIC_TASK_RUN_MISMATCH"


def test_old_run_task_not_seen_by_stats(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_B, [_task("TASK_A", run_id=RUN_A)]))
    write_yaml(
        uo / "ir" / "semantic_resolution_ledger.yaml",
        {"version": 1, "semantic_patches": [_ledger_patch("TASK_A", run_id=RUN_A)]},
    )
    stats = compute_semantic_stats(uo, current_run_id=RUN_B)
    assert stats["task_total"] == 0
    assert stats["blocking_gap_count"] == 0
    assert stats["accept_count"] == 0


def test_old_run_task_not_seen_by_recheck(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_B, [_task("TASK_A", run_id=RUN_A)]))
    out = recheck_does_not_increment(uo, current_run_id=RUN_B)
    assert out["ok"] is True
    assert out["blocking_gap_count"] == 0
    assert out["tasks"] == []


def test_ledger_uses_semantic_patches_not_records() -> None:
    graph = {"edges": [{"id": "edge_real", "type": "dispatches_to", "confidence": "candidate"}]}
    records_only = {"version": 1, "records": [_ledger_patch("TASK_RECORDS")], "semantic_patches": []}
    out = apply_ledger_to_entrypoint_graph({"edges": [dict(graph["edges"][0])]}, records_only)
    assert out["edges"][0]["confidence"] == "candidate"

    semantic = {"version": 1, "semantic_patches": [_ledger_patch("TASK_SEM")]}
    upgraded = apply_ledger_to_entrypoint_graph({"edges": [dict(graph["edges"][0])]}, semantic)
    assert upgraded["edges"][0]["confidence"] == "semantic_verified"


def test_ledger_record_contains_full_control_identity(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_TEST, [_task()]))
    out = apply_patches_batch(
        uo,
        [_patch()],
        current_run_id=RUN_TEST,
        current_source_hash=SNAP,
        workflow_id="uo-init",
        phase="extract",
        control_action_id="apply_semantic_patch",
        actor_id="uo-semantic-resolve",
        role_id="producer",
        action_session_id="AS_APPLY",
        lease_id="LEASE_APPLY",
    )
    assert out["ok"] is True
    record = load_ledger(uo)["semantic_patches"][0]
    for key, expected in {
        "run_id": RUN_TEST,
        "workflow_id": "uo-init",
        "phase": "extract",
        "control_action_id": "apply_semantic_patch",
        "actor_id": "uo-semantic-resolve",
        "role_id": "producer",
        "action_session_id": "AS_APPLY",
        "lease_id": "LEASE_APPLY",
    }.items():
        assert record.get(key) == expected


def test_rebuild_filters_old_run_semantic_patches() -> None:
    source = inspect.getsource(rebuild_derived_graphs)
    assert 'ledger.get("semantic_patches")' in source
    assert 'ledger.get("records")' not in source
    assert "rec_run == current_run_id" in source


def test_missing_ledger_run_id_fails_closed(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_TEST, [_task()]))
    ledger = {"version": 1, "semantic_patches": [{**_ledger_patch("TASK_1"), "run_id": ""}]}
    out = sync_tasks_from_materialization(uo, ledger, current_run_id=RUN_TEST)
    assert out["ok"] is False
    assert out["error"] == "LEDGER_RUN_ID_MISSING"


def test_cross_run_reuse_requires_explicit_flag_and_same_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, uo = _repo_uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_B, []))
    write_yaml(
        uo / "ir" / "semantic_resolution_ledger.yaml",
        {
            "version": 1,
            "artifact_identity": {"run_id": RUN_A, "workflow_id": "uo-init"},
            "semantic_patches": [
                _dispatch_patch("TASK_NO_FLAG", run_id=RUN_A, allow_cross_run_reuse=False),
                _dispatch_patch("TASK_STALE", run_id=RUN_A, allow_cross_run_reuse=True, source_snapshot_hash="old"),
                _dispatch_patch("TASK_REUSE", run_id=RUN_A, allow_cross_run_reuse=True, source_snapshot_hash=SNAP),
            ],
        },
    )
    _patch_rebuild_dependencies(monkeypatch)

    out = rebuild_derived_graphs(repo, "op", run_id=RUN_B)
    assert out["ok"] is True, out
    ledger = load_ledger(uo)
    derived = [p for p in ledger["semantic_patches"] if p.get("reused_from_run_id") == RUN_A]
    assert [p["task_id"] for p in derived] == ["TASK_REUSE"]
    assert derived[0]["run_id"] == RUN_B
    assert derived[0]["source_snapshot_hash"] == SNAP


def test_incomplete_call_edge_patch_fails() -> None:
    out = validate_typed_patch(
        {"patch_type": "call_edge_resolution", "caller_function_id": "fn_a"},
        patch_type="call_edge_resolution",
    )
    assert out["ok"] is False
    assert out["error"] == "TYPED_PATCH_CALL_EDGE_INCOMPLETE"


def test_incomplete_dispatch_patch_fails() -> None:
    out = validate_typed_patch(
        {"patch_type": "entrypoint_dispatch_resolution", "source_node_id": "n_a"},
        patch_type="entrypoint_dispatch_resolution",
    )
    assert out["ok"] is False
    assert out["error"] == "TYPED_PATCH_ENTRYPOINT_DISPATCH_INCOMPLETE"


def test_incomplete_bridge_patch_fails() -> None:
    out = validate_typed_patch(
        {"patch_type": "tilingdata_bridge_resolution", "host_field_id": "HF_x"},
        patch_type="tilingdata_bridge_resolution",
    )
    assert out["ok"] is False
    assert out["error"] == "TYPED_PATCH_TILINGDATA_BRIDGE_INCOMPLETE"


def test_incomplete_template_patch_fails() -> None:
    out = validate_typed_patch(
        {"patch_type": "template_instance_resolution", "tilingkey_value_id": "TK_1"},
        patch_type="template_instance_resolution",
    )
    assert out["ok"] is False
    assert out["error"] == "TYPED_PATCH_TEMPLATE_INSTANCE_INCOMPLETE"


def test_typed_patch_never_downgrades_to_edge_resolution(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc(RUN_TEST, [_task("TASK_TYPED", object_type="call_edge")]),
    )
    out = validate_semantic_patch_set(
        uo,
        [
            _patch(
                "TASK_TYPED",
                patch_type="call_edge_resolution",
                caller_function_id="fn_a",
                edge_id="edge_real",
            )
        ],
        SNAP,
        current_run_id=RUN_TEST,
        require_full_coverage=False,
        mutate=False,
    )
    assert out["ok"] is False
    err = out["errors"][0]
    assert err["error"] == "TYPED_PATCH_CALL_EDGE_INCOMPLETE"
    assert err["patch_type"] == "call_edge_resolution"
    assert err["patch_type"] != "edge_resolution"


def test_run_b_does_not_consume_run_a_tasks_or_ledger_or_stats(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    task_b = _task(
        "TASK_B",
        run_id=RUN_B,
        type="mark_missing",
        object_type="call_edge",
        candidates=[],
        allowed_actions=["mark_missing"],
        candidate_set_hash="empty",
    )
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc(RUN_B, [_task("TASK_A", run_id=RUN_A), task_b]))
    write_yaml(
        uo / "ir" / "semantic_resolution_ledger.yaml",
        {"version": 1, "semantic_patches": [_ledger_patch("TASK_A", run_id=RUN_A)]},
    )

    resolved = resolve_patches_for_apply(uo, current_run_id=RUN_B)
    assert resolved["ok"] is True
    assert [p["task_id"] for p in resolved["patches"]] == ["TASK_B"]
    applied = apply_patches_batch(uo, resolved["patches"], current_run_id=RUN_B, current_source_hash=SNAP)
    assert applied["ok"] is True

    ledger = load_ledger(uo)
    assert any(p.get("run_id") == RUN_A for p in ledger["semantic_patches"])
    assert any(p.get("run_id") == RUN_B and p.get("task_id") == "TASK_B" for p in ledger["semantic_patches"])
    stats = compute_semantic_stats(uo, current_run_id=RUN_B)
    assert stats["task_total"] == 1
    assert stats["mark_missing_count"] == 1
    assert stats["accept_count"] == 0
    recheck = recheck_does_not_increment(uo, current_run_id=RUN_B)
    assert [t["task_id"] for t in recheck["tasks"]] == ["TASK_B"]


def _dispatch_patch(task_id: str, *, run_id: str, **extra: Any) -> dict[str, Any]:
    patch = _ledger_patch(
        task_id,
        run_id=run_id,
        patch_type="entrypoint_dispatch_resolution",
        edge_id="",
        source_node_id="node_a",
        target_node_id="node_b",
        relation="dispatches_to",
    )
    patch.update(extra)
    return patch


def _patch_rebuild_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "uo.scripts.evidence_score.require_source_snapshot",
        lambda _uo, run_id=None: {"ok": True, "hash": SNAP, "run_id": run_id, "workflow_id": "uo-init"},
    )
    monkeypatch.setattr(
        "uo.scripts.resolve_entrypoints.collect_entrypoint_candidates",
        lambda *_args, **_kwargs: {
            "entrypoint_graph": {
                "version": 2,
                "nodes": [
                    {"id": "node_a", "role": "public_host_entry"},
                    {"id": "node_b", "role": "normal_impl"},
                ],
                "edges": [],
            }
        },
    )
    monkeypatch.setattr(
        "uo.scripts.build_layered_kb.build_layered_kb",
        lambda *_args, **_kwargs: {
            "version": 2,
            "nodes": [
                {"id": "node_a", "role": "public_host_entry"},
                {"id": "node_b", "role": "normal_impl"},
            ],
            "edges": [],
        },
    )
    monkeypatch.setattr("uo.scripts.resolve_entrypoints._apply_link_status", lambda _nodes, _edges: None)
    monkeypatch.setattr(
        "uo.scripts.resolve_entrypoints._evaluate_closure",
        lambda _nodes, _edges, _arch: {"host_main_chain": "closed", "kernel_main_chain": "closed"},
    )
    monkeypatch.setattr("uo.scripts.resolve_entrypoints._build_extraction_units", lambda _nodes, _edges, _arch: [])
