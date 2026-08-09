# -*- coding: utf-8 -*-
"""TG thin wrapper around UO source locator (opens ``indexes/kb_graph.sqlite``)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable


def _ensure_uo_on_path(hint: Path | None = None) -> None:
    candidates = []
    if hint is not None:
        # uo_root → …/engines/understand-operator/src
        candidates.extend(
            [
                hint.parents[3] / "engines" / "understand-operator" / "src"
                if len(hint.parents) >= 4
                else None,
                hint.parents[2] / "engines" / "understand-operator" / "src"
                if len(hint.parents) >= 3
                else None,
            ]
        )
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parents[2] / "understand-operator" / "src",
            here.parents[3] / "engines" / "understand-operator" / "src"
            if len(here.parents) >= 4
            else None,
        ]
    )
    for candidate in candidates:
        if candidate is None:
            continue
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def locate(
    query: str,
    *,
    uo_root: str | Path,
    kinds: Iterable[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Locate entity source spans in the UO KB database for TG consumers."""
    root = Path(uo_root).expanduser().resolve()
    _ensure_uo_on_path(root)
    from uo_init.source_locator import open_locator

    return [
        loc.to_dict()
        for loc in open_locator(root).locate(query, kinds=kinds, limit=limit)
    ]


def locate_dim(
    name: str, *, uo_root: str | Path, limit: int = 20
) -> list[dict[str, Any]]:
    root = Path(uo_root).expanduser().resolve()
    _ensure_uo_on_path(root)
    from uo_init.source_locator import open_locator

    return [loc.to_dict() for loc in open_locator(root).locate_dim(name, limit=limit)]


def locate_branch(
    branch_id: str, *, uo_root: str | Path, limit: int = 20
) -> list[dict[str, Any]]:
    root = Path(uo_root).expanduser().resolve()
    _ensure_uo_on_path(root)
    from uo_init.source_locator import open_locator

    return [
        loc.to_dict()
        for loc in open_locator(root).locate_branch(branch_id, limit=limit)
    ]


def locate_field(
    name: str, *, uo_root: str | Path, limit: int = 20
) -> list[dict[str, Any]]:
    root = Path(uo_root).expanduser().resolve()
    _ensure_uo_on_path(root)
    from uo_init.source_locator import open_locator

    return [loc.to_dict() for loc in open_locator(root).locate_field(name, limit=limit)]
