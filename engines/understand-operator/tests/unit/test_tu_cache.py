# -*- coding: utf-8 -*-
"""P2: durable WalkResult disk cache for walk_file."""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.clang_walk import CtrlNode, WalkResult, walk_file
from uo_init import tu_cache


class _FakeCtx:
    cann_root = "D:/cann"
    ops_root = "D:/ops"
    compat_root = "D:/compat"
    op_dir = ""
    arch_dir = "arch35"

    def host_args(self):
        return ["-std=c++17", "-I", "D:/cann/include"]

    def kernel_args(self, dtype_variant=None):
        return ["-std=c++17", f"-DDTYPE={dtype_variant or ''}"]


def _sample_result(path: str) -> WalkResult:
    return WalkResult(
        path=path.replace("\\", "/"),
        controls=[
            CtrlNode(
                id=f"{path}:1:0:if:0",
                kind="if",
                file=path.replace("\\", "/"),
                line=1,
                condition="x > 0",
                function="f",
            )
        ],
        writes=[],
        local_writes=[],
        call_sites=[],
        functions={},
        diagnostics=[],
        class_fields=set(),
        field_decls={},
        local_decls=[],
    )


def test_deserialize_func_record_accepts_usr():
    """Analyze loads walk cache; FuncRecord identity fields must round-trip."""
    from uo_init.clang_walk import FuncRecord

    wr = WalkResult(
        path="op_kernel/k.cpp",
        functions={
            "Process": FuncRecord(
                name="Process",
                file="op_kernel/k.cpp",
                line=10,
                usr="c:@F@Process",
                qualified_name="Ns::Process",
            )
        },
    )
    payload = tu_cache.serialize_walk_result(wr)
    payload["data"]["functions"]["Process"]["usr"] = "c:@F@Process"
    payload["data"]["functions"]["Process"]["qualified_name"] = "Ns::Process"
    got = tu_cache.deserialize_walk_result(payload)
    rec = got.functions["Process"]
    assert rec.usr == "c:@F@Process"
    assert rec.qualified_name == "Ns::Process"


def test_walk_result_macro_uses_roundtrip():
    from uo_init.clang_walk import MacroUse

    wr = WalkResult(
        path="op_kernel/k.cpp",
        macro_uses=[
            MacroUse(
                name="COMMON_RUN_PARAM",
                file="op_kernel/k.cpp",
                line=20,
                parent_name="Process",
                parent_kind="FUNCTION_DECL",
            )
        ],
    )
    payload = tu_cache.serialize_walk_result(wr)
    assert payload["version"] == tu_cache.CACHE_VERSION
    got = tu_cache.deserialize_walk_result(payload)
    assert len(got.macro_uses) == 1
    use = got.macro_uses[0]
    assert use.name == "COMMON_RUN_PARAM"
    assert use.parent_name == "Process"
    assert use.parent_kind == "FUNCTION_DECL"


def test_walk_result_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("UO_TU_CACHE", "1")
    monkeypatch.setenv("UO_CACHE_ROOT", str(tmp_path / "cache"))
    tu_cache.reset_stats()
    src = tmp_path / "tiny.cpp"
    src.write_text("int f(int x) { if (x > 0) return 1; return 0; }\n", encoding="utf-8")
    result = _sample_result(str(src))
    key = tu_cache.walk_cache_key(src, _FakeCtx(), side="host", op_needle="tiny")
    path = tu_cache.store_walk(key, result, op_dir=str(tmp_path), arch="arch35")
    assert path is not None and path.is_file()
    loaded = tu_cache.load_walk(key, op_dir=str(tmp_path), arch="arch35")
    assert loaded is not None
    assert loaded.path == result.path
    assert len(loaded.controls) == 1
    assert loaded.controls[0].condition == "x > 0"
    assert tu_cache.stats()["store"] == 1
    assert tu_cache.stats()["hit"] == 1


def test_walk_file_second_call_is_cache_hit(tmp_path, monkeypatch):
    """Second walk_file must return the disk IR without calling libclang."""
    monkeypatch.setenv("UO_TU_CACHE", "1")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("UO_CACHE_ROOT", str(cache_root))
    tu_cache.reset_stats()

    src = tmp_path / "op.cpp"
    src.write_text("void g() {}\n", encoding="utf-8")
    ctx = _FakeCtx()
    ctx.op_dir = str(tmp_path)

    primed = _sample_result(str(src))
    key = tu_cache.walk_cache_key(src, ctx, side="host", op_needle="op")
    tu_cache.store_walk(key, primed, op_dir=str(tmp_path), arch="arch35")
    tu_cache.reset_stats()

    def _boom(*_a, **_k):  # pragma: no cover - must not run
        raise AssertionError("libclang parse must not run on cache hit")

    monkeypatch.setattr("uo_init.clang_walk._require_clang", _boom)

    hit = walk_file(src, ctx, side="host", op_needle="op")
    assert hit.controls[0].function == "f"
    assert tu_cache.stats()["hit"] == 1
    assert tu_cache.stats()["miss"] == 0

    # Content change → new key → miss path would need clang; we only assert key moves.
    src.write_text("void g() { int y = 1; }\n", encoding="utf-8")
    new_key = tu_cache.walk_cache_key(src, ctx, side="host", op_needle="op")
    assert new_key != key
    assert tu_cache.load_walk(new_key, op_dir=str(tmp_path), arch="arch35") is None


def test_cache_disabled_bypasses(tmp_path, monkeypatch):
    monkeypatch.setenv("UO_TU_CACHE", "0")
    monkeypatch.setenv("UO_CACHE_ROOT", str(tmp_path / "cache"))
    tu_cache.reset_stats()
    src = tmp_path / "a.cpp"
    src.write_text("int x;\n", encoding="utf-8")
    key = tu_cache.walk_cache_key(src, _FakeCtx())
    assert tu_cache.store_walk(key, _sample_result(str(src)), op_dir=str(tmp_path)) is None
    assert tu_cache.load_walk(key, op_dir=str(tmp_path)) is None
    assert tu_cache.stats()["bypass"] >= 2
