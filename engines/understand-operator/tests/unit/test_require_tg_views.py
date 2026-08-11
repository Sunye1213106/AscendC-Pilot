# -*- coding: utf-8 -*-
"""require_tg_views gate + finalize always projects kernel/tilingdata."""
from __future__ import annotations

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.tg_projection import (
    REQUIRED_COMMIT_VIEWS,
    REQUIRED_TG_VIEWS,
    require_commit_views,
    require_tg_views,
)
from uo_init.tg_views import finalize_tg_views


def test_require_tg_views_lists_missing() -> None:
    assert require_tg_views({}) == list(REQUIRED_TG_VIEWS)
    assert require_tg_views({n: {} for n in REQUIRED_TG_VIEWS}) == []


def test_commit_gate_is_kernel_and_tilingdata_only() -> None:
    assert require_commit_views({}) == list(REQUIRED_COMMIT_VIEWS)
    # A tree with no discoverable TilingKey header still commits: the key-domain
    # views are not part of the commit gate.
    partial = {n: {} for n in REQUIRED_COMMIT_VIEWS}
    assert require_commit_views(partial) == []
    assert require_tg_views(partial) != []


def test_finalize_projects_kernel_and_tilingdata() -> None:
    cm = CodeMap(op_name="other_op", architecture="arch35")
    cm.add_entity(Entity(id="TD", kind=EntityKind.TILING_DATA, name="Td", attrs={}))
    cm.add_entity(
        Entity(
            id="TF",
            kind=EntityKind.TILING_FIELD,
            name="flag",
            attrs={"owner": "Td", "host_writer_sites": [{"expression": "1"}]},
        )
    )
    cm.add_entity(
        Entity(
            id="KB",
            kind=EntityKind.BRANCH,
            name="flag_on",
            attrs={"condition": "flag != 0", "stage": "runtime"},
        )
    )
    views = finalize_tg_views(
        cm,
        existing={
            "tiling/exhaustive_key_space.yaml": {"legal_key_count": 2},
            "tiling/legal_key_index.jsonl": {"rows": [{"tiling_key": 1}, {"tiling_key": 2}]},
        },
    )
    assert require_tg_views(views) == []
    assert "views/kernel.yaml" in views
    assert "views/tilingdata.yaml" in views
    assert views["views/tilingdata.yaml"].get("structs")
