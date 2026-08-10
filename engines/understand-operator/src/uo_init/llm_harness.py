# -*- coding: utf-8 -*-
"""Controlled LLM intervention harness (no free writes to fact graph)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["review", "arbitrate", "propose_check", "aside"]


@dataclass
class LlmOutput:
    mode: Mode
    task_id: str
    evidence: str  # file:line
    confidence: float
    payload: Any
    provenance: str = "llm"

    def validate(self) -> None:
        if self.provenance != "llm":
            raise ValueError("provenance must be llm")
        if not self.task_id:
            raise ValueError("task_id required")
        if not self.evidence or ":" not in self.evidence:
            raise ValueError("evidence file:line required")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence")


@dataclass
class Ledger:
    entries: list[LlmOutput] = field(default_factory=list)
    deterministic_facts: dict[str, Any] = field(default_factory=dict)

    def add_llm(self, out: LlmOutput) -> None:
        out.validate()
        self.entries.append(out)

    def strip_llm(self) -> "Ledger":
        return Ledger(entries=[], deterministic_facts=dict(self.deterministic_facts))

    def apply_override(self, key: str, value: Any) -> None:
        """Deterministic evidence always wins over LLM."""
        self.deterministic_facts[key] = value
        self.entries = [e for e in self.entries if getattr(e, "payload_key", None) != key]

    def closures(self, det: float, with_llm: float) -> dict[str, float]:
        return {"deterministic_closure": det, "with_llm_closure": with_llm}
