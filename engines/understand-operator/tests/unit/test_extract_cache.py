# -*- coding: utf-8 -*-
"""Content fingerprint and TU-cache correctness."""
from __future__ import annotations

from pathlib import Path

import pytest
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

    def kernel_args(self, dtype_variant=None, source_path=None, orig_assignment=None):
        args = ["-std=c++17"]
        if dtype_variant:
            args.append(f"-DDTYPE={dtype_variant}")
        if orig_assignment:
            args.extend(f"-D{k}={v}" for k, v in orig_assignment.items())
        return args


def _seed_scope(uo: Path, rels: list[str]) -> None:
    run = uo / "runs" / "r1" / "scope"
    summary = uo / "summary"
    run.mkdir(parents=True, exist_ok=True)
    summary.mkdir(parents=True, exist_ok=True)
    (uo / "manifest.yaml").write_text(
        yaml.safe_dump({"current_run_id": "r1", "scope_revision": 1}),
        encoding="utf-8",
    )
    payload = {
        "confirmed_source_files": rels,
        "files": [{"path": r, "provenance": "clang_tu"} for r in rels],
        "notes": ["clang_scope_status=complete"],
    }
    (summary / "scope_set.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    (run / "scope_set.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
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


def test_fingerprint_fails_without_clang_confirmed_list(tmp_path):
    host = tmp_path / "op_host"
    host.mkdir()
    (host / "a.cpp").write_text("void f() {}\n", encoding="utf-8")
    (host / "arch22").mkdir()
    (host / "arch22" / "old.cpp").write_text("void g() {}\n", encoding="utf-8")
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    uo.mkdir(parents=True)
    (uo / "manifest.yaml").write_text(
        yaml.safe_dump({"current_run_id": "r1", "scope_revision": 1}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="SCOPE_CONFIRMED_SOURCES_MISSING"):
        compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")


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


def test_parse_cache_key_ignores_walker_flags(tmp_path):
    source = tmp_path / "tiny.cpp"
    source.write_text("int f(int x) { return x; }\n", encoding="utf-8")
    ctx = _FakeCtx()
    ctx.op_dir = str(tmp_path)
    parse = tu_cache.parse_cache_key(source, ctx, side="host")
    parse_again = tu_cache.parse_cache_key(source, ctx, side="host")
    walk = tu_cache.walk_cache_key(
        source, ctx, side="host", op_needle="flash", collect_writes=False
    )
    assert parse == parse_again
    assert parse != walk


def test_parse_cache_key_changes_with_orig_assignment(tmp_path):
    source = tmp_path / "k.cpp"
    source.write_text("void kernel() {}\n", encoding="utf-8")
    ctx = _FakeCtx()
    ctx.op_dir = str(tmp_path)
    plain = tu_cache.parse_cache_key(source, ctx, side="kernel", dtype_variant="DT_FLOAT16")
    mixed = tu_cache.parse_cache_key(
        source,
        ctx,
        side="kernel",
        dtype_variant="DT_FLOAT16",
        orig_assignment={"ORIG_DTYPE_QUERY": "DT_INT8"},
    )
    assert plain != mixed


def test_parse_cache_key_honors_explicit_parse_flags(tmp_path):
    source = tmp_path / "tiny.cpp"
    source.write_text("int f(int x) { return x; }\n", encoding="utf-8")
    ctx = _FakeCtx()
    ctx.op_dir = str(tmp_path)
    via_ctx = tu_cache.parse_cache_key(source, ctx, side="host")
    via_flags = tu_cache.parse_cache_key(
        source, ctx, side="host", parse_flags=ctx.host_args()
    )
    other = tu_cache.parse_cache_key(
        source, ctx, side="host", parse_flags=["-std=c++17", "-DFOO=1"]
    )
    assert via_ctx == via_flags
    assert via_ctx != other


def test_content_fingerprint_reuses_sha_when_mtime_size_match(tmp_path, monkeypatch):
    """Unchanged mtime+size must not re-read file bytes for the extract fingerprint."""
    host = tmp_path / "op_host"
    host.mkdir()
    (host / "a.cpp").write_text("int a;\n", encoding="utf-8")
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    _seed_scope(uo, ["op_host/a.cpp"])
    first = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    store_extract_fingerprint(uo, first)

    def _boom(path):  # pragma: no cover
        raise AssertionError(f"sha256_file must not run on unchanged stamp: {path}")

    monkeypatch.setattr("uo_init.extract_cache.sha256_file", _boom)
    second = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    assert second["extract_fingerprint"] == first["extract_fingerprint"]
    assert second.get("reused_stamp_files") == ["op_host/a.cpp"]


def test_skip_reextract_reports_only_changed_file(tmp_path):
    host = tmp_path / "op_host"
    host.mkdir()
    (host / "a.cpp").write_text("void f() {}\n", encoding="utf-8")
    (host / "b.cpp").write_text("void g() {}\n", encoding="utf-8")
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    _seed_scope(uo, ["op_host/a.cpp", "op_host/b.cpp"])
    meta = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    store_extract_fingerprint(uo, meta)
    (host / "b.cpp").write_text("void g() { return; }\n", encoding="utf-8")

    plan = skip_reextract_for_unchanged_tus(tmp_path, uo_root=uo, arch="arch35")
    assert plan["skip_reextract"] is False
    assert plan["changed_or_cold"] == ["op_host/b.cpp"]
    assert plan["unchanged_tus"] == ["op_host/a.cpp"]


def test_header_change_marks_including_cpp(tmp_path):
    host = tmp_path / "op_host"
    host.mkdir()
    (host / "shared.h").write_text("int k = 1;\n", encoding="utf-8")
    (host / "a.cpp").write_text('#include "shared.h"\nvoid f() {}\n', encoding="utf-8")
    (host / "b.cpp").write_text("void g() {}\n", encoding="utf-8")
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    _seed_scope(uo, ["op_host/a.cpp", "op_host/b.cpp", "op_host/shared.h"])
    meta = compute_extract_fingerprint(tmp_path, uo_root=uo, arch="arch35")
    store_extract_fingerprint(uo, meta)
    (host / "shared.h").write_text("int k = 2;\n", encoding="utf-8")

    plan = skip_reextract_for_unchanged_tus(tmp_path, uo_root=uo, arch="arch35")
    assert plan["skip_reextract"] is False
    changed = set(plan["changed_or_cold"] or [])
    assert "op_host/shared.h" in changed
    assert "op_host/a.cpp" in changed
    assert "op_host/b.cpp" not in changed
