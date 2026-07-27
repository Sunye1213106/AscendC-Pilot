from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo._operator.spec import spec_bundle_hash
from uo.scripts.build_layered_kb import build_layered_kb
from uo.scripts.detect_kb_changes import detect_kb_changes
from uo.scripts.export_diff_product import export_diff_product
from uo.scripts.plan_kb_update import plan_kb_update
from uo.scripts.update_operator import update_operator
from tests._entrypoint_fixtures import write_entrypoint_graph


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_git_repo(repo: Path) -> str:
    _git(repo, "init")
    _git(repo, "config", "user.email", "uo@example.com")
    _git(repo, "config", "user.name", "uo-test")
    (repo / "op_host").mkdir(parents=True)
    (repo / "op_kernel").mkdir(parents=True)
    (repo / "op_host" / "demo.cpp").write_text(
        "void DemoOpHost() { int x = 1; TilingData tile; tile.v = x; }\n",
        encoding="utf-8",
    )
    (repo / "op_kernel" / "demo.cpp").write_text(
        "void DemoKernel() { TilingData tile; if (flag) { DoPostNz(); } }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return _git(repo, "rev-parse", "HEAD")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _seed_kb(repo: Path, revision: str) -> Path:
    root = operator_root(repo, "DemoOp")
    init_operator_contract_layout(root, "DemoOp", repo)
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["current_run_id"] = "UO_RUN_BASE"
    manifest["source"]["root"] = str(repo.resolve())
    manifest["source"]["revision"] = revision
    manifest["source"]["snapshot_id"] = "SOURCE_BASE"
    manifest["spec"]["bundle_hash"] = spec_bundle_hash()
    _write_yaml(root / "manifest.yaml", manifest)

    phase0 = root / "runs" / "UO_RUN_BASE" / "scope"
    phase0.mkdir(parents=True)
    confirmed = {
        "version": 1,
        "confirmed_file_list": [
            {"path": "op_host/demo.cpp", "role": "host"},
            {"path": "op_kernel/demo.cpp", "role": "kernel"},
        ],
    }
    _write_yaml(phase0 / "scope_confirmed.yaml", confirmed)
    _write_yaml(
        phase0 / "receipt.yaml",
        {
            "version": 1,
            "status": "pass",
            "source_revision": revision,
            "frozen_scope": confirmed,
        },
    )

    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    entrypoint_graph = write_entrypoint_graph(
        ir,
        op_name="DemoOp",
        host_name="DemoOpHost",
        host_file="op_host/demo.cpp",
        host_line=1,
        kernel_name="DemoKernel",
        kernel_file="op_kernel/demo.cpp",
        kernel_line=1,
    )
    host_nodes = [
        {
            "id": "VAR_HOST_X",
            "layer": "host",
            "node_type": "Attribute",
            "name": "x",
            "file_path": "op_host/demo.cpp",
            "start_line": 1,
            "end_line": 1,
        }
    ]
    kernel_nodes = [
        {
            "id": "KBR_POST_NZ",
            "layer": "kernel",
            "node_type": "KernelBranch",
            "name": "PostNz",
            "file_path": "op_kernel/demo.cpp",
            "start_line": 1,
            "end_line": 1,
        }
    ]
    branches = [{"id": "KBR_POST_NZ", "file_path": "op_kernel/demo.cpp", "binding_time": "runtime"}]
    bridge_nodes = [
        {"id": "BRIDGE_TILING_KEY", "layer": "bridge", "node_type": "TilingKey", "name": "TilingKey", "file_path": ""}
    ]

    _write_yaml(ir / "entrypoint_candidates.yaml", {"version": 1, "roles": {}})
    _write_yaml(ir / "host_subgraph.yaml", {"nodes": host_nodes, "edges": [], "unresolved": []})
    _write_yaml(
        ir / "kernel_subgraph.yaml",
        {"nodes": kernel_nodes, "edges": [], "branches": branches, "unresolved": []},
    )
    _write_yaml(
        ir / "tilingkey_space.yaml",
        {
            "nodes": bridge_nodes,
            "edges": [],
            "unresolved": [],
            "args_sel_count": 1,
            "dimensions": [],
            "template_blocks": [],
        },
    )
    _write_yaml(ir / "golden.yaml", {"nodes": [], "unresolved": [], "golden": {}})
    _write_yaml(
        ir / "bridge.yaml",
        {"bridge_nodes": bridge_nodes, "bridge_edges": [], "unresolved": [], "diagnostics": []},
    )
    graph = {
        "version": 1,
        "op_name": "DemoOp",
        "architecture": "arch35",
        "layers": ["host", "bridge", "kernel"],
        "entrypoint_graph": entrypoint_graph,
        "nodes": [*host_nodes, *kernel_nodes, *bridge_nodes],
        "edges": [],
        "tilingkey": {"args_sel_count": 1, "dimensions": [], "template_blocks": []},
        "kernel_branches": branches,
        "golden": {},
        "bridge_diagnostics": [],
        "unresolved": [],
        "stats": {"node_count": 3, "edge_count": 0, "unresolved_count": 0, "args_sel_count": 1},
    }
    _write_yaml(ir / "operator_graph.yaml", graph)
    _write_yaml(ir / "unresolved.yaml", {"version": 1, "op_name": "DemoOp", "items": []})
    _write_yaml(
        ir / "extract_plan.yaml",
        {
            "version": 1,
            "confirmed_by": "test",
            "writers": [],
            "receivers": [],
            "aliases": [],
            "non_sink_roots": [],
            "extra_host_entries": [],
        },
    )

    for rel in [
        "tiling/key_space.yaml",
        "tiling/exhaustive_key_space.yaml",
        "tiling/coverage_model.yaml",
        "kernel/branches.yaml",
        "cross_layer/impact_graph.yaml",
        "quality.yaml",
    ]:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel == "quality.yaml":
            _write_yaml(path, {"version": 1, "op_name": "DemoOp", "status": "pass"})
        elif rel == "tiling/key_space.yaml":
            _write_yaml(path, {"version": 1, "op_name": "DemoOp", "fields": []})
        else:
            _write_yaml(path, {"version": 1, "op_name": "DemoOp", "items": []})

    return root


def test_detect_and_plan_host_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_git_repo(repo)
    _seed_kb(repo, base)

    (repo / "op_host" / "demo.cpp").write_text(
        "void DemoOpHost() { int x = 2; TilingData tile; tile.v = x; }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "host tweak")
    head = _git(repo, "rev-parse", "HEAD")

    change_set = detect_kb_changes(repo, "DemoOp", write=True)
    assert change_set["base_revision"] == base
    assert change_set["head_revision"] == head
    assert change_set["scoped_change_count"] == 1
    assert change_set["files"][0]["path"] == "op_host/demo.cpp"
    assert change_set["files"][0]["role"] == "host"
    assert change_set["needs_scope_review"] is False

    plan = plan_kb_update(repo, "DemoOp", change_set=change_set, write=True)
    assert plan["mode"] in {"selective", "full_extract"}
    assert "host" in plan["affected_layers"]
    assert "bridge" in plan["affected_layers"]
    assert "kernel" not in plan["affected_layers"] or plan["mode"] == "full_extract"


def test_export_diff_binds_host_entity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_git_repo(repo)
    root = _seed_kb(repo, base)

    change_set = {
        "version": 1,
        "op_name": "DemoOp",
        "base_revision": base,
        "head_revision": base,
        "needs_scope_review": False,
        "files": [{"path": "op_host/demo.cpp", "status": "M", "in_scope": True, "role": "host", "suspicious_out_of_scope": False}],
    }
    plan = {
        "version": 1,
        "op_name": "DemoOp",
        "mode": "selective",
        "affected_layers": ["host", "bridge", "entrypoints"],
        "scoped_changed_files": ["op_host/demo.cpp"],
        "needs_scope_review": False,
    }
    result = export_diff_product(repo, "DemoOp", change_set=change_set, update_plan=plan, write=True)
    assert (root / "diff" / "index.yaml").exists()
    assert (root / "diff" / "impact.yaml").exists()
    assert (root / "diff" / "unresolved.yaml").exists()
    assert (root / "diff" / "change_set.yaml").exists()
    assert result["index"]["status"] == "ready"
    assert result["index"]["kind"] == "uo_diff_product"
    assert "VAR_HOST_X" in result["impact"]["affected_entities"]["variables"]
    # Must not mark unrelated kernel branch as high confidence for host-only change
    high_kernel = [
        h
        for h in result["impact"]["coverage_hints"]
        if h.get("confidence") == "high" and h.get("entity_ref") == "KBR_POST_NZ"
    ]
    assert high_kernel == []


def test_out_of_scope_source_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_git_repo(repo)
    _seed_kb(repo, base)

    (repo / "op_host" / "extra.cpp").write_text("void Extra() {}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add out of scope host file")

    change_set = detect_kb_changes(repo, "DemoOp", write=True)
    assert change_set["needs_scope_review"] is True
    plan = plan_kb_update(repo, "DemoOp", change_set=change_set, write=True)
    assert plan["needs_scope_review"] is True

    result = update_operator(repo, "DemoOp", skip_validate=True)
    assert result["status"] == "blocked"
    index = yaml.safe_load((operator_root(repo, "DemoOp") / "diff" / "index.yaml").read_text(encoding="utf-8"))
    assert index["status"] == "blocked"


def test_unknown_revision_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    root = _seed_kb(repo, "unknown")
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["source"]["revision"] = "unknown"
    _write_yaml(root / "manifest.yaml", manifest)
    try:
        detect_kb_changes(repo, "DemoOp", write=False)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unknown" in str(exc).lower() or "uo-init" in str(exc).lower()


def test_selective_layers_preserves_untouched_yaml(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_git_repo(repo)
    root = _seed_kb(repo, base)
    kernel_before = (root / "ir" / "kernel_subgraph.yaml").read_text(encoding="utf-8")

    # Monkeypatch extractors by calling build with layers that skip kernel — should keep file
    # Host extract may fail without CBM; so only request golden which is lightweight
    graph = build_layered_kb(repo, "DemoOp", layers={"golden"})
    assert "golden" in graph.get("rebuild_layers", [])
    assert "kernel" not in graph.get("rebuild_layers", [])
    assert (root / "ir" / "kernel_subgraph.yaml").read_text(encoding="utf-8") == kernel_before


def test_cli_update_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "uo.scripts.update_operator", "--help"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "uo-update" in result.stdout.lower() or "Incremental" in result.stdout or "--op-name" in result.stdout


def test_apply_update_ignores_stale_sqlite(tmp_path: Path) -> None:
    """Structural apply must not fail when indexes/kb_graph.sqlite is stale."""
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_git_repo(repo)
    root = _seed_kb(repo, base)

    # Stale sqlite that would fail integrity if apply still ran gates/export.
    db = root / "indexes" / "kb_graph.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not-a-valid-sqlite-db")

    (repo / "op_host" / "demo.cpp").write_text(
        "void DemoOpHost() { int x = 2; TilingData tile; tile.v = x; }\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "host change")

    result = update_operator(repo, "DemoOp", run_gates=False, reuse_artifacts=False)
    assert result["status"] == "pass"
    # Must not have attempted integrity against stale sqlite.
    assert result.get("integrity") is None
    receipt = result.get("receipt") or {}
    assert receipt.get("publish_deferred_to") == "export_integrity"
    # Corrupt sqlite left untouched by structural apply.
    assert db.read_bytes() == b"not-a-valid-sqlite-db"
