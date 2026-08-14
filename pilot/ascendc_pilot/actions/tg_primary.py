"""Backward-compatible re-exports. Canonical module: ``ascendc_pilot.human_confirm``."""

from __future__ import annotations

from ascendc_pilot.human_confirm import (
    PRIMARY_TG_ACTIONS,
    materialize_primary_decision,
    primary_interactive_steps,
    rollback_primary_decision,
)

__all__ = [
    "PRIMARY_TG_ACTIONS",
    "materialize_primary_decision",
    "primary_interactive_steps",
    "rollback_primary_decision",
]
