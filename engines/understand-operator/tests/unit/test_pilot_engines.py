# -*- coding: utf-8 -*-
"""Smoke tests for pilot_engines prepare/scope/resolve skip paths."""
from __future__ import annotations

from pathlib import Path

from uo_init.pilot_engines import (
    prepare_layout,
    resolve_gaps,
    scope_validate,
)


def test_prepare_layout_requires_run_id(tmp_path: Path):
    out = prepare_layout(tmp_path, {})
    assert out["ok"] is False
    assert out["error"] == "run_id_required"


def test_prepare_layout_blocks_when_cann_missing(tmp_path: Path, monkeypatch):
    from uo_init import paths as paths_mod

    monkeypatch.setattr(paths_mod, "require_cann_ready", lambda explicit=None: (None, ["CANN missing"]))
    out = prepare_layout(tmp_path, {"run_id": "r1"})
    assert out["ok"] is False
    assert out["error"] == "CANN_ENV_NOT_READY"


def test_prepare_layout_scrubs_legacy_layers_without_stubs(tmp_path: Path, monkeypatch):
    """Legacy layered-KB paths must not survive prepare_layout; no not_extracted stubs."""
    from uo_init import paths as paths_mod
    from uo_init.op_spec import OpSpec

    fake_cann = tmp_path / "cann"
    for rel in paths_mod.REQUIRED_CANN_RELATIVE:
        p = fake_cann / rel
        if rel.endswith(".h"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("//", encoding="utf-8")
        else:
            p.mkdir(parents=True, exist_ok=True)
    (fake_cann / "cann-asc-devkit").mkdir(exist_ok=True)
    (fake_cann / "cann-metadef").mkdir(exist_ok=True)
    monkeypatch.setattr(
        paths_mod,
        "require_cann_ready",
        lambda explicit=None: (fake_cann, []),
    )

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
    (uo / "flow").mkdir(parents=True)
    (uo / "flow" / "golden_model.yaml").write_text("status: not_extracted\n", encoding="utf-8")
    (uo / "tiling").mkdir(parents=True)
    (uo / "tiling" / "data_model.yaml").write_text("status: not_extracted\n", encoding="utf-8")
    product = uo / "DummyOp.arch35.uo"
    product.write_bytes(b"uo-keep")

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
    assert not (uo / "flow").exists()
    assert not (uo / "tiling" / "data_model.yaml").exists()
    assert not (uo / "kernel" / "pipeline.yaml").exists()
    assert out.get("seeded_not_extracted") == []
    manifest = (uo / "manifest.yaml").read_text(encoding="utf-8")
    assert "uo-codemap/v1" in manifest
    assert "prepared" in manifest
    assert "DummyOp.arch35.uo" in manifest
    assert "kind: uo_init.pilot_engines.prepare_layout" in manifest
    assert "source_revision:" in manifest
    assert "revision:" in manifest
    assert (uo / "runs" / "r_new" / "scope" / "layout_receipt.yaml").is_file()
    assert (uo / "summary").is_dir()
    assert (uo / "tiling").is_dir()
    assert (uo / "kernel").is_dir()
    assert product.is_file()
    assert product.read_bytes() == b"uo-keep"


def test_resolve_gaps_removed(tmp_path: Path):
    out = resolve_gaps(tmp_path, {"run_id": "r1", "arch_dir": "arch35"})
    assert out["ok"] is False
    assert out["error"] == "RESOLVE_GAPS_REMOVED"
    assert "uo-investigate" in str(out.get("message_zh") or "")


def test_scope_validate_blocks_when_probe_unclean(tmp_path: Path):
    """Probe failure is a blocker — never a human file-list confirmation."""
    scope = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    (scope / "candidates.yaml").write_text(
        "probe_clean: false\n"
        "clang_scope_status: complete\n"
        "ambiguities: []\n"
        "op_name: X\n"
        "arch_dir: arch35\n"
        "arch_user_specified: true\n"
        "host_targets:\n"
        "  - a.cpp\n"
        "kernel_entry: k.cpp\n"
        "probes:\n"
        "  - file: k.cpp\n"
        "    side: kernel\n"
        "    errors: 1\n"
        "    fatal: 1\n"
        "    samples:\n"
        "      - \"'../../../../include/utils/std/tuple.h' file not found\"\n",
        encoding="utf-8",
    )
    out = scope_validate(tmp_path, {"run_id": "r1", "arch_dir": "arch35"})
    assert out["ok"] is False
    assert out.get("blocker") is True
    assert out.get("need_human") is False
    assert "clang_probe_unclean" in (out.get("blockers") or [])
    assert any("tuple.h" in s for s in (out.get("probe_samples") or []))
    assert "tuple.h" in str(out.get("message_zh") or "")


def test_scope_validate_blocks_when_clang_scope_incomplete(tmp_path: Path):
    scope = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    (scope / "candidates.yaml").write_text(
        "probe_clean: true\n"
        "clang_scope_status: incomplete\n"
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
    assert "SCOPE_CLANG_CLOSURE_INCOMPLETE" in (out.get("blockers") or [])
    assert out.get("error") == "SCOPE_CLANG_CLOSURE_INCOMPLETE"


def test_scope_validate_ignores_decision_yes_bypass(tmp_path: Path):
    """decision=yes must not skip Clang / probe gates on the product path."""
    scope = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    (scope / "candidates.yaml").write_text(
        "probe_clean: false\n"
        "clang_scope_status: incomplete\n"
        "ambiguities: []\n"
        "op_name: X\n"
        "arch_dir: arch35\n"
        "arch_user_specified: true\n"
        "host_targets:\n"
        "  - a.cpp\n"
        "kernel_entry: k.cpp\n",
        encoding="utf-8",
    )
    out = scope_validate(
        tmp_path,
        {
            "run_id": "r1",
            "arch_dir": "arch35",
            "decision": "yes",
            "force_confirm": True,
            "force_validate": True,
        },
    )
    assert out["ok"] is False
    blockers = out.get("blockers") or []
    assert "clang_probe_unclean" in blockers
    assert "SCOPE_CLANG_CLOSURE_INCOMPLETE" in blockers


def test_scope_validate_auto_passes_when_clean(tmp_path: Path):
    scope = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    (scope / "candidates.yaml").write_text(
        "probe_clean: true\n"
        "clang_scope_status: complete\n"
        "clang_scope_tus_expected: 2\n"
        "clang_scope_tus_parsed: 2\n"
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
    # Parent Action id must not leak into the scope_receipt gate identity.
    out = scope_validate(
        tmp_path,
        {
            "run_id": "r1",
            "arch_dir": "arch35",
            "workflow_id": "uo-init",
            "action_id": "prepare",
        },
    )
    assert out["ok"] is True
    assert out.get("auto") is True
    receipt = out["receipt"]
    assert receipt["status"] == "confirmed"
    assert receipt["source"] == "machine"
    assert receipt["validated"] is True
    assert receipt["clang_scope_status"] == "complete"
    assert receipt["action_id"] == "scope_validated"
    assert (scope / "scope_validated.yaml").is_file()
    text = (scope / "scope_validated.yaml").read_text(encoding="utf-8")
    assert "action_id: scope_validated" in text
    assert "action_id: prepare" not in text


def test_scope_validate_soft_tiling_key_header_not_found(tmp_path: Path):
    scope = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    (scope / "candidates.yaml").write_text(
        "probe_clean: true\n"
        "clang_scope_status: complete\n"
        "clang_scope_tus_expected: 2\n"
        "clang_scope_tus_parsed: 2\n"
        "ambiguities:\n"
        "  - 'tiling_key_header_not_found: no *template_tiling_key.h'\n"
        "op_name: X\n"
        "arch_dir: arch35\n"
        "arch_user_specified: true\n"
        "host_targets:\n"
        "  - a.cpp\n"
        "kernel_entry: k.cpp\n"
        "scope_files: 3\n",
        encoding="utf-8",
    )
    out = scope_validate(tmp_path, {"run_id": "r1", "arch_dir": "arch35"})
    assert out["ok"] is True
    assert "tiling_key_header_not_found" not in str(out.get("blockers") or [])
