# -*- coding: utf-8 -*-
"""Baselines that describe a source snapshot rather than the analysis itself.

A recorded control-node count guards against the walker regressing, but it also
changes whenever the operator's source changes -- and those two causes need
different responses. Keying each number to the sha256 of the file it was
measured from separates them: a matching digest means a mismatch is a
regression and must fail; a differing digest means the source moved on and the
number is simply stale.

Stale is reported, never silently accepted, and `--uo-update-baselines`
rewrites the record.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

BASELINE_DIR = Path(__file__).resolve().parent / "baselines"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(op_name: str) -> Path:
    return BASELINE_DIR / f"{op_name}.yaml"


def load(op_name: str) -> dict[str, Any]:
    path = _file(op_name)
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def save(op_name: str, data: dict[str, Any]) -> None:
    path = _file(op_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )


def check(
    op_name: str,
    section: str,
    measured: dict[str, tuple[Path, Any]],
    *,
    update: bool,
) -> None:
    """Compare measurements against the record, one entry per source file.

    `measured` maps an entry name to the source file it came from and the value
    measured. Entries whose source digest still matches are asserted; entries
    whose source changed are collected and reported at the end.
    """
    data = load(op_name)
    recorded = dict(data.get(section) or {})

    regressions: list[str] = []
    stale: list[str] = []
    added: list[str] = []

    for name, (source, value) in sorted(measured.items()):
        sha = digest(source)
        entry = recorded.get(name)
        if entry is None:
            added.append(f"{name}: {value} (no baseline recorded)")
        elif entry.get("sha256") != sha:
            stale.append(
                f"{name}: recorded {entry.get('value')} for a different revision, "
                f"measured {value}"
            )
        elif entry.get("value") != value:
            regressions.append(f"{name}: recorded {entry.get('value')}, measured {value}")
        recorded[name] = {"sha256": sha, "value": value}

    gone = sorted(set(recorded) - set(measured))

    if update:
        data[section] = recorded
        save(op_name, data)
        return

    if regressions:
        pytest.fail(
            f"{section}: the source is unchanged but the analysis is not:\n  "
            + "\n  ".join(regressions)
        )
    if stale or added or gone:
        detail = stale + added + [f"{name}: source no longer present" for name in gone]
        pytest.skip(
            f"{section}: baseline does not describe this source revision:\n  "
            + "\n  ".join(detail)
            + "\n  re-run with --uo-update-baselines to record the current values"
        )
