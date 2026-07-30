# -*- coding: utf-8 -*-
"""Stubs for removed old-engine extract_plan / semantic helpers."""
from __future__ import annotations

from typing import Any

FORBIDDEN_EXTRACT_PLAN_KEYS = frozenset(
    {
        "llm_tasks",
        "dispatch_tasks",
        "worker_batches",
        "candidates",
    }
)


class LegacyEngineRemoved(RuntimeError):
    """Raised when code still expects understand-operator-old APIs."""


def _gone(name: str) -> Any:
    raise LegacyEngineRemoved(
        f"{name} removed with understand-operator-old; use uo_init / new uo-update"
    )


def normalize_plan_from_candidates(*_a, **_k):
    return _gone("normalize_plan_from_candidates")


def validate_extract_plan_against_candidates(*_a, **_k):
    return _gone("validate_extract_plan_against_candidates")


def compute_semantic_stats(*_a, **_k):
    return {"open": 0, "done": 0, "engine": "stub"}


def open_blocking_tasks(*_a, **_k):
    return []


def validate_semantic_patch_set(*_a, **_k):
    return []


def can_auto_mark_missing(*_a, **_k):
    return False


def post_semantic_prerequisites(*_a, **_k):
    return {"ok": True}


def _source_snapshot_hash(*_a, **_k):
    return ""


def should_skip_layered_rebuild(*_a, **_k):
    return False


def input_derivable_closure(*_a, **_k):
    return True


def check_family_path_obligation(*_a, **_k):
    return {"ok": True, "gate": "family_path_obligation", "engine": "stub"}
