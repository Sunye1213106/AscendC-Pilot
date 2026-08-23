# -*- coding: utf-8 -*-
"""Deterministic TG v3 coverage: predicates, obligations, eval, signatures, ledger."""

from .compile import compile_obligations
from .eval import evaluate_obligation, flatten_observe
from .ledger import (
    LEDGER_SCHEMA,
    dump_worklog,
    ledger_closed,
    parse_worklog_fence,
    seed_ledger,
    upsert_obligation,
)
from .predicate import KNOWN_OPS, Truth, evaluate, is_predicate
from .signature import semantic_signature

__all__ = [
    "KNOWN_OPS",
    "LEDGER_SCHEMA",
    "Truth",
    "compile_obligations",
    "dump_worklog",
    "evaluate",
    "evaluate_obligation",
    "flatten_observe",
    "is_predicate",
    "ledger_closed",
    "parse_worklog_fence",
    "seed_ledger",
    "semantic_signature",
    "upsert_obligation",
]
