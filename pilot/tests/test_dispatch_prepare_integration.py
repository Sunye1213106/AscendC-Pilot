# -*- coding: utf-8 -*-
"""Vertical prepare → dispatch_subagent tests with real source roots.

Component contract tests missed BUNDLE_NOT_READABLE because they used
write:(none) kb_lookup stubs and empty allowed_source_roots.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from synthetic_uo import write_synthetic_uo

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "engines" / "understand-operator" / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "engines" / "understand-operator" / "src"))
if str(REPO / "pilot") not in sys.path:
    sys.path.insert(0, str(REPO / "pilot"))


def _setup_op_with_sources(tmp_path: Path, monkeypatch, *, arch: str = "arch0") -> Path:
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", arch)
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))
    from ascendc_pilot.paths import ensure_agent_layout, uo_root

    ensure_agent_layout(tmp_path, arch=arch)
    write_synthetic_uo(tmp_path, op_name="_synthetic_toy", architecture=arch)
    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_kernel").mkdir()
    (tmp_path / "op_host" / "op.cpp").write_text("void Host() {}\n", encoding="utf-8")
    (tmp_path / "op_kernel" / "kernel.cpp").write_text("void Kernel() {}\n", encoding="utf-8")
    boundary = uo_root(tmp_path, arch=arch) / "ir" / "operator_boundary.yaml"
    boundary.parent.mkdir(parents=True, exist_ok=True)
    boundary.write_text(
        yaml.safe_dump(
            {"roots": ["op_host", "op_kernel"], "source_roots": ["op_host", "op_kernel"]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_tg_init_audit_prepare_dispatches_with_future_write(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.actions.dispatch import build_host_step
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow

    root = _setup_op_with_sources(tmp_path, monkeypatch)
    start_workflow(
        root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
        phase="gate",
        force_phase=True,
    )
    contract_dir = tg_root(root, arch="arch0") / "contract"
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "tilingkey_contract.yaml").write_text(
        "status: pass\nerrors: []\n",
        encoding="utf-8",
    )
    gate = prepare_action(root, "integrity_gate")
    assert gate.get("ok") is True, gate
    prep = prepare_action(root, "init_audit")
    assert prep.get("ok") is True, prep
    assert prep.get("reason_code") != "BUNDLE_NOT_READABLE"
    stub = str(prep.get("task_prompt_stub") or "")
    assert "acp --project" in stub
    assert "write:" in stub
    assert "audit_report.yaml" in stub
    report = tg_root(root, arch="arch0") / "init" / "audit_report.yaml"
    assert not report.is_file()
    step = build_host_step(
        kind="dispatch_subagent",
        prepare=prep,
        actor_id=str(prep.get("actor_id") or "tg-init-audit"),
    )
    assert step.get("kind") == "dispatch_subagent", step
    assert "." not in (prep.get("unleased") or [])


def test_ce_review_prepare_dispatches_with_project_root(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.actions.dispatch import build_host_step
    from ascendc_pilot.state import start_workflow

    root = _setup_op_with_sources(tmp_path, monkeypatch)
    start_workflow(root, "ce-review", architecture="arch0", op_name="_synthetic_toy")
    prep = prepare_action(root, "code_review")
    assert prep.get("ok") is True, prep
    assert prep.get("reason_code") != "BUNDLE_NOT_READABLE"
    stub = str(prep.get("task_prompt_stub") or "")
    assert "acp --project" in stub
    step = build_host_step(
        kind="dispatch_subagent",
        prepare=prep,
        actor_id=str(prep.get("actor_id") or "ce-reviewer"),
    )
    assert step.get("kind") == "dispatch_subagent", step
    assert "." not in (prep.get("unleased") or [])


def test_prepare_rejects_out_of_scope_source_read(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions.method_bundle import TaskStubPointers, check_bundle_readable
    from ascendc_pilot.paths import ensure_agent_layout

    root = _setup_op_with_sources(tmp_path, monkeypatch)
    ensure_agent_layout(root, arch="arch0")
    outside = root / "unrelated" / "leak.cpp"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("int leak;\n", encoding="utf-8")
    sdir = root / "session"
    sdir.mkdir()
    (sdir / "prompt.md").write_text("# p\n", encoding="utf-8")
    (sdir / "method.md").write_text("# m\n", encoding="utf-8")
    (sdir / "bundle.yaml").write_text("ok: true\n", encoding="utf-8")
    br = check_bundle_readable(
        pointers=TaskStubPointers(
            prompt=str(sdir / "prompt.md"),
            method=str(sdir / "method.md"),
            bundle=str(sdir / "bundle.yaml"),
            session_dir=str(sdir),
            project_root=str(root.resolve()),
            read=[str(outside.resolve())],
        ),
        session_dir=sdir,
        project_root=root,
        allowed_read_paths=["runs/**"],
        allowed_source_roots=["op_host", "op_kernel"],
    )
    assert br.get("ok") is False
    assert br.get("reason_code") == "BUNDLE_NOT_READABLE"
    assert br.get("unleased")


def test_prepare_bundle_check_exception_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow

    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "arch35" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    start_workflow(op, "uo-query", architecture="arch35", intent="TND SplitAxis?")

    def boom(**kwargs):
        raise RuntimeError("checker exploded")

    monkeypatch.setattr(
        "ascendc_pilot.actions.method_bundle.check_bundle_readable",
        boom,
    )
    result = prepare_action(op, "kb_lookup")
    assert result.get("ok") is False
    assert result.get("reason_code") == "BUNDLE_NOT_READABLE"
    assert "checker exploded" in str(result.get("message_zh") or "")
