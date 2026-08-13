# -*- coding: utf-8 -*-
"""CodeMap freshness policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from code_engineering.product_uo import meta


def _scope_root(project_root: Path | str, architecture: str) -> Path:
    root = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    return root / architecture if architecture else root


def _load_capture(project_root: Path | str, architecture: str) -> dict[str, Any]:
    path = _scope_root(project_root, architecture) / "ce" / "impact" / "change_capture.yaml"
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def check_freshness(
    project_root: Path | str,
    expected_fingerprint: str,
    *,
    architecture: str = "",
) -> dict[str, Any]:
    """Choose canonical diff, lexical fallback, or stale fail-closed mode.

    A CE change capture is authoritative when present. In that mode we compare
    the UO product's source revision with the captured Git base/head instead of
    accepting a graph fingerprint copied from the same UO product.
    """
    values = meta(project_root, architecture=architecture)
    actual = str(values.get("cm_graph_fingerprint") or values.get("graph_fingerprint") or "")
    expected = str(expected_fingerprint or "")
    revision = str(
        values.get("source_revision")
        or values.get("revision")
        or values.get("git_revision")
        or ""
    ).strip()

    capture = _load_capture(project_root, architecture)
    base_sha = str(capture.get("base_sha") or "").strip()
    head_sha = str(capture.get("head_sha") or "").strip()
    diff_present = bool(str(capture.get("diff") or ""))

    if capture:
        if not revision:
            mode, reason = "stale", "uo_source_revision_missing"
        elif head_sha and revision == head_sha:
            if base_sha == head_sha and diff_present:
                mode, reason = "lexical", "working_tree_change_after_uo"
            else:
                mode, reason = "codemap_diff", "source_revision_matches_head"
        elif base_sha and revision == base_sha:
            mode, reason = "lexical", "source_revision_matches_base_only"
        else:
            mode, reason = "stale", "source_revision_mismatch"
    elif actual and expected and actual == expected:
        mode, reason = "codemap_diff", "fingerprint_match_without_capture"
    elif not actual:
        mode, reason = "lexical", "codemap_fingerprint_missing"
    else:
        mode, reason = (
            "stale",
            "fingerprint_mismatch" if expected else "expected_fingerprint_missing",
        )

    return {
        "mode": mode,
        "fresh": mode == "codemap_diff",
        "expected": expected,
        "actual": actual,
        "product_revision": revision,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "reason": reason,
    }


freshness = check_freshness
