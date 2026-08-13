from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.source_locator import open_locator
from uo_init.store.writer import write_codemap


def _product(tmp_path: Path) -> Path:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.TILING_KEY,
        "SplitAxis",
        attrs={
            "source_declared": True,
            "decl_order": 1,
            "packing_value_sites": [
                {
                    "file": "op_host/toy_tiling.cpp",
                    "line": 1444,
                    "lhs": "splitAxis",
                    "rhs": "fBaseParams.splitAxis",
                    "kind": "declaration",
                },
                {
                    "file": "op_host/toy_tiling.cpp",
                    "line": 1645,
                    "lhs": "fBaseParams.splitAxis",
                    "rhs": "SplitAxisEnum::BN2",
                    "kind": "assignment",
                    "function": "SetSplitAxis",
                },
            ],
        },
        file="op_kernel/toy_tiling_key.h",
        line=56,
        status="confirmed",
    )
    cm.upsert(
        EntityKind.TILING_FIELD,
        "sparseMode",
        attrs={
            "owner": "ToyTilingData",
            "qualified_name": "ToyTilingData::sparseMode",
            "host_writer_sites": [
                {
                    "file": "op_host/toy_tiling.cpp",
                    "line": 1862,
                    "receiver": "baseParams_",
                    "expression": "fBaseParams.sparseMode",
                    "mode": "setter",
                }
            ],
            "value_defining_sites": [
                {
                    "file": "op_host/toy_tiling.cpp",
                    "line": 1190,
                    "lhs": "fBaseParams.sparseMode",
                    "rhs": "SparseMode::NO_MASK",
                    "kind": "assignment",
                    "function": "ProcessSparseModeInfo",
                }
            ],
        },
        file="op_kernel/toy_tiling_data.h",
        line=114,
        status="confirmed",
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, product)
    return product


def test_open_locator_prefers_uo_product(tmp_path: Path) -> None:
    product = _product(tmp_path)
    loc = open_locator(product.parent)
    assert loc.database == product.resolve()
    hits = loc.locate_dim("SplitAxis")
    files = {(h.file, h.line_start) for h in hits}
    assert ("op_kernel/toy_tiling_key.h", 56) in files
    assert ("op_host/toy_tiling.cpp", 1444) in files
    assert ("op_host/toy_tiling.cpp", 1645) in files
    assert any("splitAxis" in (h.snippet or "") for h in hits)


def test_locate_field_exposes_host_writer_sites(tmp_path: Path) -> None:
    _product(tmp_path)
    loc = open_locator(tmp_path)
    hits = loc.locate_field("sparseMode")
    files = {(h.file, h.line_start) for h in hits}
    assert ("op_kernel/toy_tiling_data.h", 114) in files
    assert ("op_host/toy_tiling.cpp", 1862) in files
    assert ("op_host/toy_tiling.cpp", 1190) in files
    assert any("NO_MASK" in (h.snippet or "") for h in hits)


def test_open_locator_rejects_sqlite_only_tree(tmp_path: Path) -> None:
    import pytest

    db = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "indexes" / "kb_graph.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        open_locator(tmp_path)
