# -*- coding: utf-8 -*-
"""Explore-specific compatibility facade layered over the stable CodeMap API."""

from __future__ import annotations

from typing import Any

from uo_init.query.compat import CodeMapUoQuery
from uo_init.query.legal_key_cache import _pattern_filters


class ExploreCodeMapUoQuery(CodeMapUoQuery):
    """Claim-sized aggregate modes exposed by ``acp uo-query``.

    The public CLI already has ``--pattern``.  Treat a simple comma-separated
    ``Dim=Value`` expression as structured template filters, preserving ordinary
    free-text patterns for navigation.  This avoids adding another command
    dialect while still letting the Agent query fixed_fields/field_domains in a
    single hop.
    """

    def aggregate_template_match(
        self,
        pattern: str = "",
        *,
        filters: dict[str, str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        structured = dict(filters or {})
        if not structured:
            structured.update(_pattern_filters(pattern))
        graph_pattern = "" if structured else pattern
        return super().aggregate_template_match(
            graph_pattern,
            filters=structured,
            limit=limit,
        )
