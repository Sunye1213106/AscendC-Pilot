# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.kb_model import KnowledgeBase
from uo_init.materialize_tiling import (
    build_legal_key_rows,
    build_template_blocks,
    materialize_into_kb,
)
from uo_init.tpl_dsl import parse_file


HEADER = Path(
    r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad"
    r"\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h"
)


def test_template_blocks_sum_to_8705():
    if not HEADER.is_file():
        return
    schema = parse_file(HEADER)
    blocks = build_template_blocks(schema)
    assert len(blocks) == 65
    assert sum(b.product_count for b in blocks) == 8705


def test_legal_keys_unique_and_roundtrip():
    if not HEADER.is_file():
        return
    schema = parse_file(HEADER)
    rows = build_legal_key_rows(
        schema, binding=None, blocker_ids=[], input_controllable_fraction=0.2
    )
    assert len(rows) == 8705
    assert len({r.tiling_key for r in rows}) == 8705
    for row in rows[:20]:
        dec = schema.decode_tiling_key(row.tiling_key)
        assert all(dec[k] == row.dims[k] for k in row.dims)


def test_materialize_into_kb_writes_notes():
    if not HEADER.is_file():
        return
    schema = parse_file(HEADER)
    kb = KnowledgeBase(op_name="FlashAttentionScoreGrad", architecture="arch35")
    kb.notes["quality"] = {"source_closure": 0.9, "input_controllability": 0.2}
    out = materialize_into_kb(kb, schema=schema, header_path=str(HEADER))
    assert out["ok"] is True
    assert out["legal_key_count"] == 8705
    mat = kb.notes["tiling_materialize"]
    assert len(mat["template_blocks"]) == 65
    assert mat["key_field_obligations"]
    assert sum(1 for n in kb.iter_nodes() if n.kind == "TilingKeyDim") == 19
