# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from uo_init import tu_cache
from uo_init.build import _COMPILE_MEM, drop_compile_mem, store_compile_cache
from uo_init.runtime import end_session, live_ast_count


def test_clear_live_ast_also_drops_walk_bundle() -> None:
    tu_cache.reset_stats()
    tu_cache._LIVE_AST["k"] = (object(), object(), "host")
    tu_cache._WALK_BUNDLE["w"] = [object()]
    tu_cache.clear_live_ast()
    assert tu_cache._LIVE_AST == {}
    assert tu_cache._WALK_BUNDLE == {}


def test_extract_host_bundle_clears_live_ast_on_exception(monkeypatch) -> None:
    from uo_init import extract_bundle

    tu_cache.reset_stats()
    tu_cache._LIVE_AST["k"] = (object(), object(), "host")
    tu_cache._WALK_BUNDLE["w"] = [object()]

    def boom(*_a, **_k):
        tu_cache._LIVE_AST["during"] = (object(), object(), "kernel")
        raise RuntimeError("SCOPE_CLANG_CLOSURE_INCOMPLETE: test")

    monkeypatch.setattr("uo_init.op_spec.discover", boom)
    with pytest.raises(RuntimeError, match="SCOPE_CLANG"):
        extract_bundle.extract_host_bundle(
            op_dir=".",
            cann_root=".",
            arch_dir="arch35",
            with_kernel=False,
        )
    assert tu_cache._LIVE_AST == {}
    assert tu_cache._WALK_BUNDLE == {}


def test_ensure_bundle_does_not_reuse_other_operator(tmp_path: Path, monkeypatch) -> None:
    from uo_init import pilot_engines as pe
    from uo_init.host_ir import HostIR

    pe._STORE.clear()
    other = tmp_path / "opA"
    other.mkdir()
    pe._STORE["bundle"] = {"host_ir": HostIR(backend="stale"), "spec": SimpleNamespace(op_name="A")}
    pe._STORE["bundle_key"] = (str(other.resolve()), "A", "arch35", "")

    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    (uo / "ir").mkdir(parents=True)
    pe._dump_ir_pickle(uo / "ir" / "host_ir.pkl", HostIR(backend="clang"))
    monkeypatch.setattr(
        "uo_init.op_spec.discover",
        lambda root, arch_dir=None: SimpleNamespace(op_name="Toy", arch_dir="arch35"),
    )
    monkeypatch.setattr(
        "uo_init.extract_bundle.extract_host_bundle",
        lambda **_k: (_ for _ in ()).throw(AssertionError("should restore pickle")),
    )
    bundle = pe._ensure_bundle(tmp_path, {"architecture": "arch35", "op_name": "Toy"})
    assert bundle["host_ir"].backend == "clang"
    assert pe._STORE["bundle_key"][1] == "Toy"
    pe._STORE.clear()


def test_drop_compile_mem_keeps_disk_pickle(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    store_compile_cache(
        root,
        "Toy",
        "arch35",
        {"codemap": object(), "_merged_views": {}, "summary": {}, "gaps": [], "audit": {}, "tg_views": {}},
    )
    key = f"{root.resolve()}|Toy|arch35"
    assert key in _COMPILE_MEM
    disk = root / ".ascendc-pilot" / "arch35" / "uo" / "ir" / "_codemap_compile_cache.pkl"
    assert disk.is_file()
    drop_compile_mem(root, architecture="arch35")
    assert key not in _COMPILE_MEM
    assert disk.is_file()


def test_end_session_clears_process_caches(tmp_path: Path) -> None:
    from uo_init import include_heal, pilot_engines as pe
    from uo_init.passes import source_text_cache
    from uo_init.source_index import reset_index_cache
    from uo_init.source_index.cache import cache_put

    tu_cache._LIVE_AST["k"] = (object(), object(), "host")
    tu_cache._WALK_BUNDLE["w"] = [1]
    pe._STORE["bundle"] = {"x": 1}
    pe._STORE["bundle_key"] = ("a", "b", "c", "")
    _COMPILE_MEM["k"] = {"codemap": object()}
    src = tmp_path / "a.cpp"
    src.write_text("int x;", encoding="utf-8")
    source_text_cache.read_text(src)
    cache_put(str(src.resolve()), object())
    include_heal._INDEX_CACHE[("r",)] = {"a.h": ["x"]}
    end_session()
    assert live_ast_count() == 0
    assert tu_cache._WALK_BUNDLE == {}
    assert pe._STORE == {}
    assert _COMPILE_MEM == {}
    assert source_text_cache.stats()["cached_files"] == 0
    reset_index_cache()
    assert include_heal._INDEX_CACHE == {}
