# -*- coding: utf-8 -*-
"""Unified operator adapter facade for TG / closure (v3 §553).

Concrete materialize logic may stay operator-specific; generation, mutation,
construction and replay all go through this protocol so a second operator
does not require editing engine modules.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class OperatorAdapter(Protocol):
    """Operator-facing surface used by closure / TG engines."""

    def declared_keys(self) -> frozenset[int]:
        ...

    def decode_key(self, key: int) -> Mapping[str, str]:
        ...

    def sample_case(self, rng: Any, grid: Mapping[str, Sequence[Any]] | None = None) -> Any:
        ...

    def mutate(self, case: Any, rng: Any, k: int = 2,
               grid: Mapping[str, Sequence[Any]] | None = None) -> Any:
        ...

    def construct(self, target: Mapping[str, str], *, seed: int = 0) -> Sequence[Any]:
        ...

    def describe(self, case: Any) -> Mapping[str, Any]:
        ...

    def replay(self, cases: Sequence[Any], *, tag: str = "") -> Sequence[Any]:
        ...

    def actual_key(self, result: Any) -> int:
        ...

    def generation_knobs(self, field_id: str, *, uo_root: str | None = None) -> Sequence[str]:
        ...

    def materialize(self, case: Any, case_id: str = "") -> Any:
        ...
