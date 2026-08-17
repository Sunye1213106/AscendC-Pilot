# -*- coding: utf-8 -*-
"""FAG arch35 agent-facing query shapes: name card, cover, around, index."""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.store.reader import find_uo_product
from uo_init.uo_query import open_query


def _resolve_fag() -> tuple[Path | None, Path | None]:
    for root in (
        Path(r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad"),
        Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
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


def _card(payload: dict, *, kind: str = "") -> dict:
    cards = list(payload.get("cards") or [])
    assert cards, payload
    if not kind:
        return cards[0]
    hit = next((row for row in cards if str(row.get("kind") or "") == kind), None)
    assert hit is not None, [row.get("kind") for row in cards]
    return hit


def test_s1inner_card_has_field_reads_writes(q) -> None:
    out = q.agent_query(pattern="s1Inner")
    assert out["shape"] == "name"
    card = _card(out, kind="TILING_FIELD")
    extras = card.get("extras") or {}
    writers = extras.get("writers") or []
    edges = card.get("edges") or {}
    assert writers or "WRITES" in edges
    assert "readers" in extras
    assert card.get("file") and int(card.get("line") or 0) > 0


def test_is_small_d_preload_card_has_definition_and_edges(q) -> None:
    out = q.agent_query(pattern="IS_SMALL_D_PRELOAD")
    assert out["shape"] == "name"
    card = _card(out)
    kinds = {str(row.get("kind") or "") for row in out.get("cards") or []}
    assert "COMPILE_VAR" in kinds or "MACRO" in kinds
    assert card.get("file") and (card.get("snippet") or (card.get("extras") or {}).get("definition"))
    assert card.get("edges") or out.get("next")


def test_setschedulemode_card_has_calls_or_rooted_at(q) -> None:
    out = q.agent_query(pattern="SetScheduleMode")
    assert out["shape"] == "name"
    kinds = set()
    for card in out.get("cards") or []:
        kinds.update((card.get("edges") or {}).keys())
    assert "CALLS" in kinds or "ROOTED_AT" in kinds


def test_index_phases_are_arch35(q) -> None:
    out = q.agent_query()
    assert out["shape"] == "index"
    phases = [row for row in (out.get("phases") or []) if row.get("pipe") or row.get("file")]
    assert phases
    files = " ".join(str(row.get("file") or "") for row in phases)
    entry = out.get("entry") if isinstance(out.get("entry"), dict) else {}
    files += " " + str(entry.get("file") or "")
    assert "arch35" in files.replace("\\", "/")


def test_cover_splitaxis_has_dim_coverage(q) -> None:
    out = q.agent_query(pattern="SplitAxis=1,IsTnd=1")
    assert out["shape"] == "cover"
    coverage = out.get("dim_coverage") or {}
    assert coverage
    assert "1" in [str(v) for v in (coverage.get("SplitAxis") or [])] or int(
        out.get("matching_block_count") or 0
    ) >= 1


def test_cover_empty_does_not_dump_sel(q) -> None:

    out = q.agent_query(pattern="DTemplateNum=1")
    assert out["shape"] == "cover"
    assert int(out.get("matching_block_count") or 0) == 0
    assert out.get("template_blocks") == []
    assert not (out.get("keys") or out.get("legal_keys"))
    assert "dim_coverage" in out


def test_around_walks_from_card_span(q) -> None:
    card_payload = q.agent_query(pattern="s1Inner")
    card = _card(card_payload, kind="TILING_FIELD")
    path = str(card.get("file") or "")
    line = int(card.get("line") or 0)
    assert path and line > 0
    around = q.agent_query(file=path, line=line)
    assert around["shape"] == "around"
    assert around.get("ok") is True
