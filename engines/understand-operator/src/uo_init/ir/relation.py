# -*- coding: utf-8 -*-
"""CodeMap relation ontology (unified edge kinds)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RelationKind(str, Enum):
    DECLARES = "DECLARES"
    DEFINES = "DEFINES"
    REFERENCES = "REFERENCES"

    CALLS = "CALLS"
    READS = "READS"
    WRITES = "WRITES"

    DERIVES = "DERIVES"
    FLOWS_TO = "FLOWS_TO"
    CONTROLS = "CONTROLS"

    EXPANDS_TO = "EXPANDS_TO"
    GUARDED_BY = "GUARDED_BY"

    BINDS = "BINDS"
    INSTANTIATES = "INSTANTIATES"
    SPECIALIZES = "SPECIALIZES"

    SELECTS = "SELECTS"
    LAUNCHES = "LAUNCHES"

    AVAILABLE_ON = "AVAILABLE_ON"
    ACTIVE_UNDER = "ACTIVE_UNDER"

    SAVES = "SAVES"
    RESTORES = "RESTORES"

    # Kernel execution graph (occurrence-level).
    CONTAINS = "CONTAINS"
    PRECEDES = "PRECEDES"
    READS_BUFFER = "READS_BUFFER"
    WRITES_BUFFER = "WRITES_BUFFER"
    VIEW_OF = "VIEW_OF"
    ALIASES = "ALIASES"
    ALLOCATES = "ALLOCATES"
    RELEASES = "RELEASES"
    SIGNALS = "SIGNALS"
    WAITS_ON = "WAITS_ON"
    SYNCHRONIZES_WITH = "SYNCHRONIZES_WITH"
    HAPPENS_BEFORE = "HAPPENS_BEFORE"
    EXECUTES_ON = "EXECUTES_ON"

    OTHER = "OTHER"


@dataclass
class Relation:
    """One directed edge in the unified CodeMap."""

    id: str
    kind: RelationKind | str
    src: str
    dst: str
    attrs: dict[str, Any] = field(default_factory=dict)
    status: str = "extracted"
    confidence: float = 1.0

    def kind_name(self) -> str:
        k = self.kind
        return k.value if isinstance(k, RelationKind) else str(k)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "kind": self.kind_name(),
            "src": self.src,
            "dst": self.dst,
            "status": self.status,
            "confidence": round(float(self.confidence), 4),
        }
        out.update(self.attrs)
        return out
