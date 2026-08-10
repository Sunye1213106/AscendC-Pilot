# -*- coding: utf-8 -*-
"""Product-only UO→TG handoff: .uo is enough; arch YAML/DB tree is optional."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from testcase_agent.init_status import (
    InitGateError,
    kb_exists,
    mark_init_confirmed,
    require_kb,
    require_kb_fingerprint_fresh,
    write_init_status,
)
from testcase_agent.io import output_root, write_yaml
from testcase_agent.resolve_policy import TILINGKEY_AUDIT_CHECKLIST_IDS


def _write_product_uo(path: Path, *, op_name: str = "DemoOp", arch: str = "arch35", views: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.unlink()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("CREATE TABLE view_blob(name TEXT PRIMARY KEY, schema TEXT, data TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key,value) VALUES('schema','uo-codemap/v1')")
        conn.execute("INSERT INTO meta(key,value) VALUES('op_name',?)", (op_name,))
        conn.execute("INSERT INTO meta(key,value) VALUES('architecture',?)", (arch,))
        conn.execute("INSERT INTO meta(key,value) VALUES('revision','r-product')")
        blobs = {
            "ir/operator_graph.yaml": {
                "schema": "uo-operator-graph/v1",
                "fingerprint": "fp-demo",
                "op_name": op_name,
                "architecture": arch,
            },
            "views/kernel.yaml": {
                "schema": "uo-kernel-view/v1",
                "branches": [{"id": "KB_1", "condition": "X == 1", "dimensions": ["X"], "stage": "constexpr"}],
            },
            "views/tilingdata.yaml": {
                "schema": "uo-tilingdata-view/v1",
                "structs": [{"name": "TilingData", "fields": [{"name": "s1Tail", "writers": [{}], "readers": [{}]}]}],
            },
        }
        if views:
            blobs.update(views)
        for name, doc in blobs.items():
            conn.execute(
                "INSERT INTO view_blob(name,schema,data) VALUES(?,?,?)",
                (name, str(doc.get("schema") or ""), json.dumps(doc)),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_audit(out_root: Path) -> None:
    path = out_root / "init" / "audit_report.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(
        path,
        {
            "version": 1,
            "status": "pass",
            "checklist": "tilingkey",
            "checks": [{"id": cid, "status": "pass"} for cid in TILINGKEY_AUDIT_CHECKLIST_IDS],
            "blockers": [],
        },
    )


def test_kb_exists_accepts_product_only_layout(tmp_path: Path) -> None:
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product)
    assert not (project / ".ascendc-pilot" / "arch35" / "uo").exists()
    found = kb_exists(project, "DemoOp")
    assert found is not None
    assert found == product.parent
    assert require_kb(project, "DemoOp") == product.parent


def test_mark_init_confirmed_fingerprints_product_without_arch_tree(tmp_path: Path) -> None:
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product)
    out = output_root(project, "DemoOp")
    write_init_status(
        out,
        {
            "version": 1,
            "op_name": "DemoOp",
            "status": "pending_confirm",
            "project_root": project.as_posix(),
            # Intentionally point at the retired arch tree that does not exist.
            "understand_root": (project / ".ascendc-pilot" / "arch35" / "uo").as_posix(),
        },
    )
    _seed_audit(out)
    doc = mark_init_confirmed(out, notes="product-only", require_merge=False)
    assert doc["status"] == "confirmed"
    fp_path = out / "init" / "kb_fingerprint.yaml"
    assert fp_path.is_file()
    assert doc.get("kb_fingerprint_digest")
    fresh = require_kb_fingerprint_fresh(project, "DemoOp", out_root=out, status_doc=doc)
    assert fresh["ok"] is True


def test_product_mutation_invalidates_fingerprint(tmp_path: Path) -> None:
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product)
    out = output_root(project, "DemoOp")
    write_init_status(
        out,
        {
            "version": 1,
            "op_name": "DemoOp",
            "status": "pending_confirm",
            "project_root": project.as_posix(),
            "understand_root": product.parent.as_posix(),
        },
    )
    _seed_audit(out)
    doc = mark_init_confirmed(out, require_merge=False)
    assert doc["status"] == "confirmed"
    # Mutate product bytes.
    with product.open("ab") as fh:
        fh.write(b"\x00mutated")
    with pytest.raises(InitGateError) as exc:
        require_kb_fingerprint_fresh(project, "DemoOp", out_root=out)
    assert exc.value.ask == "kb_stale_reinit"


def test_confirm_fails_closed_without_any_uo_authority(tmp_path: Path) -> None:
    project = tmp_path / "op"
    project.mkdir()
    out = output_root(project, "DemoOp")
    write_init_status(
        out,
        {
            "version": 1,
            "op_name": "DemoOp",
            "status": "pending_confirm",
            "project_root": project.as_posix(),
            "understand_root": (project / ".ascendc-pilot" / "arch35" / "uo").as_posix(),
        },
    )
    _seed_audit(out)
    with pytest.raises(InitGateError) as exc:
        mark_init_confirmed(out, require_merge=False)
    assert exc.value.ask == "kb_fingerprint_unavailable"


def test_missing_kernel_view_fails_i0_kernel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the fail-closed establishment gate used by closure_certify."""
    from testcase_agent.closure import report as R
    from testcase_agent.closure.kernel_domain import load_kernel_view
    from testcase_agent.closure import workspace as W

    chk = R._domain_established(
        "kernel",
        {"source": {"kind": "missing", "reason": "views/kernel.yaml missing from .uo"}},
    )
    assert chk["ok"] is False
    assert "not_established" in chk["detail"]

    project = tmp_path / "empty_op"
    project.mkdir()
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(project))
    monkeypatch.setenv("UO_OP_DIR", str(project))
    monkeypatch.setenv("UO_ARCH", "arch35")
    monkeypatch.setenv("TG_CLOSURE_CI", "1")
    ws = W.Workspace(root=project, artifacts=project / "a", state=project / "s")
    (project / "a").mkdir()
    (project / "s").mkdir()
    _doc, source = load_kernel_view(ws)
    assert source.get("kind") == "missing"
    assert R._domain_established("kernel", {"source": source})["ok"] is False
