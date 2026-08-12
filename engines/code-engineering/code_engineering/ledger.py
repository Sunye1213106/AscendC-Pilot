# -*- coding: utf-8 -*-
"""Persistent O/V/X/Open obligation ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


def compute_open(
    obligations: Iterable[str], verified: Iterable[str], excepted: Iterable[str]
) -> set[str]:
    """Compute unresolved obligations."""
    return set(obligations) - set(verified) - set(excepted)


@dataclass
class Ledger:
    """Four-set obligation ledger."""

    O: set[str] = field(default_factory=set)
    V: set[str] = field(default_factory=set)
    X: set[str] = field(default_factory=set)

    @property
    def Open(self) -> set[str]:  # noqa: N802 - schema field name
        return compute_open(self.O, self.V, self.X)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ce-impact-ledger/v1",
            "O": sorted(self.O),
            "V": sorted(self.V),
            "X": sorted(self.X),
            "Open": sorted(self.Open),
        }


def ledger_path(
    project_root: Path | str, *, architecture: str = "", name: str = "ledger.yaml"
) -> Path:
    """Return the arch-scoped CE impact ledger path."""
    pilot = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    return (pilot / architecture if architecture else pilot) / "ce" / "impact" / name


def load_ledger(
    project_root: Path | str, *, architecture: str = "", path: Path | str | None = None
) -> Ledger:
    """Load a ledger, treating a missing file as empty."""
    source = Path(path) if path is not None else ledger_path(project_root, architecture=architecture)
    if not source.is_file():
        return Ledger()
    doc = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"invalid ledger mapping: {source}")
    return Ledger(
        O={str(v) for v in doc.get("O", [])},
        V={str(v) for v in doc.get("V", [])},
        X={str(v) for v in doc.get("X", [])},
    )


def save_ledger(
    ledger: Ledger,
    project_root: Path | str,
    *,
    architecture: str = "",
    path: Path | str | None = None,
) -> Path:
    """Save a normalized YAML ledger."""
    target = Path(path) if path is not None else ledger_path(project_root, architecture=architecture)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(ledger.to_dict(), sort_keys=False), encoding="utf-8")
    return target
