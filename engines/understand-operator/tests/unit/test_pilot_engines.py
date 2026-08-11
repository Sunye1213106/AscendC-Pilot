# -*- coding: utf-8 -*-
"""Smoke tests for pilot_engines prepare/scope/resolve skip paths."""
from __future__ import annotations

from pathlib import Path

from uo_init.pilot_engines import (
    apply_gap_patch,
    prepare_layout,
    resolve_gaps,
    scope_confirm,
    scope_validate,
)


def test_prepare_layout_requires_run_id(tmp_path: Path):
    out = prepare_layout(tmp_path, {})
    assert out["ok"] is False
    assert out["error"] == "run_id_required"


def test_prepare_layout_scrubs_disallowed_and_seeds_not_extracted(tmp_path: Path):
    """Disallowed top-level paths must not survive prepare_layout."""
    from uo_init.op_spec import OpSpec

    op = tmp_path / "DummyOp"
    op.mkdir()
    (op / "op_host").mkdir()
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "flash_attention_score_grad_def.cpp").write_text(
        "class DummyOp : public OpDef {};\nOP_ADD(DummyOp);\n",
        encoding="utf-8",
    )
    uo = op / ".ascendc-pilot" / "arch35" / "uo"
    (uo / "ir").mkdir(parents=True)
    (uo / "ir" / "bridge.yaml").write_text("version: 2\nbridge_nodes: []\n", encoding="utf-8")
    (uo / "ir" / "extract_plan.yaml").write_text("version: 1\n", encoding="utf-8")
    (uo / "docs_cache").mkdir()
    (uo / "docs_cache" / "x.bin").write_text("x", encoding="utf-8")
    (uo / "analysis").mkdir()

    import uo_init.op_spec as op_spec_mod

    def _fake_discover(root, arch_dir=None):
        return OpSpec(
            op_name="DummyOp",
            op_snake="dummy_op",
            op_dir=Path(root),
            arch_dir="arch35",
            available_archs=["arch35"],
            host_targets=[],
            kernel_entry=None,
            tiling_key_header=None,
            ambiguities=[],
        )

    old = op_spec_mod.discover
    op_spec_mod.discover = _fake_discover  # type: ignore[assignment]
    try:
        out = prepare_layout(op, {"run_id": "r_new"})
    finally:
        op_spec_mod.discover = old  # type: ignore[assignment]

    assert out["ok"] is True
    assert out.get("layout_reset") is True
    assert not (uo / "ir" / "bridge.yaml").exists()
    assert not (uo / "docs_cache").exists()
    assert not (uo / "analysis").exists()
    manifest = (uo / "manifest.yaml").read_text(encoding="utf-8")
    assert "kb_schema-v1" in manifest
    assert "prepared" in manifest
    assert (uo / "flow" / "golden_model.yaml").is_file()
    assert "not_extracted" in (uo / "flow" / "golden_model.yaml").read_text(encoding="utf-8")
    assert (uo / "runs" / "r_new" / "scope" / "layout_receipt.yaml").is_file()


def test_resolve_gaps_autoskips_when_closed(tmp_path: Path):
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "ir"
    uo.mkdir(parents=True)
    (uo / "unresolved.yaml").write_text(
        "version: 1\nstatus: closed\nblocker_count: 0\nblockers: []\n",
        encoding="utf-8",
    )
    out = resolve_gaps(tmp_path, {"run_id": "r1"})
    assert out["ok"] and out["skipped"]
    assert (uo / "resolve_gaps_receipt.yaml").is_file()
    patch = apply_gap_patch(tmp_path, {"run_id": "r1"})
    assert patch["ok"] and patch.get("skipped")


def test_scope_validate_blocks_when_probe_unclean(tmp_path: Path):
    """Probe failure is a blocker — never a human file-list confirmation."""
    scope = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    (scope / "candidates.yaml").write_text(
        "probe_clean: false\n"
        "ambiguities: []\n"
        "op_name: X\n"
        "arch_dir: arch35\n"
        "arch_user_specified: true\n"
        "host_targets:\n"
        "  - a.cpp\n"
        "kernel_entry: k.cpp\n",
        encoding="utf-8",
    )
    out = scope_validate(tmp_path, {"run_id": "r1", "arch_dir": "arch35"})
    assert out["ok"] is False
    assert out.get("blocker") is True
    assert out.get("need_human") is False
    assert "clang_probe_unclean" in (out.get("blockers") or [])


def test_scope_validate_auto_passes_when_clean(tmp_path: Path):
    scope = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    (scope / "candidates.yaml").write_text(
        "probe_clean: true\n"
        "ambiguities:\n"
        "  - 'host_targets_from_glob: fallback'\n"
        "op_name: X\n"
        "arch_dir: arch35\n"
        "arch_user_specified: true\n"
        "host_targets:\n"
        "  - a.cpp\n"
        "kernel_entry: k.cpp\n"
        "scope_files: 3\n"
        "scope_shared: 1\n",
        encoding="utf-8",
    )
    out = scope_validate(
        tmp_path,
        {"run_id": "r1", "arch_dir": "arch35", "workflow_id": "uo-init"},
    )
    assert out["ok"] is True
    assert out.get("auto") is True
    receipt = out["receipt"]
    assert receipt["status"] == "confirmed"
    assert receipt["source"] == "machine"
    assert receipt["validated"] is True
    assert (scope / "scope_confirmed.yaml").is_file()


def test_scope_confirm_alias_is_scope_validate():
    assert scope_confirm is scope_validate
