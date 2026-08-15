# -*- coding: utf-8 -*-
"""Product-only UO→TG handoff: .uo is enough; YAML/IR work files are optional."""

from __future__ import annotations

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
    from uo_init.ir.codemap import CodeMap
    from uo_init.ir.entity import Entity, EntityKind
    from uo_init.store.writer import write_codemap

    path = Path(path)
    cm = CodeMap(op_name=op_name, architecture=arch)
    cm.add_entity(Entity(id=f"ARCH_{arch}", kind=EntityKind.ARCH, name=arch))
    extra = dict(views or {})
    write_codemap(cm, path, views=extra or None)


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
    product = project / ".ascendc-pilot" / "arch35" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product)
    # No YAML work files — only the durable *.uo.
    assert not (product.parent / "ir").exists()
    found = kb_exists(project, "DemoOp")
    assert found is not None
    assert found == product.parent
    assert require_kb(project, "DemoOp") == product.parent


def test_mark_init_confirmed_fingerprints_product_without_yaml_worktree(tmp_path: Path) -> None:
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "arch35" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product)
    out = output_root(project, "DemoOp", arch="arch35")
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
    doc = mark_init_confirmed(out, notes="product-only", require_merge=False)
    assert doc["status"] == "confirmed"
    fp_path = out / "init" / "kb_fingerprint.yaml"
    assert fp_path.is_file()
    assert doc.get("kb_fingerprint_digest")
    fresh = require_kb_fingerprint_fresh(project, "DemoOp", out_root=out, status_doc=doc)
    assert fresh["ok"] is True


def test_product_mutation_invalidates_fingerprint(tmp_path: Path) -> None:
    project = tmp_path / "op"
    product = project / ".ascendc-pilot" / "arch35" / "uo" / "DemoOp.arch35.uo"
    _write_product_uo(product)
    out = output_root(project, "DemoOp", arch="arch35")
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
    out = output_root(project, "DemoOp", arch="arch35")
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
