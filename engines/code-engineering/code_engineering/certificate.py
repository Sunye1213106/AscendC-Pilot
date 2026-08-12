# -*- coding: utf-8 -*-
"""CE closure certificate generation."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from code_engineering.ledger import Ledger, compute_open


def certificate(
    obligations: Iterable[str], verified: Iterable[str], excepted: Iterable[str]
) -> dict:
    """Build a deterministic closure certificate."""
    o, v, x = set(obligations), set(verified), set(excepted)
    opened = compute_open(o, v, x)
    return {
        "schema": "ce-impact-certificate/v1",
        "O": sorted(o),
        "V": sorted(v),
        "X": sorted(x),
        "Open": sorted(opened),
        "closed": not opened,
    }


def write_certificate(
    project_root: Path | str,
    ledger: Ledger,
    *,
    architecture: str = "",
    path: Path | str | None = None,
) -> dict:
    """Write an arch-scoped YAML closure certificate."""
    doc = certificate(ledger.O, ledger.V, ledger.X)
    pilot = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    target = Path(path) if path is not None else (
        (pilot / architecture if architecture else pilot)
        / "ce" / "impact" / "certificate.yaml"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    doc["path"] = str(target)
    return doc
