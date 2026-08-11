# -*- coding: utf-8 -*-
"""Framework tests for generic TilingData decoder (no real-operator facts)."""

from __future__ import annotations

import struct

from testcase_agent.tilingdata.decoder import LayoutIncomplete, decode
from testcase_agent.tilingdata.layout import _from_tilingdata_view


def test_generic_decode_uint_fields() -> None:
    layout = {
        "fields": [
            {"name": "DimA", "offset": 0, "size": 4, "type": "uint32_t"},
            {"name": "DimB", "offset": 4, "size": 4, "type": "uint32_t"},
        ]
    }
    raw = struct.pack("<II", 7, 9)
    got = decode(raw, layout)
    assert got == {"DimA": 7, "DimB": 9}


def test_layout_incomplete_on_nested() -> None:
    layout = {
        "fields": [
            {"name": "X", "offset": 0, "size": 4, "nested": True},
        ]
    }
    try:
        decode(b"\x00\x00\x00\x00", layout)
        assert False, "expected LayoutIncomplete"
    except LayoutIncomplete:
        pass


def test_view_promotion_requires_offset_size() -> None:
    view = {
        "structs": [
            {
                "name": "FakeTd",
                "fields": [
                    {"name": "DimA", "offset": 0, "size": 4},
                    {"name": "DimB"},  # missing size → incomplete
                ],
            }
        ]
    }
    assert _from_tilingdata_view(view) is None

    view2 = {
        "structs": [
            {
                "name": "FakeTd",
                "fields": [
                    {"name": "DimA", "offset": 0, "size": 4, "type": "uint32_t"},
                    {"name": "DimB", "offset": 4, "size": 4, "type": "uint32_t"},
                ],
            }
        ]
    }
    layout = _from_tilingdata_view(view2)
    assert layout is not None
    assert [f["name"] for f in layout["fields"]] == ["DimA", "DimB"]
