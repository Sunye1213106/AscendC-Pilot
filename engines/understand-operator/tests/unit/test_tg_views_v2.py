# -*- coding: utf-8 -*-
from __future__ import annotations

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind
from uo_init.tg_views import project_kernel_view, project_tilingdata_view


def _cm() -> CodeMap:
    cm = CodeMap(op_name="demo", architecture="arch35")
    cm.add_entity(Entity(id="TK_X", kind=EntityKind.TILING_KEY, name="IsTnd", attrs={}))
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
            attrs={"condition": "s1Tail != 0", "evaluation_stage": ""},
        )
    )
    cm.add_entity(
        Entity(
            id="KB_ce",
            kind=EntityKind.BRANCH,
            name="is_tnd",
            attrs={"condition": "IsTnd == 1", "stage": "constexpr"},
        )
    )
    cm.relations["R1"] = Relation(
        id="R1",
        kind=RelationKind.READS,
        src="KB_rt",
        dst="TD_s1",
        attrs={"expression": "s1Tail != 0"},
    )
    return cm


def test_kernel_view_v2_records_tilingdata_fields_and_runtime_stage() -> None:
    view = project_kernel_view(_cm())
    assert view["schema"] == "uo-kernel-view/v2"
    by_id = {b["id"]: b for b in view["branches"]}
    assert "s1Tail" in by_id["KB_rt"]["tilingdata_fields"]
    assert by_id["KB_rt"]["stage"] == "runtime"
    assert by_id["KB_ce"]["stage"] == "constexpr"
    assert by_id["KB_ce"]["key_specialization"]["tiling_key_dims"] == ["IsTnd"]


def test_tilingdata_view_v2_classifies_and_extracts_value_classes() -> None:
    view = project_tilingdata_view(_cm())
    assert view["schema"] == "uo-tilingdata-view/v2"
    field = view["structs"][0]["fields"][0]
    assert field["name"] == "s1Tail"
    assert field["field_class"] in {"control", "boundary"}
    preds = {c["predicate"] for c in field["value_classes"]}
    assert "s1Tail != 0" in preds
    assert "s1Tail == 0" in preds
