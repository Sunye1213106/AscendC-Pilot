# -*- coding: utf-8 -*-
"""Replay the bind-init session's real uo-query argv against the FAG .uo."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from uo_init.store.reader import find_uo_product
from uo_init.uo_query import open_query


def _resolve_fag() -> tuple[Path | None, Path | None]:
    for root in (
        Path(
            r"D:\TEST\pr_workspace\.ascendc-pr"
            r"\gitcode.com--cann--ops-transformer--pr-9851"
            r"\attention\flash_attention_score_grad"
        ),
        Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
        Path(r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad"),
    ):
        product = find_uo_product(root, architecture="arch35")
        if product is not None and Path(product).is_file():
            return root, Path(product)
    return None, None


FAG_ROOT, FAG_PRODUCT = _resolve_fag()

pytestmark = pytest.mark.skipif(
    FAG_PRODUCT is None or not Path(FAG_PRODUCT).is_file(),
    reason="FAG arch35 .uo product is not present",
)


@pytest.fixture(scope="module")
def q():
    return open_query(FAG_ROOT, architecture="arch35")


def _dump_size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def _blob(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def test_bind_session_index_stays_small(q) -> None:
    out = q.agent_query()
    assert out["shape"] == "index"
    assert _dump_size(out) < 8_000
    hint = str(out.get("hint") or "")
    assert "Dim=" in hint
    assert "IsTnd=1" in hint or "Name=Value" in hint
    assert "Dim=<" not in hint


def test_bind_session_keep_prob_card(q) -> None:
    out = q.agent_query(pattern="keep_prob")
    assert out["shape"] == "name"
    blob = _blob(out)
    assert ".ATTR(keep_prob" in blob or "keep_prob" in blob
    assert "proto" in blob.lower() or out["cards"]
    card = (out.get("cards") or [{}])[0]
    assert card.get("file")
    assert int(card.get("line") or 0) > 0
    assert _dump_size(out) < 8_000


@pytest.mark.parametrize("name", ["InputDType", "S1TemplateNum"])
def test_bind_session_tiling_key_keeps_writers(q, name: str) -> None:
    out = q.agent_query(pattern=name)
    assert out["shape"] == "name"
    extras = {}
    for card in out.get("cards") or []:
        if str(card.get("kind") or "") == "TILING_KEY":
            extras = card.get("extras") if isinstance(card.get("extras"), dict) else {}
            derives = (card.get("edges") or {}).get("DERIVES") or {}
            assert len(list(derives.get("neighbors") or [])) <= 3
            break
    writers = extras.get("writers") or []
    assert writers, extras
    assert any(int(row.get("line") or 0) > 0 and row.get("file") for row in writers)
    assert _dump_size(out) < 8_000


def test_bind_session_bad_dim_true_is_honest_zero(q) -> None:
    out = q.agent_query(pattern="Dim=IsTnd=true")
    assert out["shape"] == "cover"
    assert int(out.get("matching_block_count") or 0) == 0
    assert not (out.get("dim_coverage") or {})
    assert (out.get("coverage") or {}).get("answerable") is not True
    hint = str(out.get("hint") or "").lower()
    assert "isTnd=1".lower() in hint or "0/1" in hint


def test_bind_session_istnd_slice_keeps_s2(q) -> None:
    out = q.agent_query(pattern="IsTnd=1")
    assert out["shape"] == "cover"
    assert int(out.get("matching_block_count") or 0) > 0
    s2 = (out.get("dim_coverage") or {}).get("S2TemplateNum") or []
    assert s2, out.get("dim_coverage")


def test_bind_session_around_attrindex(q) -> None:
    out = q.agent_query(
        file="op_host/arch35/flash_attention_score_grad_tiling_common_regbase.h",
        line=188,
    )
    assert out["shape"] == "around"
    blob = _blob(out)
    assert "KEEP_PROB" in blob
    assert "SPARSE_MODE" in blob
    assert "TND_SOFTMAX_IN" in blob
    assert _dump_size(out) < 24_000


def test_bind_session_around_tiling_cpp_is_compact(q) -> None:
    out = q.agent_query(
        file="op_host/flash_attention_score_grad_tiling.cpp",
        line=237,
    )
    assert out["shape"] == "around"
    assert _dump_size(out) < 24_000
    blob = _blob(out)
    assert "0" in blob
    seeds = out.get("seeds") or out.get("hits") or []
    assert seeds
