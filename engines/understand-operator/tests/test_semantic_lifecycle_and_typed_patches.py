"""Semantic task lifecycle, typed patches, rebuild order, and tx consistency."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from uo.scripts._ir_io import commit_semantic_artifacts, read_yaml, write_yaml
from uo.scripts.llm_tasks import (
    apply_task_patch,
    blocking_gap_tasks,
    compute_semantic_stats,
    load_llm_tasks,
    sync_tasks_from_materialization,
)
from uo.scripts.semantic_patches import (
    apply_patch_to_layers,
    validate_typed_patch,
    verify_patch_against_layers,
)
from uo.scripts.semantic_resolution_ledger import (
    apply_ledger_to_layers,
    load_ledger,
)

RUN_TEST = "RUN_TEST"


def _uo(tmp_path: Path) -> Path:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    return uo


def _tasks_doc(tasks: list[dict[str, Any]], *, total_semantic_batches: int = 0) -> dict[str, Any]:
    return {
        "version": 1,
        "artifact_identity": {"run_id": RUN_TEST, "workflow_id": "uo-init"},
        "active_run_id": RUN_TEST,
        "total_semantic_batches": total_semantic_batches,
        "tasks": tasks,
    }


def _open_task(tid: str = "TASK_life", **extra: Any) -> dict[str, Any]:
    row = {
        "task_id": tid,
        "run_id": RUN_TEST,
        "workflow_id": "uo-init",
        "status": "open",
        "task_status": "open",
        "severity": "blocking",
        "blocking": True,
        "semantic_status": "unresolved",
        "type": "choose_edge",
        "object_type": "call_edge",
        "target": "e_dispatch",
        "candidates": [{"id": "e_dispatch"}],
        "allowed_actions": ["accept_edge", "mark_missing"],
        "source_snapshot_hash": "snap1",
        "candidate_set_hash": "cset1",
        "task_attempts": 0,
    }
    row.update(extra)
    return row


def test_apply_sets_pending_materialization_not_closed(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc([_open_task()]),
    )
    ok = apply_task_patch(
        uo,
        {
            "task_id": "TASK_life",
            "action": "accept_edge",
            "edge_id": "e_dispatch",
            "accepted_candidate_ids": ["e_dispatch"],
            "rejected_candidate_ids": [],
            "source_snapshot_hash": "snap1",
            "candidate_set_hash": "cset1",
            "patch_type": "entrypoint_dispatch_resolution",
            "source_node_id": "n_src",
            "target_node_id": "n_tgt",
            "relation": "dispatches_to",
        },
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert ok["ok"] is True
    task = load_llm_tasks(uo)["tasks"][0]
    assert task["task_status"] == "pending_materialization"
    assert task["semantic_status"] == "pending_materialization"
    assert task["blocking"] is True
    assert task["semantic_status"] != "closed"
    assert len(blocking_gap_tasks(uo, current_run_id=RUN_TEST)) == 1
    ledger = load_ledger(uo)
    assert ledger["semantic_patches"][0]["apply_status"] == "pending"
    assert ledger["semantic_patches"][0]["source_node_id"] == "n_src"
    assert ledger["semantic_patches"][0]["target_node_id"] == "n_tgt"


def test_materialized_closes_task(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc(
            [
                {
                    **_open_task(),
                    "status": "pending_materialization",
                    "task_status": "pending_materialization",
                    "semantic_status": "pending_materialization",
                }
            ],
        ),
    )
    ledger = {
        "version": 1,
        "semantic_patches": [
            {
                "task_id": "TASK_life",
                "run_id": RUN_TEST,
                "control_action_id": "adjudicate_llm_tasks",
                "actor_id": "uo-semantic-resolve",
                "status": "active",
                "action": "accept_edge",
                "patch_type": "edge_resolution",
                "edge_id": "e1",
                "apply_status": "materialized",
            }
        ],
    }
    sync = sync_tasks_from_materialization(uo, ledger, current_run_id=RUN_TEST)
    task = sync["doc"]["tasks"][0]
    assert task["task_status"] == "resolved"
    assert task["semantic_status"] == "closed"
    assert task["blocking"] is False


def test_unconsumed_reopens_blocking(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc(
            [
                {
                    **_open_task(),
                    "status": "pending_materialization",
                    "task_status": "pending_materialization",
                    "semantic_status": "pending_materialization",
                }
            ],
        ),
    )
    ledger = {
        "version": 1,
        "semantic_patches": [
            {
                "task_id": "TASK_life",
                "run_id": RUN_TEST,
                "control_action_id": "adjudicate_llm_tasks",
                "actor_id": "uo-semantic-resolve",
                "status": "active",
                "action": "accept_edge",
                "patch_type": "edge_resolution",
                "edge_id": "missing_edge",
                "apply_status": "unconsumed",
                "apply_error": "SEMANTIC_PATCH_UNCONSUMED",
            }
        ],
    }
    sync = sync_tasks_from_materialization(uo, ledger, current_run_id=RUN_TEST)
    write_yaml(uo / "ir" / "llm_tasks.yaml", sync["doc"])
    task = load_llm_tasks(uo)["tasks"][0]
    assert task["task_status"] == "rework_required"
    assert task["semantic_status"] == "unresolved"
    assert task["blocking"] is True
    assert task["failure_code"] == "SEMANTIC_PATCH_UNCONSUMED"
    assert len(blocking_gap_tasks(uo, current_run_id=RUN_TEST)) == 1


def test_mark_missing_never_closes_gap(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "llm_tasks.yaml",
        _tasks_doc(
            [
                {
                    **_open_task("TASK_mm"),
                    "type": "mark_missing",
                    "candidates": [],
                    "allowed_actions": ["mark_missing"],
                    "candidate_set_hash": "empty",
                }
            ],
        ),
    )
    ok = apply_task_patch(
        uo,
        {
            "task_id": "TASK_mm",
            "action": "mark_missing",
            "source_snapshot_hash": "snap1",
            "candidate_set_hash": "empty",
        },
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert ok["ok"] is True
    task = load_llm_tasks(uo)["tasks"][0]
    assert task["task_status"] == "adjudicated"
    assert task["semantic_status"] == "unresolved"
    assert task["blocking"] is True
    assert len(blocking_gap_tasks(uo, current_run_id=RUN_TEST)) == 1


def test_typed_entrypoint_dispatch_materializes_edge() -> None:
    layers = {
        "entrypoint_graph": {
            "nodes": [{"id": "n_src", "role": "public_host_entry"}, {"id": "n_tgt", "role": "normal_impl"}],
            "edges": [],
        },
        "operator_graph": {"nodes": [], "edges": []},
    }
    patch = {
        "task_id": "T1",
        "run_id": RUN_TEST,
        "patch_type": "entrypoint_dispatch_resolution",
        "action": "accept_edge",
        "source_node_id": "n_src",
        "target_node_id": "n_tgt",
        "relation": "dispatches_to",
        "status": "active",
    }
    assert validate_typed_patch(patch, patch_type="entrypoint_dispatch_resolution")["ok"]
    result = apply_patch_to_layers(layers, patch)
    assert result["ok"] is True
    edges = layers["entrypoint_graph"]["edges"]
    assert len(edges) == 1
    assert edges[0]["type"] == "dispatches_to"
    assert edges[0]["confidence"] == "semantic_verified"
    verified = verify_patch_against_layers(layers, patch)
    assert verified["apply_status"] == "materialized"


def test_typed_tilingdata_bridge_creates_maps_edge() -> None:
    layers = {
        "operator_graph": {
            "nodes": [
                {"id": "HF_fieldA", "role": "HostField"},
                {"id": "KF_fieldA", "role": "KernelField"},
            ],
            "edges": [],
        },
        "bridge": {"tilingdata_bridges": [], "bridge_edges": []},
        "entrypoint_graph": {"nodes": [], "edges": []},
    }
    patch = {
        "task_id": "T_bridge",
        "run_id": RUN_TEST,
        "patch_type": "tilingdata_bridge_resolution",
        "action": "accept_edge",
        "host_field_id": "HF_fieldA",
        "kernel_field_id": "KF_fieldA",
        "owning_type": "FooTilingData",
        "field_path": "tilingData.fieldA",
        "unit_id": "unit_host",
        "relation": "maps_tilingdata",
        "status": "active",
    }
    assert validate_typed_patch(patch, patch_type="tilingdata_bridge_resolution")["ok"]
    result = apply_patch_to_layers(layers, patch)
    assert result["ok"] is True
    edges = layers["operator_graph"]["edges"]
    assert any(e.get("type") == "maps_tilingdata" for e in edges)
    assert any(
        b.get("host_field_id") == "HF_fieldA" and b.get("kernel_field_id") == "KF_fieldA"
        for b in layers["bridge"]["tilingdata_bridges"]
    )
    assert verify_patch_against_layers(layers, patch)["apply_status"] == "materialized"


def test_typed_call_edge_and_template_and_node() -> None:
    layers = {
        "operator_graph": {
            "nodes": [
                {"id": "fn_caller", "role": "HostFunction"},
                {"id": "fn_callee", "role": "HostFunction"},
                {"id": "tk_v", "role": "TilingKeyValue"},
                {"id": "tpl_i", "role": "TemplateInstance"},
                {"id": "kern_e", "role": "KernelEntry"},
                {"id": "node_ep", "role": "public_host_entry", "confidence": "candidate"},
            ],
            "edges": [],
        },
        "entrypoint_graph": {
            "nodes": [
                {"id": "tk_v", "role": "TilingKeyValue"},
                {"id": "tpl_i", "role": "TemplateInstance"},
                {"id": "kern_e", "role": "KernelEntry"},
                {"id": "node_ep", "role": "public_host_entry", "confidence": "candidate"},
            ],
            "edges": [],
        },
        "host_subgraph": {"nodes": [{"id": "fn_caller"}, {"id": "fn_callee"}], "edges": []},
    }
    call_patch = {
        "task_id": "T_call",
        "run_id": RUN_TEST,
        "patch_type": "call_edge_resolution",
        "caller_function_id": "fn_caller",
        "callee_function_id": "fn_callee",
        "callsite": {"file_path": "op_host/x.cpp", "line": 42},
        "status": "active",
        "action": "accept_edge",
    }
    assert apply_patch_to_layers(layers, call_patch)["ok"]
    assert verify_patch_against_layers(layers, call_patch)["apply_status"] == "materialized"

    tpl_patch = {
        "task_id": "T_tpl",
        "run_id": RUN_TEST,
        "patch_type": "template_instance_resolution",
        "tilingkey_value_id": "tk_v",
        "template_instance_id": "tpl_i",
        "kernel_entry_id": "kern_e",
        "status": "active",
        "action": "accept_edge",
    }
    assert apply_patch_to_layers(layers, tpl_patch)["ok"]
    assert verify_patch_against_layers(layers, tpl_patch)["apply_status"] == "materialized"

    node_patch = {
        "task_id": "T_node",
        "run_id": RUN_TEST,
        "patch_type": "entrypoint_node_resolution",
        "node_id": "node_ep",
        "status": "active",
        "action": "accept_edge",
    }
    assert apply_patch_to_layers(layers, node_patch)["ok"]
    assert verify_patch_against_layers(layers, node_patch)["apply_status"] == "materialized"


def test_semantic_tx_rolls_back_when_second_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uo = _uo(tmp_path)
    write_yaml(uo / "ir" / "llm_tasks.yaml", _tasks_doc([_open_task()]))
    write_yaml(
        uo / "ir" / "semantic_resolution_ledger.yaml",
        {"version": 1, "artifact_identity": {"run_id": RUN_TEST, "workflow_id": "uo-init"}, "semantic_patches": []},
    )
    before_tasks = (uo / "ir" / "llm_tasks.yaml").read_text(encoding="utf-8")
    before_ledger = (uo / "ir" / "semantic_resolution_ledger.yaml").read_text(encoding="utf-8")

    real_replace = __import__("os").replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        # Fail on the second dest replace (after first succeeded).
        if Path(dst).name == "semantic_resolution_ledger.yaml":
            raise OSError("simulated write failure")
        return real_replace(src, dst)

    monkeypatch.setattr("os.replace", flaky_replace)

    with pytest.raises(OSError):
        commit_semantic_artifacts(
            uo,
            llm_tasks=_tasks_doc([{"task_id": "CHANGED", "run_id": RUN_TEST}], total_semantic_batches=9),
            ledger={
                "version": 1,
                "artifact_identity": {"run_id": RUN_TEST, "workflow_id": "uo-init"},
                "semantic_patches": [
                    {
                        "task_id": "CHANGED",
                        "run_id": RUN_TEST,
                        "control_action_id": "adjudicate_llm_tasks",
                        "actor_id": "uo-semantic-resolve",
                    }
                ],
            },
            apply_report={"patches": [{"task_id": "CHANGED"}]},
        )

    # Transactional restore: original tasks + ledger preserved; no apply_report.
    assert (uo / "ir" / "llm_tasks.yaml").read_text(encoding="utf-8") == before_tasks
    assert (uo / "ir" / "semantic_resolution_ledger.yaml").read_text(encoding="utf-8") == before_ledger
    assert not (uo / "ir" / "semantic_apply_report.yaml").is_file()


def test_apply_ledger_to_layers_does_not_only_upgrade_confidence() -> None:
    layers = {
        "entrypoint_graph": {
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"id": "unrelated", "type": "calls", "source": "x", "target": "y", "confidence": "candidate"}],
        },
        "operator_graph": {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []},
    }
    ledger = {
        "semantic_patches": [
            {
                "task_id": "T",
                "run_id": RUN_TEST,
                "control_action_id": "adjudicate_llm_tasks",
                "actor_id": "uo-semantic-resolve",
                "status": "active",
                "action": "accept_edge",
                "patch_type": "entrypoint_dispatch_resolution",
                "source_node_id": "a",
                "target_node_id": "b",
                "relation": "dispatches_to",
            }
        ]
    }
    apply_ledger_to_layers(layers, ledger)
    types = [e.get("type") for e in layers["entrypoint_graph"]["edges"]]
    assert "dispatches_to" in types
    # Unrelated edge must not be the only thing touched / upgraded as a substitute.
    unrelated = next(e for e in layers["entrypoint_graph"]["edges"] if e.get("id") == "unrelated")
    assert unrelated.get("confidence") == "candidate"
