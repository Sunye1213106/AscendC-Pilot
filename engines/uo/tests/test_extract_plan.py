"""Synthetic-op tests for LLM extract_plan gate (no FAG names)."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts.apply_extract_plan import apply_extract_plan
from uo.scripts.extract_host_subgraph import extract_host_subgraph
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.propose_extract_plan import propose_extract_plan
from uo.scripts._ir_io import write_yaml


def _setup_foo_tiling(tmp_path: Path) -> tuple[Path, str]:
    op = "foo_op"
    repo = tmp_path / op
    host = repo / "op_host" / "arch35"
    kernel = repo / "op_kernel" / "arch35"
    host.mkdir(parents=True)
    kernel.mkdir(parents=True)

    (host / "foo_tiling.cpp").write_text(
        """
void FooTiling() {
  SaveStuff();
  GetTilingKey();
}

void SaveStuff() {
  blob_->set_x(1);
  blob_->set_y(2);
  mid_->set_tmp(0);
}

void GetTilingKey() {
  context->SetTilingKey(1);
}
""",
        encoding="utf-8",
    )
    (kernel / "foo_kernel.h").write_text(
        """
class FooKernel {
  void Process() {
    localType = tilingData->base.layout;
    if (localType == LAYOUT_TND) { DoTnd(); }
  }
};
""",
        encoding="utf-8",
    )

    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    write_yaml(
        ir / "entrypoints.yaml",
        {
            "version": 1,
            "roles": {
                "host_tiling_entry": {
                    "selected": {
                        "name": "FooTiling",
                        "qualified_name": "FooTiling",
                        "file_path": "op_host/arch35/foo_tiling.cpp",
                        "start_line": 2,
                        "end_line": 6,
                    },
                    "status": "confirmed",
                },
                "kernel_entry": {
                    "selected": {
                        "name": "FooKernel",
                        "qualified_name": "FooKernel",
                        "file_path": "op_kernel/arch35/foo_kernel.h",
                        "start_line": 2,
                        "end_line": 10,
                    },
                    "status": "confirmed",
                },
            },
        },
    )
    return repo, op


def test_propose_finds_generic_receiver(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    write_yaml(
        operator_root(repo, op) / "ir" / "extract_plan_candidates.yaml",
        cands,
    )
    recv_names = {c["name"] for c in cands["receiver_candidates"]}
    assert "blob_" in recv_names
    writer_names = {c["name"] for c in cands["writer_candidates"]}
    assert "SaveStuff" in writer_names


def test_host_no_tdf_without_plan(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    payload = extract_host_subgraph(repo, op, architecture="arch35", allow_empty_plan=False)
    assert any(u.get("id") == "UNRES_EXTRACT_PLAN_MISSING" for u in payload["unresolved"])
    tdf_nodes = [n for n in payload["nodes"] if n.get("node_type") == "TilingDataField"]
    assert tdf_nodes == []


def test_host_tdf_after_plan(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    ir = operator_root(repo, op) / "ir"
    write_yaml(ir / "extract_plan_candidates.yaml", cands)

    plan = {
        "version": 1,
        "confirmed_by": "llm",
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 8,
                "role": "tiling_writer",
            },
            {
                "name": "GetTilingKey",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 14,
                "role": "key_writer",
            },
            {
                "name": "FooTiling",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 2,
                "role": "ignore",
            },
        ],
        "receivers": [
            {"name": "blob_", "is_tiling_sink": True},
            {"name": "mid_", "is_tiling_sink": False},
        ],
        "aliases": [],
        "non_sink_roots": [],
        "extra_host_entries": [],
    }
    # Only include writers/receivers that exist in candidates
    cand_writers = {c["name"] for c in cands["writer_candidates"]}
    plan["writers"] = [w for w in plan["writers"] if w["name"] in cand_writers]
    cand_recv = {c["name"] for c in cands["receiver_candidates"]}
    plan["receivers"] = [r for r in plan["receivers"] if r["name"] in cand_recv]

    result = apply_extract_plan(repo, op, plan=plan, check_only=False)
    assert result["ok"], result

    payload = extract_host_subgraph(repo, op, architecture="arch35")
    tdf_names = {n["name"] for n in payload["nodes"] if n.get("node_type") == "TilingDataField"}
    assert "x" in tdf_names
    assert "tmp" not in tdf_names  # mid_ not a sink


def test_kernel_alias_normalize(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    ir = operator_root(repo, op) / "ir"
    # Minimal candidates so apply can validate alias if we skip apply
    write_yaml(
        ir / "extract_plan.yaml",
        {
            "version": 1,
            "confirmed_by": "test",
            "writers": [],
            "receivers": [],
            "aliases": [{"local": "localType", "tdf_leaf": "layout"}],
            "non_sink_roots": [],
            "extra_host_entries": [],
        },
    )
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    refs = [
        b.get("determinant_ref") or b.get("node", {}).get("determinant_ref")
        for b in payload.get("branches") or []
    ]
    # branches may nest under node
    flat_refs = []
    for b in payload.get("branches") or []:
        if isinstance(b, dict):
            flat_refs.append(b.get("determinant_ref"))
            node = b.get("node") or {}
            if isinstance(node, dict):
                flat_refs.append(node.get("determinant_ref"))
    assert "layout" in flat_refs or any(r == "layout" for r in refs)
    assert "localType" not in [r for r in flat_refs if r]


def test_apply_rejects_invented_writer(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    write_yaml(
        operator_root(repo, op) / "ir" / "extract_plan_candidates.yaml",
        cands,
    )
    bad = {
        "version": 1,
        "confirmed_by": "llm",
        "writers": [{"name": "NotInCandidates", "role": "tiling_writer"}],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
        "extra_host_entries": [],
    }
    result = apply_extract_plan(repo, op, plan=bad, check_only=True)
    assert not result["ok"]
    assert result["rejected_count"] >= 1
