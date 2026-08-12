# -*- coding: utf-8 -*-
"""CodeMap freshness policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from code_engineering.product_uo import meta


def check_freshness(
    project_root: Path | str,
    expected_fingerprint: str,
    *,
    architecture: str = "",
) -> dict[str, Any]:
    """Choose canonical diff, lexical fallback, or stale fail-closed mode."""
    values = meta(project_root, architecture=architecture)
    actual = str(values.get("cm_graph_fingerprint") or values.get("graph_fingerprint") or "")
    expected = str(expected_fingerprint or "")
    if actual and expected and actual == expected:
        mode, reason = "codemap_diff", "fingerprint_match"
    elif not actual:
        mode, reason = "lexical", "codemap_fingerprint_missing"
    else:
        mode, reason = "stale", "fingerprint_mismatch" if expected else "expected_fingerprint_missing"
    return {
        "mode": mode,
        "fresh": mode == "codemap_diff",
        "expected": expected,
        "actual": actual,
        "reason": reason,
    }


freshness = check_freshness
