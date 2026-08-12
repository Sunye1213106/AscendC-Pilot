# -*- coding: utf-8 -*-
"""Load explicitly declared external evidence receipts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_external_evidence(declared_path: Path | str) -> list[dict[str, Any]]:
    """Accept only ``ce-external-evidence/v1`` receipts from a declared path."""
    path = Path(declared_path).expanduser().resolve()
    files = (
        sorted(p for p in path.iterdir() if p.suffix.lower() in {".json", ".yaml", ".yml"})
        if path.is_dir()
        else [path]
    )
    receipts: list[dict[str, Any]] = []
    for source in files:
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        doc = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
        values = doc if isinstance(doc, list) else [doc]
        for value in values:
            if not isinstance(value, dict) or value.get("schema") != "ce-external-evidence/v1":
                raise ValueError(f"invalid external evidence receipt: {source}")
            receipt = dict(value)
            receipt["declared_path"] = str(source)
            receipts.append(receipt)
    return receipts
