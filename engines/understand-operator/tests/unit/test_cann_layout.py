# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init import paths
from uo_init.build_context import BuildContext


def test_cann_candidates_prefer_checkout_pkg() -> None:
    repo = paths.repo_root()
    cands = paths._cann_candidates()
    assert cands[0] == repo / "_cann" / "slim"
    assert cands[1] == repo / "_cann" / "pkg"
    assert Path.home() / "ascendc" / "cann" / "pkg" in cands
    joined = "\n".join(str(p) for p in cands)
    assert "D:\\AscendC" not in joined
    assert "/AscendC/cann/pkg" not in joined.replace("\\", "/")


def test_required_relative_follows_aarch64_host(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "cann-asc-devkit" / "aarch64-linux").mkdir(parents=True)
    rels = paths.required_cann_relative(root)
    assert rels
    assert all("x86_64-linux" not in p for p in rels)
    assert any(p.startswith("cann-asc-devkit/aarch64-linux/") for p in rels)
    assert any(p.endswith("impl/include") for p in rels)


def test_layout_missing_impl_include_hints_fixup(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "cann-asc-devkit").mkdir(parents=True)
    issues = paths.cann_layout_issues(root)
    assert any("impl/include" in x and "--fixup" in x for x in issues)


def test_missing_root_mentions_repo_dest(monkeypatch) -> None:
    monkeypatch.setattr(paths, "cann_root", lambda explicit=None: None)
    issues = paths.cann_layout_issues(None)
    text = "\n".join(issues)
    assert "_cann" in text
    assert "cann_extract.py" in text


def test_build_context_rewrites_host_tuple(tmp_path: Path) -> None:
    cann = tmp_path / "cann"
    (cann / "cann-asc-devkit" / "aarch64-linux").mkdir(parents=True)
    ctx = BuildContext.load(
        cann_root=str(cann),
        ops_root="/ops",
        op_dir="/op",
        arch_dir="arch35",
    )
    includes = [p.replace("\\", "/") for p in ctx.host_includes()]
    assert any("/aarch64-linux/" in p for p in includes)
    assert not any("/x86_64-linux/" in p for p in includes)
