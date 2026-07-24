"""P0 brace-bound bodies, P1 one-hop callees, P2 provenance_helper."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.apply_extract_plan import apply_extract_plan
from uo.scripts.extract_host_subgraph import extract_host_subgraph
from uo.scripts.function_body import find_function_body, resolve_helper_body
from uo.scripts.propose_extract_plan import propose_extract_plan
from tests._entrypoint_fixtures import write_entrypoint_graph


def _write_host_chain(repo: Path) -> None:
    host = repo / "op_host" / "arch35"
    host.mkdir(parents=True)
    (repo / "op_kernel" / "arch35").mkdir(parents=True)
    (host / "foo_tiling.cpp").write_text(
        """
void FooTiling() {
  InitStuff();
}

void InitStuff() {
  int local = 0;
  ProcessAttr();
  SaveStuff();
  local = 1;
}

void ProcessAttr() {
  auto v = GetAttrOptional<int64_t>("pseType", 0);
  (void)v;
}

void SaveStuff() {
  blob_->set_x(1);
}

void GetWorkspaceSize() {
  blob_->set_wsOffset(8);
}

void UnrelatedLater() {
  ghost_->set_should_not_belong_to_init(9);
}
""",
        encoding="utf-8",
    )
    (repo / "op_kernel" / "arch35" / "foo_kernel.h").write_text(
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


def _setup(tmp_path: Path) -> tuple[Path, str]:
    op = "foo_chain_op"
    repo = tmp_path / op
    _write_host_chain(repo)
    (repo / "op_kernel" / "arch35" / "k.h").write_text("// k\n", encoding="utf-8")
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    write_entrypoint_graph(
        ir,
        op_name=op,
        host_name="FooTiling",
        host_file="op_host/arch35/foo_tiling.cpp",
        host_line=2,
        kernel_name="FooKernel",
        kernel_file="op_kernel/arch35/foo_kernel.h",
    )
    # propose_extract_plan requires boundary present (even empty slots).
    write_yaml(ir / "operator_boundary.yaml", {"inputs": [], "attributes": [], "outputs": []})
    return repo, op


def test_brace_bound_does_not_swallow_next_function(tmp_path: Path) -> None:
    repo, _ = _setup(tmp_path)
    body = find_function_body(repo, "op_host/arch35/foo_tiling.cpp", "InitStuff")
    assert body is not None
    text, start, end = body[2], body[0], body[1]
    assert "ProcessAttr" in text
    assert "SaveStuff" in text
    assert "set_should_not_belong_to_init" not in text
    assert "UnrelatedLater" not in text
    assert end - start < 20

    save = find_function_body(repo, "op_host/arch35/foo_tiling.cpp", "SaveStuff")
    assert save is not None
    assert "set_x" in save[2]
    assert "set_should_not_belong_to_init" not in save[2]


def test_propose_one_hop_includes_getattr_helper(tmp_path: Path) -> None:
    repo, op = _setup(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    names = {c["name"]: c for c in cands["writer_candidates"]}
    assert "SaveStuff" in names
    assert "ProcessAttr" in names
    assert "one_hop_callee" in (names["ProcessAttr"].get("evidence") or [])
    assert "has_getattr" in (names["ProcessAttr"].get("evidence") or [])


def test_propose_sink_closure_and_kernel_alias(tmp_path: Path) -> None:
    repo, op = _setup(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    names = {c["name"]: c for c in cands["writer_candidates"]}
    assert "GetWorkspaceSize" in names
    assert "sink_set_writer" in (names["GetWorkspaceSize"].get("evidence") or [])
    aliases = {(a["local"], a["tdf_leaf"]) for a in cands["alias_candidates"]}
    assert ("localType", "layout") in aliases


def test_workspace_writer_emits_tdf(tmp_path: Path) -> None:
    repo, op = _setup(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    ir = operator_root(repo, op) / "ir"
    write_yaml(ir / "extract_plan_candidates.yaml", cands)
    cand_names = {c["name"] for c in cands["writer_candidates"]}
    recv_names = {c["name"] for c in cands["receiver_candidates"]}
    plan = {
        "version": 1,
        "confirmed_by": "test",
        "writers": [
            w
            for w in [
                {"name": "SaveStuff", "file_path": "op_host/arch35/foo_tiling.cpp", "start_line": 1, "role": "tiling_writer"},
                {"name": "GetWorkspaceSize", "file_path": "op_host/arch35/foo_tiling.cpp", "start_line": 1, "role": "workspace_writer"},
            ]
            if w["name"] in cand_names
        ],
        "receivers": [{"name": "blob_", "is_tiling_sink": True}] if "blob_" in recv_names else [],
        "aliases": [],
        "non_sink_roots": [],
        "extra_host_entries": [],
    }
    assert apply_extract_plan(repo, op, plan=plan, check_only=False)["ok"]
    payload = extract_host_subgraph(repo, op, architecture="arch35")
    tdf = {n["name"] for n in payload["nodes"] if n.get("node_type") == "TilingDataField"}
    assert "x" in tdf
    assert "wsOffset" in tdf


def test_provenance_helper_attrs_without_tdf(tmp_path: Path) -> None:
    repo, op = _setup(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    ir = operator_root(repo, op) / "ir"
    write_yaml(ir / "extract_plan_candidates.yaml", cands)
    cand_names = {c["name"] for c in cands["writer_candidates"]}
    recv_names = {c["name"] for c in cands["receiver_candidates"]}

    plan = {
        "version": 1,
        "confirmed_by": "test",
        "writers": [
            w
            for w in [
                {"name": "SaveStuff", "file_path": "op_host/arch35/foo_tiling.cpp", "start_line": 1, "role": "tiling_writer"},
                {"name": "ProcessAttr", "file_path": "op_host/arch35/foo_tiling.cpp", "start_line": 1, "role": "provenance_helper"},
                {"name": "InitStuff", "file_path": "op_host/arch35/foo_tiling.cpp", "start_line": 1, "role": "ignore"},
                {"name": "FooTiling", "file_path": "op_host/arch35/foo_tiling.cpp", "start_line": 1, "role": "ignore"},
            ]
            if w["name"] in cand_names
        ],
        "receivers": [{"name": "blob_", "is_tiling_sink": True}] if "blob_" in recv_names else [],
        "aliases": [],
        "non_sink_roots": [],
        "extra_host_entries": [],
    }
    result = apply_extract_plan(repo, op, plan=plan, check_only=False)
    assert result["ok"], result

    payload = extract_host_subgraph(repo, op, architecture="arch35")
    helpers = {n["name"] for n in payload["nodes"] if n.get("node_type") == "HelperCall"}
    assert "ProcessAttr" in helpers
    assert "SaveStuff" in helpers

    attrs = {n["name"] for n in payload["nodes"] if n.get("node_type") == "Attribute"}
    assert "pseType" in attrs

    tdf = {n["name"] for n in payload["nodes"] if n.get("node_type") == "TilingDataField"}
    assert "x" in tdf
    assert "should_not_belong_to_init" not in tdf

    # No write edge from ProcessAttr to TDF
    helper_ids = {
        n["id"]: n["name"]
        for n in payload["nodes"]
        if n.get("node_type") == "HelperCall"
    }
    tdf_ids = {n["id"] for n in payload["nodes"] if n.get("node_type") == "TilingDataField"}
    for e in payload["edges"]:
        if e.get("type") == "writes" and e.get("target") in tdf_ids:
            src_name = helper_ids.get(e.get("source"))
            assert src_name != "ProcessAttr"


def test_resolve_helper_body_prefers_definition(tmp_path: Path) -> None:
    repo, _ = _setup(tmp_path)
    # Call-site-like hint pointing at FooTiling but name SaveStuff → definition body
    item = {
        "name": "SaveStuff",
        "file_path": "op_host/arch35/foo_tiling.cpp",
        "start_line": 2,
        "end_line": 4,
    }
    body, start, end = resolve_helper_body(repo, item, prefer_definition=True)
    assert "set_x" in body
    assert start > 2
