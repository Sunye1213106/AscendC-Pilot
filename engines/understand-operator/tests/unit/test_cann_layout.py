# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init import paths
from uo_init.build_context import BuildContext
from uo_init.pilot_engines import _cann_env_block


def _isolate_cann_discovery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in paths.CANN_DISCOVERY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(paths, "_cann_candidates", lambda: [])


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


def test_extracted_tree_ready_without_impl_include(tmp_path: Path) -> None:
    root = tmp_path / "pkg"
    (root / "cann-asc-devkit").mkdir(parents=True)
    assert paths.cann_layout_issues(root) == []


def test_installed_toolkit_layout_is_ready(tmp_path: Path) -> None:
    root = tmp_path / "latest"
    (root / "x86_64-linux" / "asc" / "include").mkdir(parents=True)
    assert paths._looks_like_cann(root)
    assert paths.cann_host_dir(root) == "x86_64-linux"
    assert paths.cann_layout_issues(root) == []


def test_missing_root_mentions_repo_dest(monkeypatch) -> None:
    monkeypatch.setattr(paths, "cann_root", lambda explicit=None: None)
    issues = paths.cann_layout_issues(None)
    text = "\n".join(issues)
    assert "_cann" in text
    assert "cann_extract.py" in text


def test_adapt_path_strips_package_prefix_for_install(tmp_path: Path) -> None:
    root = tmp_path / "latest"
    real = root / "x86_64-linux" / "asc" / "include"
    real.mkdir(parents=True)
    yaml_path = (root / "cann-asc-devkit" / "x86_64-linux" / "asc" / "include").as_posix()
    assert paths.adapt_cann_fs_path(yaml_path, root) == real.as_posix()


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


def test_cann_root_reads_opencode_cache(tmp_path: Path, monkeypatch) -> None:
    _isolate_cann_discovery(monkeypatch, tmp_path)
    pkg = tmp_path / "pkg"
    (pkg / "cann-asc-devkit").mkdir(parents=True)
    cache = paths.opencode_cann_root_cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text(str(pkg), encoding="utf-8")
    assert paths.cann_root() == pkg
    root, issues = paths.require_cann_ready()
    assert root == pkg
    assert issues == []


def test_cann_root_uses_ascend_home_path(tmp_path: Path, monkeypatch) -> None:
    _isolate_cann_discovery(monkeypatch, tmp_path)
    home = tmp_path / "latest"
    (home / "aarch64-linux" / "asc").mkdir(parents=True)
    monkeypatch.setenv("ASCEND_HOME_PATH", str(home))
    assert paths.cann_root() == home
    assert paths.require_cann_ready()[1] == []


def test_missing_uo_cann_root_falls_through_to_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    _isolate_cann_discovery(monkeypatch, tmp_path)
    monkeypatch.setenv("UO_CANN_ROOT", str(tmp_path / "deleted"))
    pkg = tmp_path / "pkg"
    (pkg / "cann-metadef").mkdir(parents=True)
    monkeypatch.setattr(paths, "_cann_candidates", lambda: [pkg])
    assert paths.cann_root() == pkg


def test_non_cann_uo_cann_root_falls_through_to_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    _isolate_cann_discovery(monkeypatch, tmp_path)
    junk = tmp_path / "junk"
    junk.mkdir()
    monkeypatch.setenv("UO_CANN_ROOT", str(junk))
    pkg = tmp_path / "pkg"
    (pkg / "cann-asc-devkit").mkdir(parents=True)
    monkeypatch.setattr(paths, "_cann_candidates", lambda: [pkg])
    assert paths.cann_root() == pkg


def test_non_cann_explicit_falls_through_like_doctor(
    tmp_path: Path, monkeypatch
) -> None:
    _isolate_cann_discovery(monkeypatch, tmp_path)
    bad = tmp_path / "operator"
    bad.mkdir()
    pkg = tmp_path / "pkg"
    (pkg / "cann-asc-devkit").mkdir(parents=True)
    monkeypatch.setattr(paths, "_cann_candidates", lambda: [pkg])
    assert paths.cann_root(str(bad)) == pkg
    root, issues = paths.require_cann_ready(str(bad))
    assert root == pkg
    assert issues == []


def test_prepare_gate_matches_require_cann_ready(tmp_path: Path, monkeypatch) -> None:
    _isolate_cann_discovery(monkeypatch, tmp_path)
    pkg = tmp_path / "pkg"
    (pkg / "cann-asc-devkit").mkdir(parents=True)
    monkeypatch.setattr(paths, "_cann_candidates", lambda: [pkg])
    _root, issues = paths.require_cann_ready()
    assert issues == []
    assert _cann_env_block("prepare_layout", {}) is None
    monkeypatch.setattr(paths, "_cann_candidates", lambda: [])
    _root, issues = paths.require_cann_ready()
    assert issues
    blocked = _cann_env_block("prepare_layout", {})
    assert blocked is not None
    assert blocked["error"] == "CANN_ENV_NOT_READY"


def test_check_cann_script_shares_require_cann_ready_gate() -> None:
    text = (paths.repo_root() / "scripts" / "dev" / "check_cann.py").read_text(
        encoding="utf-8"
    )
    assert "require_cann_ready" in text
    assert "return 1" in text
    assert "return 0" in text
