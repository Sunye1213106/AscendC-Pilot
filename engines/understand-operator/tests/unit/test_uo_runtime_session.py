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
    pe._STORE["bundle_key"] = (str(other.resolve()), "A", "arch35")
    pe._STORE["bundle_fp"] = "stale-fp"

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


def test_ensure_bundle_hits_memory_for_same_op_without_caller_fingerprint(
    tmp_path: Path, monkeypatch
) -> None:
    from uo_init import pilot_engines as pe
    from uo_init.host_ir import HostIR

    pe._STORE.clear()
    live = {"host_ir": HostIR(backend="memory"), "spec": SimpleNamespace(op_name="Toy")}
    pe._STORE["bundle"] = live
    pe._STORE["bundle_key"] = (str(tmp_path.resolve()), "Toy", "arch35")
    pe._STORE["bundle_fp"] = "fp-live"
    monkeypatch.setattr(
        "uo_init.pilot_engines._current_extract_fingerprint",
        lambda *_a, **_k: "fp-live",
    )
    monkeypatch.setattr(
        "uo_init.pilot_engines._restore_extracted_bundle",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not unpickle")),
    )
    monkeypatch.setattr(
        "uo_init.extract_bundle.extract_host_bundle",
        lambda **_k: (_ for _ in ()).throw(AssertionError("must not re-extract")),
    )
    bundle = pe._ensure_bundle(tmp_path, {"architecture": "arch35", "op_name": "Toy"})
    assert bundle is live
    pe._STORE.clear()


def test_ensure_bundle_rejects_stale_fingerprint(tmp_path: Path, monkeypatch) -> None:
    from uo_init import pilot_engines as pe
    from uo_init.host_ir import HostIR

    pe._STORE.clear()
    pe._STORE["bundle"] = {
        "host_ir": HostIR(backend="stale-mem"),
        "spec": SimpleNamespace(op_name="Toy"),
    }
    pe._STORE["bundle_key"] = (str(tmp_path.resolve()), "Toy", "arch35")
    pe._STORE["bundle_fp"] = "fp-old"
    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    (uo / "ir").mkdir(parents=True)
    pe._dump_ir_pickle(uo / "ir" / "host_ir.pkl", HostIR(backend="pickle"))
    monkeypatch.setattr(
        "uo_init.pilot_engines._current_extract_fingerprint",
        lambda *_a, **_k: "fp-new",
    )
    monkeypatch.setattr(
        "uo_init.op_spec.discover",
        lambda root, arch_dir=None: SimpleNamespace(op_name="Toy", arch_dir="arch35"),
    )
    monkeypatch.setattr(
        "uo_init.extract_bundle.extract_host_bundle",
        lambda **_k: (_ for _ in ()).throw(AssertionError("should restore pickle")),
    )
    bundle = pe._ensure_bundle(tmp_path, {"architecture": "arch35", "op_name": "Toy"})
    assert bundle["host_ir"].backend == "pickle"
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
    pe._STORE["bundle_key"] = ("a", "b", "c")
    pe._STORE["bundle_fp"] = "fp"
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


def test_end_session_can_keep_compile_mem(tmp_path: Path) -> None:
    from uo_init import pilot_engines as pe

    pe._STORE["bundle"] = {"x": 1}
    tu_cache._LIVE_AST["k"] = (object(), object(), "host")
    key = f"{tmp_path.resolve()}|Toy|arch35"
    _COMPILE_MEM[key] = {"codemap": object()}
    end_session(op_root=tmp_path, architecture="arch35", drop_compile_mem=False)
    assert pe._STORE == {}
    assert live_ast_count() == 0
    assert key in _COMPILE_MEM
    _COMPILE_MEM.clear()


def test_analyze_exception_ends_session(tmp_path: Path, monkeypatch) -> None:
    from uo_init import pilot_engines as pe
    from uo_init.codemap_engines import analyze

    pe._STORE["bundle"] = {"x": 1}
    tu_cache._LIVE_AST["k"] = (object(), object(), "host")
    key = f"{tmp_path.resolve()}|Toy|arch35"
    _COMPILE_MEM[key] = {"codemap": object()}

    def boom(*_a, **_k):
        raise RuntimeError("analyze boom")

    monkeypatch.setattr("uo_init.codemap_engines._compiler_inputs", boom)
    out = analyze(tmp_path, {"architecture": "arch35", "op_name": "Toy"})
    assert out.get("ok") is False
    assert pe._STORE == {}
    assert live_ast_count() == 0
    assert key not in _COMPILE_MEM


def test_commit_failure_keeps_compile_mem(tmp_path: Path, monkeypatch) -> None:
    from uo_init import pilot_engines as pe
    from uo_init.codemap_engines import commit

    pe._STORE["bundle"] = {"x": 1}
    tu_cache._LIVE_AST["k"] = (object(), object(), "host")
    tu_cache._WALK_BUNDLE["w"] = [1]
    key = f"{tmp_path.resolve()}|Toy|arch35"
    _COMPILE_MEM[key] = {"codemap": object()}

    def fail_commit(*_a, **_k):
        return {"ok": False, "error": "write failed"}

    monkeypatch.setattr("uo_init.codemap_engines._commit_uo_product", fail_commit)
    out = commit(tmp_path, {"architecture": "arch35", "op_name": "Toy"})
    assert out.get("ok") is False
    assert key in _COMPILE_MEM
    assert live_ast_count() == 0
    assert tu_cache._WALK_BUNDLE == {}
    _COMPILE_MEM.clear()
    pe._STORE.clear()


def test_mark_terminal_ends_uo_init_session(tmp_path: Path) -> None:
    from ascendc_pilot.state import mark_terminal, start_workflow
    from uo_init import include_heal, pilot_engines as pe
    from uo_init.passes import source_text_cache

    start_workflow(tmp_path, "uo-init", architecture="arch35")
    pe._STORE["bundle"] = {"x": 1}
    tu_cache._LIVE_AST["k"] = (object(), object(), "host")
    key = f"{tmp_path.resolve()}|Toy|arch35"
    _COMPILE_MEM[key] = {"codemap": object()}
    mark_terminal(tmp_path, "failed", reason="test abort")
    assert pe._STORE == {}
    assert live_ast_count() == 0
    assert key not in _COMPILE_MEM
    source_text_cache.clear()
    include_heal.reset_index_cache()
