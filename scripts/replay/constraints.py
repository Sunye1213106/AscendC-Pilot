# -*- coding: utf-8 -*-
"""DEPRECATED: FAG-era hard-coded implications.

Production exclusion uses ``operators/<op>/<arch>/proof_rules.yaml`` via
``replay.rule_engine``. This module is kept only so historical imports fail
loudly instead of silently applying an unreviewed seed book.
"""

from __future__ import annotations

raise ImportError(
    "replay.constraints is removed; load proof_rules.yaml through rule_engine "
    "(package seed → referee promote → active_rules)"
)
