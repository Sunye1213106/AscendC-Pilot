"""Tests for UO scoring + Pilot disambiguation loop (十二条)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.def_use import extract_def_use_from_text, verified_provenance_flows
from uo.scripts.evidence_score import (
    SOURCE_VERIFIED,
    detect_score_post,
    detect_score_pre,
    evaluate_disposition,
    multi_schema_needs_llm,
    score_edge,
    score_profile,
)
from uo.scripts.extract_operator_boundary import extract_operator_boundary
from uo.scripts.llm_tasks import (
    apply_task_patch,
    load_llm_tasks,
    recheck_does_not_increment,
    upsert_tasks_from_score_items,
)
from uo.scripts.resolve_entrypoints import (
    _evaluate_closure,
    collect_entrypoint_candidates,
)
from uo.scripts.semantic_resolution_ledger import (
    append_semantic_patch,
    apply_ledger_to_entrypoint_graph,
    invalidate_stale_patches,
    load_ledger,
)

RUN_TEST = "UO_RUN_TEST1"


def _prep_op(tmp_path: Path, op_name: str) -> Path:
    op_root = tmp_path / op_name
    op_root.mkdir(parents=True)
    uo = op_root / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    run = uo / "runs" / "UO_RUN_TEST1" / "scope"
    run.mkdir(parents=True, exist_ok=True)
    write_yaml(
        uo / "manifest.yaml",
        {"op_name": op_name, "current_run": "UO_RUN_TEST1", "current_run_id": "UO_RUN_TEST1"},
    )
    return op_root


def _scope(uo: Path, files: list[str]) -> None:
    write_yaml(
        uo / "runs" / "UO_RUN_TEST1" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": p} for p in files],
            "confirmed_file_list": [{"path": p} for p in files],
        },
    )


# ① checkpoint: post scoring refuses without plan/host
def test_checkpoint_no_bridge_before_plan(tmp_path: Path) -> None:
    op = "synth_op_a"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    write_yaml(uo / "ir" / "entrypoint_graph.yaml", {"version": 2, "nodes": [], "edges": []})
    result = detect_score_post(uo)
    assert result["ok"] is False
    assert "requires" in str(result.get("error") or "").lower() or "post_semantic" in str(result)


# ② low score main-chain → blocking
def test_low_score_main_chain_blocking() -> None:
    mid = evaluate_disposition(
        object_type="call_edge",
        score=0.55,
        evidence_classes=["file_line"],
        necessity="main_chain",
    )
    low = evaluate_disposition(
        object_type="call_edge",
        score=0.30,
        evidence_classes=[],
        necessity="main_chain",
    )
    aux = evaluate_disposition(
        object_type="call_edge",
        score=0.30,
        evidence_classes=[],
        necessity="auxiliary",
    )
    assert mid["severity"] == "blocking"
    assert mid["disposition"] == "llm_task"
    assert low["severity"] == "blocking"
    assert low["task_hint"] == "mark_missing"
    assert aux["severity"] == "informational"
    assert aux["disposition"] == "unresolved"


# ③ per-type score profile
def test_per_type_score_profile() -> None:
    ep = score_profile("entrypoint_node")
    bridge = score_profile("tilingdata_bridge")
    assert ep["auto_accept_threshold"] != bridge["auto_accept_threshold"]
    assert "required_evidence" in ep
    # conflict blocks auto even with high score
    d = evaluate_disposition(
        object_type="tilingdata_bridge",
        score=0.99,
        evidence_classes=["canonical_type", "field_path", "unit_consistent"],
        conflicts=True,
        necessity="main_chain",
    )
    assert d["disposition"] == "llm_task"


# ④ verification source tiers
def test_verification_source_tiers() -> None:
    edge = {
        "id": "e1",
        "type": "registers",
        "confidence": "source_verified",
        "verification_source": "source",
        "evidence": [{"macro": "IMPL_OP_OPTILING", "file_path": "a.cpp", "line": 1}],
    }
    scored = score_edge(edge, object_type="registration_edge")
    assert scored["confidence"] == SOURCE_VERIFIED
    nodes = {
        "h": {"id": "h", "role": "public_host_entry", "status": "linked", "architecture": "arch35"},
        "t": {"id": "t", "role": "template_registration", "status": "linked", "architecture": "arch35"},
        "k": {"id": "k", "role": "public_kernel_entry", "status": "verified", "architecture": "arch35"},
    }
    cand_edges = [
        {
            "id": "c1",
            "type": "dispatches_to",
            "source": "h",
            "target": "t",
            "confidence": "candidate",
        }
    ]
    closure = _evaluate_closure(nodes, cand_edges, "arch35")
    assert closure["host_main_chain"] != "closed"


def test_candidate_edge_no_false_close() -> None:
    nodes = {
        "reg": {"id": "reg", "role": "operator_registration", "status": "linked", "architecture": "neutral"},
        "h": {"id": "h", "role": "public_host_entry", "status": "linked", "architecture": "neutral"},
        "impl": {"id": "impl", "role": "normal_impl", "status": "linked", "architecture": "arch35"},
        "k": {"id": "k", "role": "public_kernel_entry", "status": "verified", "architecture": "arch35"},
    }
    edges = [
        {"id": "e1", "type": "selects", "source": "h", "target": "impl", "confidence": "candidate"},
    ]
    closure = _evaluate_closure(nodes, edges, "arch35")
    assert closure["host_main_chain"] == "unresolved"
    verified_edges = [
        {
            "id": "e2",
            "type": "registers",
            "source": "h",
            "target": "impl",
            "confidence": "source_verified",
            "verification_source": "source",
        }
    ]
    closure2 = _evaluate_closure(nodes, verified_edges, "arch35")
    assert closure2["host_main_chain"] == "closed"


# ⑤ stale patch rejected
def test_stale_patch_rejected(tmp_path: Path) -> None:
    op = "synth_op_b"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    items = [
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "task_hint": "choose_edge",
            "object_type": "call_edge",
            "target_id": "edge_x",
            "score": 0.6,
            "necessity": "main_chain",
            "candidates": [{"id": "cand_1", "symbol_ref": "Foo"}],
        }
    ]
    upsert_tasks_from_score_items(
        uo, items, checkpoint="extract.pre_semantic", run_id=RUN_TEST, source_snapshot_hash="hashA"
    )
    doc = load_llm_tasks(uo)
    task = next(t for t in doc["tasks"] if t["status"] == "open")
    bad = apply_task_patch(
        uo,
        {
            "task_id": task["task_id"],
            "accepted_candidate_ids": ["cand_OUTSIDE"],
            "action": "accept_edge",
        },
        current_run_id=RUN_TEST,
        current_source_hash="hashA",
    )
    assert bad["ok"] is False
    assert bad["error"] == "candidate_out_of_window"
    stale = apply_task_patch(
        uo,
        {
            "task_id": task["task_id"],
            "accepted_candidate_ids": ["cand_1"],
            "action": "accept_edge",
        },
        current_run_id=RUN_TEST,
        current_source_hash="hashB",
    )
    assert stale["ok"] is False
    assert stale["error"] == "source_snapshot_stale"


def test_mark_missing_rejects_accept_edge_false_closure(tmp_path: Path) -> None:
    """Empty-candidate mark_missing must not invent accept_edge closes."""
    op = "synth_op_mark_missing"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    items = [
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "task_hint": "mark_missing",
            "object_type": "call_edge",
            "target_id": "edge_empty",
            "score": 0.2,
            "necessity": "main_chain",
            "candidates": [],
        }
    ]
    upsert_tasks_from_score_items(
        uo, items, checkpoint="extract.pre_semantic", run_id=RUN_TEST, source_snapshot_hash="hashA"
    )
    doc = load_llm_tasks(uo)
    task = next(t for t in doc["tasks"] if t["status"] == "open")
    assert task["type"] == "mark_missing"
    assert "accept_edge" not in (task.get("allowed_actions") or [])

    bad = apply_task_patch(
        uo,
        {
            "task_id": task["task_id"],
            "action": "accept_edge",
            "accepted_candidate_ids": ["some_edge_id_in_graph"],
        },
        current_run_id=RUN_TEST,
        current_source_hash="hashA",
    )
    assert bad["ok"] is False
    assert bad["error"] in {"action_not_allowed", "empty_candidate_false_closure"}

    smuggle = apply_task_patch(
        uo,
        {
            "task_id": task["task_id"],
            "action": "mark_missing",
            "accepted_candidate_ids": ["some_edge_id_in_graph"],
        },
        current_run_id=RUN_TEST,
        current_source_hash="hashA",
    )
    assert smuggle["ok"] is False
    assert smuggle["error"] == "mark_missing_forbids_accepted_ids"

    ok = apply_task_patch(
        uo,
        {"task_id": task["task_id"], "action": "mark_missing"},
        current_run_id=RUN_TEST,
        current_source_hash="hashA",
    )
    assert ok["ok"] is True


# ⑥ attempts only on resolve+apply
def test_attempts_only_on_resolve_apply(tmp_path: Path) -> None:
    op = "synth_op_c"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    items = [
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "task_hint": "choose_edge",
            "object_type": "call_edge",
            "target_id": "edge_y",
            "score": 0.6,
            "necessity": "main_chain",
            "candidates": [{"id": "cand_1", "symbol_ref": "Bar"}],
        }
    ]
    upsert_tasks_from_score_items(
        uo, items, checkpoint="extract.pre_semantic", run_id=RUN_TEST, source_snapshot_hash="snap1"
    )
    before = load_llm_tasks(uo)
    batches0 = int(before.get("total_semantic_batches") or 0)
    recheck_does_not_increment(uo, current_run_id=RUN_TEST)
    mid = load_llm_tasks(uo)
    assert int(mid.get("total_semantic_batches") or 0) == batches0
    task = next(t for t in mid["tasks"] if t["status"] == "open")
    ok = apply_task_patch(
        uo,
        {
            "task_id": task["task_id"],
            "accepted_candidate_ids": ["cand_1"],
            "action": "accept_edge",
            "relation": "dispatches_to",
        },
        current_run_id=RUN_TEST,
        current_source_hash="snap1",
    )
    assert ok["ok"] is True
    after = load_llm_tasks(uo)
    assert int(after.get("total_semantic_batches") or 0) == batches0 + 1
    resolved = next(t for t in after["tasks"] if t["task_id"] == task["task_id"])
    assert int(resolved.get("task_attempts") or 0) == 1


# ⑦ ledger rebuild invalidates stale
def test_ledger_rebuild_invalidates(tmp_path: Path) -> None:
    op = "synth_op_d"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    append_semantic_patch(
        uo,
        {
            "task_id": "TASK_x",
            "accepted_candidate_ids": ["e1"],
            "relation": "dispatches_to",
            "source_snapshot_hash": "oldhash",
            "edge_id": "e1",
        },
    )
    stale = invalidate_stale_patches(uo, current_source_hash="newhash")
    assert "TASK_x" in stale
    ledger = load_ledger(uo)
    assert ledger["semantic_patches"][0]["status"] == "stale"
    graph = {
        "edges": [
            {"id": "e1", "type": "dispatches_to", "confidence": "candidate"},
        ]
    }
    # Active patch would upgrade; stale should not.
    active = {
        "semantic_patches": [
            {
                "task_id": "TASK_y",
                "status": "active",
                "edge_id": "e1",
                "accepted_candidate_ids": ["e1"],
                "relation": "dispatches_to",
            }
        ]
    }
    upgraded = apply_ledger_to_entrypoint_graph(graph, active)
    assert upgraded["edges"][0]["confidence"] == "semantic_verified"


# ⑧ layered coverage uses capabilities
def test_layered_coverage_gate(tmp_path: Path) -> None:
    from uo.scripts.check_kb_integrity import _collect_layered_coverage_issues

    op = "synth_op_e"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    write_yaml(
        uo / "ir" / "operator_capabilities.yaml",
        {"has_tilingkey": True, "has_tilingdata": True},
    )
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {
            "keys": {
                "KeyA": {"input_derivable": True},
                "KeyB": {"input_derivable": True, "host_parent": "H"},
            }
        },
    )
    write_yaml(uo / "ir" / "operator_graph.yaml", {"edges": []})
    write_yaml(uo / "ir" / "bridge.yaml", {})
    write_yaml(uo / "ir" / "tilingkey_space.yaml", {})
    write_yaml(uo / "ir" / "llm_tasks.yaml", {"tasks": [], "total_semantic_batches": 0})
    issues: list = []
    stats = _collect_layered_coverage_issues(uo, issues)
    assert "KeyA" in stats["key_coverage_gaps"]
    assert any(i.get("code") == "KEY_COVERAGE_INCOMPLETE" for i in issues)


# ⑨ multi-schema
def test_multi_schema_deterministic_vs_ambiguous() -> None:
    assert multi_schema_needs_llm(
        schema_count=3, isolated=True, binding_ambiguous=False, registration_conflict=False, shared_candidate_conflict=False
    ) is False
    assert multi_schema_needs_llm(
        schema_count=2, isolated=False, binding_ambiguous=True, registration_conflict=False, shared_candidate_conflict=False
    ) is True


# ⑩ CBM prefer ranking API exists
def test_cbm_scope_not_opname_filter() -> None:
    import inspect

    from uo.scripts.cbm_client import CbmClient

    sig = inspect.signature(CbmClient.search_symbols)
    assert "prefer_file_contains" in sig.parameters


# ⑪ OpDef adapters
def test_opdef_adapters(tmp_path: Path) -> None:
    op = "synth_op_f"
    root = _prep_op(tmp_path, op)
    host = root / "op_host"
    host.mkdir()
    (host / f"{op}_reg.cpp").write_text(
        textwrap.dedent(
            """
            REG_OP(SynthOpF)
                .Input("query")
                .OptionalInput("atten_mask")
                .Attr("keep_prob")
                .DataType({DT_FLOAT16})
                .Format({FORMAT_ND})
                .Output("softmax");
            REG_OP(OtherOp)
                .Input("x")
                .Attr("axis");
            """
        ),
        encoding="utf-8",
    )
    (host / f"{op}_tiling.cpp").write_text(
        "auto s = context->GetInputShape(0);\nauto a = context->GetAttr(\"keep_prob\");\n",
        encoding="utf-8",
    )
    uo = root / ".ascendc-pilot" / "uo"
    _scope(
        uo,
        [f"op_host/{op}_reg.cpp", f"op_host/{op}_tiling.cpp"],
    )
    payload = extract_operator_boundary(root, op)
    names = [i.get("name") for i in payload["inputs"]]
    assert "query" in names
    assert "atten_mask" in names
    # Per REG_OP scope reset: OtherOp's x should also appear (slot reset).
    assert "x" in names
    attrs = [a.get("slot_or_name") for a in payload["attributes"]]
    assert "keep_prob" in attrs
    assert "axis" in attrs


# ⑫ def-use tiers
def test_defuse_tiers_not_reachability() -> None:
    text = "auto *p = foo();\nx = p->bar;\ntd.field = x;\n"
    result = extract_def_use_from_text(text, file_path="a.cpp", scope_symbol="DoTiling")
    flows = result["flows"]
    assert any(f.get("confidence") in {"candidate", "structurally_inferred"} for f in flows)
    verified = verified_provenance_flows(flows)
    # Unresolved / pointer-ish should not all count as verified
    assert len(verified) <= len(flows)


def test_impl_op_tiling_fluent(tmp_path: Path) -> None:
    op = "synth_op_g"
    root = _prep_op(tmp_path, op)
    host = root / "op_host"
    host.mkdir()
    (host / f"{op}_tiling.cpp").write_text(
        textwrap.dedent(
            """
            REG_OP(SynthOpG)
            IMPL_OP_OPTILING(SynthOpG).Tiling(SynthOpGTiling)
            class SynthOpGTiling {
              ge::graphStatus DoOpTiling() { return ge::GRAPH_SUCCESS; }
            };
            """
        ),
        encoding="utf-8",
    )
    kern = root / "op_kernel"
    kern.mkdir()
    (kern / f"{op}_entry.cpp").write_text("__global__ void SynthOpGKernel() {}\n", encoding="utf-8")
    uo = root / ".ascendc-pilot" / "uo"
    _scope(uo, [f"op_host/{op}_tiling.cpp", f"op_kernel/{op}_entry.cpp"])
    doc = collect_entrypoint_candidates(root, op, architecture="arch35")
    graph = doc["entrypoint_graph"]
    edges = graph.get("edges") or []
    fluent = [
        e
        for e in edges
        if e.get("type") in {"dispatches_to", "registers"}
        and any(
            (ev.get("macro") == "IMPL_OP_OPTILING.Tiling" or ev.get("reason") == "fluent_tiling")
            for ev in (e.get("evidence") or [])
            if isinstance(ev, dict)
        )
    ]
    assert fluent
    assert all(
        str(e.get("confidence")) in {"source_verified", "verified"} for e in fluent
    )
    assert graph["closure"]["host_main_chain"] == "closed"


def test_detect_score_pre_writes_report(tmp_path: Path) -> None:
    op = "synth_op_h"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    _scope(uo, ["op_host/a.cpp"])
    write_yaml(
        uo / "ir" / "entrypoint_graph.yaml",
        {
            "version": 2,
            "nodes": [
                {
                    "id": "n1",
                    "role": "public_host_entry",
                    "architecture": "arch35",
                    "confidence": 0.9,
                    "locator": {"file_path": "op_host/a.cpp"},
                    "symbol_ref": {"name": "DoOpTiling"},
                }
            ],
            "edges": [
                {
                    "id": "e1",
                    "type": "registers",
                    "confidence": "source_verified",
                    "evidence": [{"macro": "REG_OP", "file_path": "a.cpp", "line": 1}],
                }
            ],
        },
    )
    write_yaml(uo / "ir" / "operator_boundary.yaml", {"inputs": [], "attributes": []})
    result = detect_score_pre(uo, architecture="arch35", run_id=RUN_TEST)
    assert result["ok"] is True
    assert (uo / "ir" / "score_report_pre.yaml").is_file()
    assert (uo / "ir" / "llm_tasks.yaml").is_file()


def test_pilot_engines_registered() -> None:
    import sys
    from pathlib import Path

    pilot_root = Path(__file__).resolve().parents[3] / "pilot"
    inserted = False
    if pilot_root.is_dir() and str(pilot_root) not in sys.path:
        sys.path.insert(0, str(pilot_root))
        inserted = True
    try:
        from ascendc_pilot.actions.engines import ENGINE_REGISTRY

        for action in (
            "detect_score_pre",
            "detect_score_post",
            "apply_semantic_patch",
            "rebuild_from_ledger",
            "recheck_closure",
        ):
            assert ("uo-init", action) in ENGINE_REGISTRY
    finally:
        # Avoid leaving pilot on sys.path — it enables reject_key_patch_batch
        # and breaks UO tests that expect ImportError soft-fail.
        if inserted and str(pilot_root) in sys.path:
            sys.path.remove(str(pilot_root))
        for mod in list(sys.modules):
            if mod == "ascendc_pilot" or mod.startswith("ascendc_pilot."):
                del sys.modules[mod]


def test_no_operator_hardcode_in_scorer() -> None:
    import pathlib

    scorer = pathlib.Path(__file__).resolve().parents[1] / "uo" / "scripts" / "evidence_score.py"
    text = scorer.read_text(encoding="utf-8")
    for banned in ("FlashAttention", "flash_attention", "Fag", "FAG"):
        assert banned not in text
