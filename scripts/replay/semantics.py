# -*- coding: utf-8 -*-
"""What an operator has to say about its inputs.

The engine expands a case, audits it, and searches over it without knowing
what a query tensor is. Everything that *does* know -- layouts, optional
shapes, prefix sums -- lives behind this protocol, in the operator package.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class InputSemantics(Protocol):
    """Operator-owned answers to questions the engine asks about a case."""

    @property
    def in_order(self) -> Sequence[str]:
        """Input tensor names in the order the host's line expects."""
        ...

    @property
    def out_order(self) -> Sequence[str]:
        """Output tensor names in host order."""
        ...

    def shapes(self, case: Any
               ) -> tuple[Mapping[str, Sequence[int]], Mapping[str, Sequence[int]]]:
        """Input and output extents, derived from the case's knobs."""
        ...

    def dtype_of(self, case: Any, name: str, main: int) -> int:
        """Dtype the host is handed for one input."""
        ...

    def normalize(self, case: Any) -> Any:
        """Make the case self-consistent so the host will not refuse it."""
        ...

    def describe(self, case: Any) -> Mapping[str, Any]:
        """Flat record for the wide report table."""
        ...

    def enums(self) -> Mapping[str, Sequence[Any]]:
        """Closed sets the contract gate checks against."""
        ...
