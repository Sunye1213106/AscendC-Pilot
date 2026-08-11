# -*- coding: utf-8 -*-
"""Scope membership must keep sibling common/ even without op_needle."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from uo_init.clang_tu import _in_analysis_scope
from uo_init.clang_walk import _in_scope
from uo_init import scope_scan as ss


def _node(path: str):
    return SimpleNamespace(location=SimpleNamespace(file=SimpleNamespace(name=path)))


def test_in_analysis_scope_keeps_sibling_common_without_needle(tmp_path: Path):
    op = tmp_path / "attention" / "widget"
    common = tmp_path / "attention" / "common" / "op_kernel" / "arch35" / "mask.h"
    common.parent.mkdir(parents=True)
    common.write_text("//\n", encoding="utf-8")
    op.mkdir(parents=True)

    # Bare needle would miss attention/common/... — sibling common must still match.
    assert _in_analysis_scope(
        _node(common.as_posix()),
        "widget",
        op_root=str(op),
    )


def test_in_analysis_scope_prefers_scope_set(tmp_path: Path):
    root = tmp_path / "attention"
    op = root / "widget"
    shared = root / "common" / "op_kernel" / "foo.h"
    shared.parent.mkdir(parents=True)
    shared.write_text("//\n", encoding="utf-8")
    (op / "op_kernel").mkdir(parents=True)
    scope = ss.ScopeSet(
        op_dir=op,
        workspace_root=root,
        arch_dir="arch35",
        files=[
            ss.ScopeFile(
                path=shared,
                role=ss.ROLE_HEADER,
                side=ss.SIDE_KERNEL,
                is_tu=False,
                shared=True,
                kind=ss.KIND_SHARED,
                provenance="clang_include",
            )
        ],
    )
    assert _in_analysis_scope(_node(shared.as_posix()), "never_matches", scope=scope)
    assert not _in_analysis_scope(
        _node((root / "other.h").as_posix()), "never_matches", scope=scope
    )


def test_clang_walk_in_scope_keeps_common_fallback(tmp_path: Path):
    op = tmp_path / "attention" / "widget"
    common = tmp_path / "attention" / "common" / "x.h"
    common.parent.mkdir(parents=True)
    common.write_text("//\n", encoding="utf-8")
    op.mkdir(parents=True)
    assert _in_scope(common.as_posix(), needle="widget", op_root=str(op))
    assert not _in_scope(
        "/opt/cann-asc-devkit/include/x.h", needle="widget", op_root=str(op)
    )
