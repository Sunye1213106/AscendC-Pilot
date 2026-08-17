# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def _load():
    import sys

    path = ROOT / "scripts" / "cann_extract.py"
    spec = importlib.util.spec_from_file_location("cann_extract", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ce():
    return _load()


def test_mklink_argv_quotes_spaces(ce, tmp_path: Path) -> None:
    link = tmp_path / "has space" / "impl" / "include"
    target = tmp_path / "has space" / "include"
    argv = ce.mklink_junction_argv(link, target)
    assert argv[:2] == ["cmd", "/c"]
    cmdline = argv[2]
    assert cmdline.startswith("mklink /J ")
    assert f'"{link}"' in cmdline
    assert f'"{target}"' in cmdline


def test_detect_toolkit_host_aarch64(ce, tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    (pkg / "cann-asc-devkit" / "aarch64-linux" / "asc" / "include").mkdir(parents=True)
    assert ce.detect_toolkit_host(pkg) == "aarch64-linux"


def test_apply_fixup_uses_detected_host(ce, tmp_path: Path, monkeypatch) -> None:
    pkg = tmp_path / "pkg"
    include = pkg / "cann-asc-devkit" / "aarch64-linux" / "asc" / "include"
    include.mkdir(parents=True)
    called: list[tuple[Path, Path, bool]] = []

    def fake_make(link: Path, target: Path, *, copy_fallback: bool = False) -> str:
        called.append((link, target, copy_fallback))
        return "symlink"

    monkeypatch.setattr(ce, "make_dir_link", fake_make)
    plan = ce.LinkPlan()
    ce.apply_known_fixups(pkg, plan)
    assert called
    link, target, fallback = called[0]
    assert "aarch64-linux" in str(link).replace("\\", "/")
    assert str(link).replace("\\", "/").endswith("asc/impl/include")
    assert target == include.resolve()
    assert fallback is True
    assert plan.made >= 1


def test_replay_links_skips_live_paths(ce, tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "pkg"
    target = dest / "real"
    target.mkdir(parents=True)
    live = dest / "already"
    live.mkdir()
    (live / "h.h").write_text("ok\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise AssertionError("live paths must not enter make_dir_link")

    monkeypatch.setattr(ce, "make_dir_link", boom)
    plan = ce.LinkPlan()
    plan.links.append((live, "real"))
    ce.replay_links(plan)
    assert plan.made == 0
    assert plan.copied == 0


def test_replay_links_creates_missing_dir_link(ce, tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "pkg"
    target = dest / "real"
    target.mkdir(parents=True)
    link = dest / "missing"
    seen: list[tuple[Path, Path, bool]] = []

    def fake(link_path: Path, resolved: Path, *, copy_fallback: bool = False) -> str:
        seen.append((link_path, resolved, copy_fallback))
        return "junction"

    monkeypatch.setattr(ce, "make_dir_link", fake)
    plan = ce.LinkPlan()
    plan.links.append((link, "real"))
    ce.replay_links(plan)
    assert seen == [(link, target.resolve(), False)]
    assert plan.made == 1


@pytest.mark.skipif(os.name == "nt", reason="Windows junctions poison pytest tmp cleanup")
def test_make_dir_link_replaces_dangling(ce, tmp_path: Path) -> None:
    target = tmp_path / "include"
    target.mkdir()
    (target / "a.h").write_text("ok\n", encoding="utf-8")
    dead = tmp_path / "dead"
    dead.mkdir()
    link = tmp_path / "impl" / "include"
    link.parent.mkdir()
    try:
        os.symlink(dead, link, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks not permitted")
    try:
        dead.rmdir()
        assert not link.exists()
        kind = ce.make_dir_link(link, target, copy_fallback=True)
        assert kind in {"symlink", "junction", "copy"}
        assert (link / "a.h").read_text(encoding="utf-8") == "ok\n"
    finally:
        ce.unlink_reparse(link)
