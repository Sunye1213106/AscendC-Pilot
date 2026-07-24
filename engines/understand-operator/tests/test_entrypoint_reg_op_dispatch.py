"""Entrypoint REG_OP / kernel dispatch production tests."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.evidence_score import score_tilingdata_bridge
from uo.scripts.llm_tasks import upsert_tasks_from_score_items, load_llm_tasks
from uo.scripts.resolve_entrypoints import collect_entrypoint_candidates
from uo.scripts.source_path import resolve_repo_source_path


def _prep_op(tmp_path: Path, op_name: str) -> Path:
    root = tmp_path / op_name
    root.mkdir(parents=True)
    uo = root / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    run = uo / "runs" / "UO_RUN_EP1" / "scope"
    run.mkdir(parents=True)
    write_yaml(uo / "manifest.yaml", {"op_name": op_name, "current_run": "UO_RUN_EP1"})
    return root


def _scope(uo: Path, files: list[str]) -> None:
    write_yaml(
        uo / "runs" / "UO_RUN_EP1" / "scope" / "scope_confirmed.yaml",
        {"confirmed_source_files": [{"path": p} for p in files]},
    )


def test_reg_op_from_op_graph_is_bound_to_current_operator(tmp_path: Path) -> None:
    op = "demo_attn_op"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    proto = root / "op_graph" / "demo_attn_op_proto.h"
    proto.parent.mkdir(parents=True)
    proto.write_text("REG_OP(DemoAttnOp)\nREG_OP(OtherOp)\n", encoding="utf-8")
    host = root / "op_host" / "demo_attn_op_tiling.cpp"
    host.parent.mkdir(parents=True)
    host.write_text(
        "IMPL_OP_OPTILING(DemoAttnOp).Tiling(DemoAttnOpTiling);\n"
        "class DemoAttnOpTiling {};\n",
        encoding="utf-8",
    )
    # Prefixed confirmed paths (CBM style) must still resolve.
    _scope(
        uo,
        [
            f"{op}/op_graph/demo_attn_op_proto.h",
            f"{op}/op_host/demo_attn_op_tiling.cpp",
        ],
    )
    assert resolve_repo_source_path(root, f"{op}/op_graph/demo_attn_op_proto.h") == proto.resolve()
    doc = collect_entrypoint_candidates(root, op, architecture="arch35")
    graph = doc["entrypoint_graph"]
    regs = [n for n in graph["nodes"] if n.get("role") == "operator_registration"]
    assert len(regs) == 1
    assert regs[0]["name"] == "DemoAttnOp"
    assert "OtherOp" not in {n["name"] for n in regs}
    hosts = [n for n in graph["nodes"] if n.get("role") == "public_host_entry" and n.get("name") == "DemoAttnOp"]
    assert hosts
    assert graph["closure"]["host_main_chain"] == "closed"


def test_registration_file_in_confirmed_scope(tmp_path: Path) -> None:
    op = "scope_reg_op"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    proto = root / "op_graph" / "scope_reg_op_proto.h"
    proto.parent.mkdir(parents=True)
    proto.write_text("REG_OP(ScopeRegOp)\n", encoding="utf-8")
    host = root / "op_host" / "scope_reg_op_tiling.cpp"
    host.parent.mkdir(parents=True)
    host.write_text(
        "IMPL_OP_OPTILING(ScopeRegOp).Tiling(ScopeRegOpTiling);\nstruct ScopeRegOpTiling {};\n",
        encoding="utf-8",
    )
    _scope(uo, [f"{op}/op_graph/scope_reg_op_proto.h", f"{op}/op_host/scope_reg_op_tiling.cpp"])
    doc = collect_entrypoint_candidates(root, op, architecture="arch35")
    regs = [n for n in doc["entrypoint_graph"]["nodes"] if n.get("macro") == "REG_OP"]
    assert regs
    fp = str((regs[0].get("locator") or {}).get("file_path") or "")
    assert "op_graph" in fp.replace("\\", "/")


def test_public_host_chain_closes_with_verified_registration(tmp_path: Path) -> None:
    op = "host_chain_op"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    (root / "op_graph").mkdir(parents=True)
    (root / "op_graph" / "host_chain_op_proto.h").write_text("REG_OP(HostChainOp)\n", encoding="utf-8")
    (root / "op_host").mkdir(parents=True)
    (root / "op_host" / "host_chain_op_tiling.cpp").write_text(
        "IMPL_OP_OPTILING(HostChainOp).Tiling(HostChainOpTiling);\n"
        "class HostChainOpTiling {};\n",
        encoding="utf-8",
    )
    _scope(
        uo,
        [
            "op_graph/host_chain_op_proto.h",
            "op_host/host_chain_op_tiling.cpp",
        ],
    )
    graph = collect_entrypoint_candidates(root, op, architecture="arch35")["entrypoint_graph"]
    assert graph["closure"]["host_main_chain"] == "closed"
    verified = [
        e
        for e in graph["edges"]
        if e.get("type") == "registers" and str(e.get("confidence") or "").endswith("verified")
    ]
    assert verified


def test_kernel_dispatch_has_real_candidates(tmp_path: Path) -> None:
    op = "kern_disp_op"
    root = _prep_op(tmp_path, op)
    uo = root / ".ascendc-pilot" / "uo"
    kdir = root / "op_kernel" / "arch35"
    kdir.mkdir(parents=True)
    # Use the preferred KernelEntry symbol name so entry survives materialization,
    # plus a concrete *Kernel impl for dispatch linking.
    (kdir / "kern_disp_op_entry.h").write_text(
        "__global__ void KernelEntry() {}\n",
        encoding="utf-8",
    )
    (kdir / "kern_disp_op_kernel.h").write_text(
        "class KernDispOpKernel {};\n",
        encoding="utf-8",
    )
    _scope(
        uo,
        [
            "op_kernel/arch35/kern_disp_op_entry.h",
            "op_kernel/arch35/kern_disp_op_kernel.h",
        ],
    )
    graph = collect_entrypoint_candidates(root, op, architecture="arch35")["entrypoint_graph"]
    dispatches = [e for e in graph["edges"] if e.get("type") == "dispatches_to"]
    # Either verified unique link or grounded multi-candidate edges with file_path evidence.
    assert dispatches
    assert all((e.get("evidence") or [{}])[0].get("file_path") or e.get("confidence") for e in dispatches)
    # Name-only unique match must stay candidate (not fake source_verified).
    for e in dispatches:
        reasons = [str((ev or {}).get("reason") or "") for ev in (e.get("evidence") or [])]
        if any("name_match" in r for r in reasons):
            assert e.get("confidence") == "candidate"
            assert e.get("verification_source") == "heuristic"


def test_empty_dispatch_candidates_route_to_enrichment(tmp_path: Path) -> None:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    items = [
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "task_hint": "choose_edge",
            "object_type": "call_edge",
            "target_id": "edge_no_cands",
            "score": 0.3,
            "necessity": "main_chain",
            "candidates": [],
        }
    ]
    upsert_tasks_from_score_items(uo, items, checkpoint="pre", source_snapshot_hash="s1")
    task = load_llm_tasks(uo)["tasks"][0]
    assert task["type"] in {"evidence_enrichment", "candidate_generation", "mark_missing"}
    assert task["type"] != "choose_edge"
    assert "accept_edge" not in (task.get("allowed_actions") or [])


def test_no_mass_blocking_tasks_from_leaf_only_fields() -> None:
    leaf = {
        "field_path": "castBufferLen",
        "host_writer": "TDF_CASTBUFFERLEN",
        "canonical_type": "",
        "required": True,  # default-ish; without main_chain + identity → not blocking mass
    }
    scored = score_tilingdata_bridge(leaf)
    assert scored.get("task_hint") != "choose_edge"
    assert scored.get("severity") != "blocking" or scored.get("necessity") == "main_chain"
    # Leaf-only incomplete identity defaults to degraded enrichment.
    assert scored.get("severity") == "degraded"
    assert scored.get("task_hint") == "evidence_enrichment"


def test_bridge_candidate_generation_includes_owning_type() -> None:
    bridge = {
        "field_path": "x",
        "owning_type": "FasgTilingData",
        "canonical_type": "FasgTilingData",
        "unit_id": "unit_host_1",
        "host_writer": "SaveX",
        "file_path": "op_host/arch35/x.cpp",
        "snippet": "td.set_x(1);",
        "required": True,
        "main_chain": True,
    }
    scored = score_tilingdata_bridge(bridge)
    assert scored.get("owning_type") == "FasgTilingData"
    assert scored.get("canonical_type") == "FasgTilingData"
    assert scored.get("candidates")
