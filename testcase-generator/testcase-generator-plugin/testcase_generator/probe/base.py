from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TilingProbe(ABC):
    @abstractmethod
    def run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        ...


class MockTilingProbe(TilingProbe):
    """Uses expected_key to simulate observed_key. verified=false."""

    def __init__(self, key_space: dict[str, Any] | None = None):
        self.key_space = key_space or {}

    def run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        from testcase_generator.engine.decode import encode_tiling_key

        expected = case.get("expected_key", {})
        tiling_key = case.get("expected_tiling_key")
        if tiling_key is None and expected:
            tiling_key = encode_tiling_key(expected, self.key_space)
        decoded = dict(expected)
        return {
            "case_id": case.get("case_id"),
            "status": "success",
            "tiling_key": tiling_key or 0,
            "decoded_key": decoded,
            "family_guess": case.get("family_id") or expected.get("family_id"),
            "mock_probe": True,
            "coverage_verified": False,
        }


class ExternalTilingProbe(TilingProbe):
    """Placeholder for real host tiling dry-run / C++ stub interface."""

    def __init__(self, endpoint: str | None = None):
        self.endpoint = endpoint

    def run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "ExternalTilingProbe is not implemented in MVP. "
            "Use --mock or wire UO_TILING_PROBE host dry-run."
        )
