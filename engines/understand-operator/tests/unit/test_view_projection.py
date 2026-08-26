# -*- coding: utf-8 -*-
"""Views the product stops shipping must still answer, and answer the same."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind
from uo_init.store.reader import load_view_blob, load_view_blob_checked
from uo_init.store.view_projection import NOT_SHIPPED, project_view
from uo_init.store.writer import write_codemap


def _cm() -> CodeMap:
    cm = CodeMap(op_name="demo", architecture="arch35")
    cm.add_entity(
        Entity(id="TK_X", kind=EntityKind.TILING_KEY, name="IsTnd", attrs={"decl_order": 0})
    )
    cm.add_entity(
        Entity(
            id="TD_s1",
            kind=EntityKind.TILING_FIELD,
            name="s1Tail",
            attrs={"owner": "TilingData", "host_writer_sites": [{"expression": "s1 % 128"}]},
        )
    )
    cm.add_entity(
        Entity(
            id="KB_rt",
            kind=EntityKind.BRANCH,
            name="tail_nonzero",
            attrs={"condition": "s1Tail != 0"},
            file="k.h",
            line_start=7,
        )
    )
    cm.add_entity(
        Entity(
            id="M_read",
            kind=EntityKind.METHOD,
            name="Process",
            attrs={},
            file="k.h",
            line_start=3,
        )
    )
    cm.relations["R1"] = Relation(
        id="R1",
        kind=RelationKind.READS,
        src="M_read",
        dst="TD_s1",
        attrs={"expression": "s1Tail != 0"},
    )
    return cm


def _product(tmp_path: Path) -> Path:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "demo.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(_cm(), product)
    return product


def test_product_no_longer_embeds_the_projected_views(tmp_path: Path) -> None:
    product = _product(tmp_path)
    conn = sqlite3.connect(str(product))
    try:
        stored = {str(r[0]) for r in conn.execute("SELECT name FROM view_blob")}
    finally:
        conn.close()
    assert stored, "commit still has to write the views it does ship"
    for name in NOT_SHIPPED:
        assert name not in stored
        assert load_view_blob(product, name) is None


def test_absent_view_is_projected_not_reported_missing(tmp_path: Path) -> None:
    product = _product(tmp_path)
    for name in NOT_SHIPPED:
        checked = load_view_blob_checked(product, name)
        assert checked["ok"], (name, checked.get("reason_code"))
        assert checked["fallback"] == "projected"
        assert isinstance(checked["view"], dict)


def test_projection_carries_the_identity_of_the_whole_graph(tmp_path: Path) -> None:
    """A slice must not stamp itself with the size of the slice."""
    product = _product(tmp_path)
    conn = sqlite3.connect(str(product))
    try:
        meta = {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM meta")}
    finally:
        conn.close()
    view = project_view(product, "views/kernel.yaml")
    prov = view["provenance"]
    assert prov["entity_count"] == int(meta["entity_count"])
    assert prov["relation_count"] == int(meta["relation_count"])
    assert prov["canonical_graph_digest"] == meta["cm_canonical_graph_digest"]
    assert view["source"]["graph_fingerprint"] == meta["cm_graph_fingerprint"]


def test_projected_kernel_view_still_answers_the_branch_domain(tmp_path: Path) -> None:
    view = project_view(_product(tmp_path), "views/kernel.yaml")
    by_id = {b["id"]: b for b in view["branches"]}
    assert view["schema"] == "uo-kernel-view/v2"
    assert by_id["KB_rt"]["condition"] == "s1Tail != 0"
    assert by_id["KB_rt"]["tilingdata_fields"] == ["s1Tail"]
    assert by_id["KB_rt"]["file"].endswith("k.h")
    assert by_id["KB_rt"]["line"] == 7


def test_projected_tilingdata_view_keeps_reader_identity(tmp_path: Path) -> None:
    """Reader rows name the reading entity, so its kind has to be in the slice."""
    view = project_view(_product(tmp_path), "views/tilingdata.yaml")
    fields = [f for s in view["structs"] for f in s["fields"]]
    row = next(f for f in fields if f["name"] == "s1Tail")
    assert [r["function"] for r in row["readers"]] == ["Process"]
    assert [r["entity_id"] for r in row["readers"]] == ["M_read"]


def test_long_predicate_survives_the_round_trip(tmp_path: Path) -> None:
    """A clipped predicate still parses as one, so it cannot be clipped."""
    condition = "(" + " && ".join(f"fBaseParams.dim{i} != {i}" for i in range(40)) + ")"
    assert len(condition) > 400
    cm = _cm()
    cm.add_entity(
        Entity(
            id="KB_long",
            kind=EntityKind.BRANCH,
            name="long_guard",
            attrs={"predicate": condition},
            file="k.h",
            line_start=11,
        )
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "long.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)

    conn = sqlite3.connect(str(product))
    try:
        row = conn.execute("SELECT data FROM entity WHERE id = 'KB_long'").fetchone()
    finally:
        conn.close()
    assert json.loads(row[0])["predicate"] == condition

    view = project_view(product, "views/kernel.yaml")
    by_id = {b["id"]: b for b in view["branches"]}
    assert by_id["KB_long"]["condition"] == condition
