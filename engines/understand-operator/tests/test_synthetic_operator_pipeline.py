"""Generic synthetic AscendC operator coverage for UO scoring/boundary/ledger."""

from __future__ import annotations

import textwrap
from pathlib import Path

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.evidence_score import detect_score_pre
from uo.scripts.extract_operator_boundary import extract_operator_boundary
from uo.scripts.resolve_entrypoints import collect_entrypoint_candidates
from uo.scripts.semantic_resolution_ledger import (
    append_semantic_patch,
    apply_ledger_to_entrypoint_graph,
    load_ledger,
)


def _prep(tmp_path: Path, op_name: str) -> Path:
    root = tmp_path / op_name
    root.mkdir(parents=True)
    uo = root / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True, exist_ok=True)
    run = uo / "runs" / "UO_RUN_SYNTH" / "scope"
    run.mkdir(parents=True, exist_ok=True)
    write_yaml(
        uo / "manifest.yaml",
        {"op_name": op_name, "current_run": "UO_RUN_SYNTH", "current_run_id": "UO_RUN_SYNTH"},
    )
    return root


def _scope(uo: Path, files: list[str]) -> None:
    write_yaml(
        uo / "runs" / "UO_RUN_SYNTH" / "scope" / "scope_confirmed.yaml",
        {
            "confirmed_source_files": [{"path": p} for p in files],
            "confirmed_file_list": [{"path": p} for p in files],
        },
    )


def test_lowercase_global_kernel_or_llm_task(tmp_path: Path) -> None:
    op = "synth_add"
    root = _prep(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    src = root / "op_kernel" / "synth_add_entry.cpp"
    src.parent.mkdir(parents=True)
    src.write_text("__global__ void synth_add_kernel(GM_ADDR x, GM_ADDR y) {}\n", encoding="utf-8")
    _scope(uo, ["op_kernel/synth_add_entry.cpp"])
    doc = collect_entrypoint_candidates(root, op, architecture="arch35")
    graph = doc.get("entrypoint_graph") or doc
    write_yaml(uo / "ir" / "entrypoint_graph.yaml", graph)
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    kernel_nodes = [
        n
        for n in nodes
        if str(n.get("role") or "") == "public_kernel_entry"
        or "global_kernel" in str(n.get("evidence_classes") or n.get("label") or "")
        or str(n.get("symbol") or n.get("name") or "").endswith("_kernel")
    ]
    detect_score_pre(uo, architecture="arch35", run_id="t1")
    tasks = read_yaml(uo / "ir" / "llm_tasks.yaml") or {}
    task_list = [t for t in (tasks.get("tasks") or []) if isinstance(t, dict)]
    assert kernel_nodes or task_list, f"expected kernel node or LLM task; nodes={nodes}"
    for t in task_list:
        cands = t.get("candidates") or []
        if t.get("task_type") in {"choose_edge", "entrypoint_dispatch_bind", "inspect_candidates"}:
            assert cands, f"ungrounded task: {t}"


def test_tiling_callable_neutral(tmp_path: Path) -> None:
    op = "synth_mul"
    root = _prep(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    host = root / "op_host" / "synth_mul_tiling.cpp"
    host.parent.mkdir(parents=True)
    host.write_text(
        textwrap.dedent(
            """
            REG_OP(SynthMul)
            IMPL_OP_OPTILING(SynthMul).Tiling(GetTilingFunc)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    _scope(uo, ["op_host/synth_mul_tiling.cpp"])
    doc = collect_entrypoint_candidates(root, op, architecture="arch35")
    graph = doc.get("entrypoint_graph") or doc
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    roles = {str(n.get("role") or n.get("kind") or "") for n in nodes}
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    tiling_nodes = [n for n in nodes if "tiling" in str(n.get("role") or "").lower() or "tiling" in str(n.get("kind") or "").lower()]
    fluent = [
        e
        for e in edges
        if any(
            (ev.get("macro") == "IMPL_OP_OPTILING.Tiling" or ev.get("reason") == "fluent_tiling")
            for ev in (e.get("evidence") or [])
            if isinstance(ev, dict)
        )
    ]
    assert tiling_nodes or fluent or any("tiling" in r.lower() for r in roles), f"roles={roles} edges={edges}"


def test_opdef_unquoted_and_input_desc_hint(tmp_path: Path) -> None:
    op = "synth_bound"
    root = _prep(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    host = root / "op_host" / "bound.cpp"
    host.parent.mkdir(parents=True)
    host.write_text(
        textwrap.dedent(
            """
            static constexpr int IDX_X = 0;
            OpDef def = OpDef(SynthBound)
                .Input(x)
                .Attr(axis);
            void Host() {
              auto d = context->GetInputDesc(IDX_X);
              auto s = context->GetInputShape(UNBOUND_NAME);
              auto a = context->GetAttr<int64_t>("missing_attr");
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    _scope(uo, ["op_host/bound.cpp"])
    payload = extract_operator_boundary(root, op, architecture="arch35")
    names = [i.get("name") for i in payload.get("inputs") or []]
    assert "x" in names or any(i.get("slot") == 0 for i in payload.get("inputs") or [])
    hints = payload.get("llm_task_hints") or []
    assert hints, "expected io_slot_bind hints for unbound accessors"
    detect_score_pre(uo, architecture="arch35")
    tasks = read_yaml(uo / "ir" / "llm_tasks.yaml") or {}
    assert hints or any(
        t.get("task_type") == "io_slot_bind" for t in (tasks.get("tasks") or []) if isinstance(t, dict)
    )


def test_ledger_refuses_relation_wide_upgrade(tmp_path: Path) -> None:
    op = "synth_ledger"
    root = _prep(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    graph = {
        "version": 2,
        "nodes": [
            {"id": "n1", "role": "host_impl", "confidence": "source_verified"},
            {"id": "n2", "role": "kernel_entry", "confidence": "candidate"},
        ],
        "edges": [
            {
                "id": "e_reg_1",
                "type": "registers",
                "source": "n1",
                "target": "n2",
                "confidence": "candidate",
            },
            {
                "id": "e_reg_2",
                "type": "registers",
                "source": "n1",
                "target": "n2",
                "confidence": "candidate",
            },
        ],
        "closure": {"host_main_chain": "open", "kernel_main_chain": "open"},
    }
    write_yaml(uo / "ir" / "entrypoint_graph.yaml", graph)
    append_semantic_patch(
        uo,
        {
            "patch_id": "p1",
            "accepted_candidate_ids": [],
            "relation": "registers",
            "confidence": "source_verified",
            "source_snapshot_hash": "abc",
        },
    )
    ledger = load_ledger(uo)
    out = apply_ledger_to_entrypoint_graph(graph, ledger)
    assert all(e.get("confidence") == "candidate" for e in (out.get("edges") or []) if isinstance(e, dict))
