# -*- coding: utf-8 -*-
"""Content fingerprint and TU-cache correctness."""
from __future__ import annotations

from pathlib import Path

import yaml

from uo_init import tu_cache
from uo_init.clang_walk import CtrlNode, WalkResult, walk_file
from uo_init.extract_cache import (
    compute_extract_fingerprint,
    content_fingerprint,
    skip_reextract_for_unchanged_tus,
    sources_unchanged,
    store_extract_fingerprint,
)


class _FakeCtx:
    cann_root = "D:/cann"
    ops_root = "D:/ops"
    compat_root = "D:/compat"
    op_dir = ""
    arch_dir = "arch35"

    def host_args(self):
        return ["-std=c++17"]

    def kernel_args(self, dtype_variant=None):
        return ["-std=c++17"]


def _seed_scope(uo: Path, rels: list[str]) -> None:
    run = uo / "runs" / "r1" / "scope"
    run.mkdir(parents=True, exist_ok=True)
    (uo / "manifest.yaml").write_text(
        yaml.safe_dump({"current_run_id": "r1", "scope_revision": 1}),
        encoding="utf-8",
    )
    (run / "receipt.yaml").write_text(
        yaml.safe_dump({"frozen_scope": {"confirmed_source_files": rels}}),
        encoding="utf-8",
    )


def test_content_fingerprint_changes_with_bytes(tmp_path):
    host = tmp_path / "op_host"
    host.mkdir()
    source = host / "a.cpp"
    source.write_text("int a;\n", encoding="utf-8")
    first = content_fingerprint(tmp_path, ["op_host/a.cpp"])
    source.write_text("int a; int b;\n", encoding="utf-8")
    second = content_fingerprint(tmp_path, ["op_host/a.cpp"])
    assert first != second


def test_sources_unchanged_after_store(tmp_path):
    host = tmp_path / "op_host"
    host.mkdir()
    (host / "a.cpp").write_text("void f() {}\n", encoding="utf-8")
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    _seed_scope(uo, ["op_host/a.cpp"])
    meta = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    store_extract_fingerprint(uo, meta)
    ok, now = sources_unchanged(tmp_path, uo_root=uo, arch="arch35")
    assert ok is True
    assert now["extract_fingerprint"] == meta["extract_fingerprint"]
    plan = skip_reextract_for_unchanged_tus(tmp_path, uo_root=uo, arch="arch35")
    assert plan["skip_reextract"] is True
    assert plan["unchanged_tus"] == ["op_host/a.cpp"]


def test_warm_walk_reuses_tu_cache_without_cold_parse(tmp_path, monkeypatch):
    monkeypatch.setenv("UO_TU_CACHE", "1")
    monkeypatch.setenv("UO_CACHE_ROOT", str(tmp_path / "cache"))
    tu_cache.reset_stats()

    source = tmp_path / "tiny.cpp"
    source.write_text("int f(int x) { return x; }\n", encoding="utf-8")
    ctx = _FakeCtx()
    ctx.op_dir = str(tmp_path)
    primed = WalkResult(
        path=str(source).replace("\\", "/"),
        controls=[
            CtrlNode(
                id="t:1:0:if:0",
                kind="if",
                file=str(source).replace("\\", "/"),
                line=1,
                condition="1",
                function="f",
            )
        ],
    )
    key = tu_cache.walk_cache_key(source, ctx, side="host")
    tu_cache.store_walk(key, primed, op_dir=str(tmp_path), arch="arch35")

    def _boom(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("cold parse on unchanged cached TU")

    monkeypatch.setattr("uo_init.clang_walk._require_clang", _boom)
    first = walk_file(source, ctx, side="host")
    second = walk_file(source, ctx, side="host")

    assert first.path == primed.path
    assert second.path == primed.path
    assert tu_cache.stats()["hit"] >= 2
