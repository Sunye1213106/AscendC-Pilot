# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.query.sql import UoSqlQuery
from uo_init.store.accel import ACCEL_VERSION, has_accel, has_template_block, upgrade
from uo_init.store.writer import write_codemap


def _product(cm: CodeMap, tmp_path: Path) -> Path:
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    return product


def test_writer_builds_name_leaf(tmp_path: Path) -> None:
    src = tmp_path / "op_kernel" / "arch35" / "key.h"
    src.parent.mkdir(parents=True)
    src.write_text("ASCENDC_TPL_ARGS_SEL(\nASCENDC_TPL_BOOL_SEL(Flag, 0, 1)\n)\n", encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="K_Flag",
            kind=EntityKind.TILING_KEY,
            name="Flag",
            attrs={"source_declared": True, "value_domain": ["0", "1"]},
            file="op_kernel/arch35/key.h",
            line_start=1,
            status="confirmed",
        )
    )
    product = _product(cm, tmp_path)
    q = UoSqlQuery(product)
    with q._connect() as conn:
        assert has_accel(conn)
    out = q.agent_query(pattern="Flag")
    assert out["ok"]
    assert out["cards"]


def test_upgrade_adds_template_block_and_sel_lines(tmp_path: Path) -> None:
    header = tmp_path / "op_kernel" / "arch35" / "template_tiling_key.h"
    header.parent.mkdir(parents=True)
    header.write_text(
        "\n" * 9
        + "ASCENDC_TPL_ARGS_SEL(\nASCENDC_TPL_BOOL_SEL(IsTnd, 1)\n)\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.add_entity(
        Entity(
            id="K_IsTnd",
            kind=EntityKind.TILING_KEY,
            name="IsTnd",
            attrs={"source_declared": True, "value_domain": ["0", "1"]},
            file="op_kernel/arch35/template_tiling_key.h",
            line_start=2,
            status="confirmed",
        )
    )
    cm.add_entity(
        Entity(
            id="T_SEL0",
            kind=EntityKind.TEMPLATE,
            name="ARGS_SEL_0",
            attrs={
                "tpl_role": "args_sel_group",
                "sel_group_index": 0,
                "fixed_fields": {"IsTnd": "1"},
                "field_domains": {},
            },
            file="op_kernel/arch35/template_tiling_key.h",
            line_start=0,
            status="confirmed",
        )
    )
    product = _product(cm, tmp_path)
    # Writer may not have stored template_blocks.yaml; inject a tiny blob.
    import json
    import sqlite3

    conn = sqlite3.connect(str(product))
    conn.execute(
        "INSERT OR REPLACE INTO view_blob(name, schema_id, data) VALUES (?,?,?)",
        (
            "tiling/template_blocks.yaml",
            "uo-template-blocks/v1",
            json.dumps(
                {
                    "schema": "uo-template-blocks/v1",
                    "blocks": [
                        {
                            "id": "KTPL_SEL0",
                            "name": "ARGS_SEL_0",
                            "sel_group_index": 0,
                            "fixed_fields": {"IsTnd": "1"},
                            "field_domains": {},
                            "product_count": 1,
                        }
                    ],
                }
            ),
        ),
    )
    conn.commit()
    conn.close()
    stats = upgrade(product, op_root=tmp_path, architecture="arch35", vacuum=False)
    assert stats["template_blocks"] == 1
    assert stats["sel_lines_patched"] >= 1
    q = UoSqlQuery(product)
    with q._connect() as conn:
        assert has_template_block(conn)
        row = conn.execute(
            "SELECT line_start FROM entity WHERE name='ARGS_SEL_0'"
        ).fetchone()
        assert int(row[0]) == 10
    cover = q.agent_query(pattern="IsTnd=1")
    assert cover["shape"] == "cover"
    assert int(cover.get("matching_block_count") or 0) >= 1
    sites = cover.get("sel_sites") or []
    assert sites and int(sites[0]["line"]) == 10
    name = q.agent_query(pattern="IsTnd")
    extras = (name.get("cards") or [{}])[0].get("extras") or {}
    assert extras.get("sel_sites")


def test_branch_expression_is_not_a_name_leaf() -> None:
    from uo_init.store.accel import _indexable_leaves

    assert _indexable_leaves("BRANCH", "!(dim0 == fBaseParams.b)") == []
    assert _indexable_leaves("BRANCH", "OP_CHECK_IF((dim0 != b))") == ["op_check_if"]
    assert "s1inner" in _indexable_leaves("TILING_FIELD", "s1Inner")
