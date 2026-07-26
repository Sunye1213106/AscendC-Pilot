"""Pytest hooks for understand-operator tests."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "fag_e2e: fixture-level FAG acceptance hooks (no full acp session)",
    )
