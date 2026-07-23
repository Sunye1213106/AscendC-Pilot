"""Ensure uo_kb_query forwarder resolves to the canonical script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "uo" / "scripts" / "uo_kb_query.py"
FORWARDER = ROOT / "skills" / "uo-query" / "scripts" / "uo_kb_query.py"


def test_canonical_uo_kb_query_exists() -> None:
    assert CANONICAL.is_file(), f"missing canonical script: {CANONICAL}"


def test_forwarder_exists() -> None:
    assert FORWARDER.is_file(), f"missing forwarder stub: {FORWARDER}"


def test_forwarder_resolves_to_canonical() -> None:
    spec = importlib.util.spec_from_file_location(
        "uo_kb_query_forwarder", FORWARDER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    resolved = module._resolve_real_script()
    assert resolved.resolve() == CANONICAL.resolve(), (
        f"forwarder resolved to {resolved}, expected {CANONICAL}"
    )
