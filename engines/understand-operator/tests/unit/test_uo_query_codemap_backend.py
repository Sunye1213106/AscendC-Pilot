from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def _product(project: Path) -> Path:
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.ARCH, "arch35")
    query = cm.upsert(
        EntityKind.INPUT,
        "query",
        attrs={"api_kind": "tensor", "api_index": 0, "provenance": "test"},
    )
    attr = cm.upsert(
        EntityKind.INPUT,
        "layout",
        attrs={"api_kind": "attribute", "api_attr_index": 0, "provenance": "test"},
    )
    output = cm.upsert(
        EntityKind.OUTPUT,
        "dq",
        attrs={"api_kind": "tensor", "api_index": 0, "provenance": "test"},
    )
    key = cm.upsert(
        EntityKind.TILING_KEY,
        "IsTnd",
        attrs={"source_declared": True, "decl_order": 0, "bit_width": 1},
    )
    data = cm.upsert(EntityKind.TILING_DATA, "ToyTilingData")
    field = cm.upsert(
        EntityKind.TILING_FIELD,
        "s1",
        attrs={"owner": "ToyTilingData", "qualified_name": "ToyTilingData::s1"},
    )
    template_arg = cm.upsert(EntityKind.TEMPLATE_ARG, "IsTnd")
    kernel = cm.upsert(EntityKind.KERNEL, "toy_kernel")
    unresolved = cm.upsert(
        EntityKind.OTHER,
        "kernel_call_edges",
        attrs={"role": "unresolved", "reason": "kernel_call_edges"},
        status="unresolved",
        confidence=0.0,
    )
    assert attr and unresolved
    cm.link(RelationKind.DECLARES, data.id, field.id, attrs={"provenance": "test"})
    cm.link(RelationKind.DERIVES, query.id, key.id, attrs={"provenance": "test"})
    cm.link(RelationKind.BINDS, key.id, template_arg.id, attrs={"provenance": "test"})
    cm.link(RelationKind.CONTROLS, template_arg.id, kernel.id, attrs={"provenance": "test"})
    cm.link(RelationKind.FLOWS_TO, data.id, kernel.id, attrs={"provenance": "test"})
    cm.link(RelationKind.FLOWS_TO, query.id, kernel.id, attrs={"provenance": "test"})
    cm.link(RelationKind.FLOWS_TO, kernel.id, output.id, attrs={"provenance": "test"})

    product = project / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, product)
    return product


def test_open_query_prefers_uo_from_project_root(tmp_path: Path) -> None:
    product = _product(tmp_path)
    q = open_query(tmp_path)
    assert q.backend == "codemap"
    assert q.product == product.resolve()
    assert [row["name"] for row in q.tiling_keys()] == ["IsTnd"]
    assert q.tiling_data("ToyTilingData")[0]["name"] == "ToyTilingData"
    assert q.tiling_fields("ToyTilingData")[0]["name"] == "s1"
    assert q.unresolved()[0]["name"] == "kernel_call_edges"
    assert q.find_path("query", "dq")


def test_open_query_from_arch_scoped_uo_dir(tmp_path: Path) -> None:
    _product(tmp_path)
    uo_dir = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    q = open_query(uo_dir)
    assert q.backend == "codemap"
    assert q.summary()["has_input_output_path"] is True


def test_new_api_and_legacy_methods_share_same_codemap(tmp_path: Path) -> None:
    _product(tmp_path)
    q = open_query(tmp_path)

    api = q.operator_api()
    assert [row["name"] for row in api["tensor_inputs"]] == ["query"]
    assert [row["name"] for row in api["attributes"]] == ["layout"]
    assert [row["name"] for row in api["outputs"]] == ["dq"]

    search = q.search("IsTnd")
    assert any(row["kind"] == "TILING_KEY" for row in search)
    key_id = next(row["id"] for row in search if row["kind"] == "TILING_KEY")
    assert q.neighbors(key_id, depth=2)
    assert q.templates_for_key(key_id)
    assert q.tiling_field("s1")
    field_hit = q.field_impact("s1")
    assert field_hit["ok"] is True
    assert "neighbors" not in field_hit
    forward = q.slice_forward([key_id], depth=2)
    assert any(row["id"] == key_id for row in forward["nodes"])
    assert forward["truncated"] is False
    backward = q.slice_backward([key_id], edge_kinds=["DERIVES"], depth=1)
    assert any(row["name"] == "query" for row in backward["nodes"])


def test_open_query_accepts_direct_uo_path(tmp_path: Path) -> None:
    product = _product(tmp_path)
    q = open_query(product)
    assert q.backend == "codemap"
    assert q.audit()["evidence_backed_input_output_path"] is True


def test_open_query_rejects_legacy_top_level_uo_dir(tmp_path: Path) -> None:
    import pytest

    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(EntityKind.ARCH, "arch35")
    legacy = tmp_path / ".ascendc-pilot" / "uo" / "toy.arch35.uo"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, legacy)
    with pytest.raises(FileNotFoundError):
        open_query(tmp_path)


def test_open_query_rejects_sqlite_only_tree(tmp_path: Path) -> None:
    import pytest

    db = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "indexes" / "kb_graph.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not-a-product")
    with pytest.raises(FileNotFoundError):
        open_query(tmp_path)
