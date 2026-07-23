"""Input-reachable pruning and human/LLM --focus KEY selection."""

from __future__ import annotations

from testcase_agent.atom_bind import is_out_of_scope_runtime_entity
from testcase_agent.planner import (
    apply_input_reachable_filter,
    build_semantic_focus,
    filter_obligations_by_focus,
)


def test_loopid_blockid_are_loop_local() -> None:
    assert is_out_of_scope_runtime_entity(name="loopId") == "LOOP_LOCAL"
    assert is_out_of_scope_runtime_entity(name="blockId") == "LOOP_LOCAL"
    assert is_out_of_scope_runtime_entity(condition="if (block_id == 0)") == "LOOP_LOCAL"


def test_apply_input_reachable_drops_not_derivable_and_loop_local() -> None:
    files = {
        "ir/input_derivable.yaml": {
            "keys": {
                "KEY_LOCAL": {"input_derivable": False, "not_input_derivable": True},
                "KEY_OK": {"input_derivable": True},
            }
        },
        "tiling/key_space.yaml": {"fields": [{"id": "KEY_OK"}, {"id": "KEY_LOCAL"}]},
    }
    obligations = [
        {
            "id": "a",
            "kind": "tiling_key_field_value",
            "target_refs": ["KEY_LOCAL"],
            "field": "KEY_LOCAL",
        },
        {
            "id": "b",
            "kind": "tiling_key_field_value",
            "target_refs": ["KEY_OK"],
            "field": "KEY_OK",
        },
        {
            "id": "c",
            "kind": "kernel_branch",
            "name": "taskId > 0",
            "condition": "taskId > 0",
            "target_refs": ["KBR_X"],
        },
    ]
    kept, stats = apply_input_reachable_filter(obligations, files)
    assert {item["id"] for item in kept} == {"b"}
    assert stats["dropped_not_input_derivable"] == 1
    assert stats["dropped_loop_local_or_platform"] == 1


def test_focus_keeps_only_selected_keys() -> None:
    files = {
        "ir/input_derivable.yaml": {"keys": {"KEY_OK": {"input_derivable": True}, "KEY_OTHER": {"input_derivable": True}}},
        "tiling/key_space.yaml": {"fields": [{"id": "KEY_OK"}, {"id": "KEY_OTHER"}]},
    }
    focus = build_semantic_focus(files, "L0", "KEY_OK")
    assert any(item.get("field_ref") == "KEY_OK" for item in focus["tiling_key_predicates"])
    obligations = [
        {
            "id": "a",
            "kind": "tiling_key_field_value",
            "target_refs": ["KEY_OTHER"],
            "field": "KEY_OTHER",
            "priority": "high",
            "status": "pending",
        },
        {
            "id": "b",
            "kind": "tiling_key_field_value",
            "target_refs": ["KEY_OK"],
            "field": "KEY_OK",
            "priority": "high",
            "status": "pending",
        },
    ]
    assert [item["id"] for item in filter_obligations_by_focus(obligations, focus)] == ["b"]


def test_empty_focus_keeps_all() -> None:
    focus = build_semantic_focus({}, "L0", "")
    obligations = [
        {"id": "a", "kind": "tiling_key_field_value", "target_refs": ["KEY_A"], "priority": "high", "status": "pending"},
        {"id": "b", "kind": "tiling_key_field_value", "target_refs": ["KEY_B"], "priority": "high", "status": "pending"},
    ]
    assert len(filter_obligations_by_focus(obligations, focus)) == 2
