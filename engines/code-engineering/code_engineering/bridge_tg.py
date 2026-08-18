# -*- coding: utf-8 -*-
"""Bridge impacted tiling keys to TG closure witnesses."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

import yaml


def bridge_tg(
    project_root: Path | str,
    impacted_keys: Iterable[int] | dict[str, Any] | Any,
    *,
    architecture: str = "",
    limit: int = 256,
) -> dict[str, Any]:
    """Filter TG closure rows and write CE verification handoff artifacts."""
    root = Path(project_root).expanduser().resolve()
    pilot = root / ".ascendc-pilot"
    scoped = pilot / architecture if architecture else pilot
    source = scoped / "tg" / "cases.csv"
    if isinstance(impacted_keys, dict):
        keys = impacted_keys.get("affected_keys") or impacted_keys.get("affected_keys_sample") or []
        fields = impacted_keys.get("key_dims") or impacted_keys.get("fields") or []
    elif hasattr(impacted_keys, "affected_keys"):
        keys = getattr(impacted_keys, "affected_keys", [])
        fields = getattr(impacted_keys, "key_dims", []) or getattr(impacted_keys, "fields", [])
    else:
        keys, fields = impacted_keys, []
    wanted = {_normal_key(str(value)) for value in keys if str(value).strip() != ""}
    field_names = [str(name) for name in fields if str(name).strip()]
    selected: list[dict[str, str]] = []
    if source.is_file():
        with source.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                raw = row.get("tiling_key") or row.get("TilingKey") or row.get("key") or row.get("key_id")
                by_key = bool(wanted) and raw is not None and _normal_key(raw) in wanted
                by_field = bool(field_names) and any(
                    row.get(name) not in (None, "") or row.get(f"dim_{name}") not in (None, "")
                    for name in field_names
                )
                if by_key or by_field:
                    selected.append(dict(row))
                if len(selected) >= limit:
                    break
    verify = scoped / "ce" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    cases_path = verify / "regress_cases.csv"
    if selected:
        with cases_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(selected[0]))
            writer.writeheader()
            writer.writerows(selected)
    numeric_keys: list[int] = []
    for value in wanted:
        try:
            numeric_keys.append(int(value, 0) if isinstance(value, str) else int(value))
        except (TypeError, ValueError):
            continue
    handoff = {
        "schema": "ce-tg-handoff/v1",
        "architecture": architecture,
        "impacted_keys": sorted(numeric_keys),
        "fields": sorted(set(field_names)),
        "cases_source": str(source),
        "regress_cases": str(cases_path),
        "case_count": len(selected),
        "filter": "keys" if wanted else ("fields" if field_names else "none"),
    }
    handoff_path = verify / "tg_handoff.yaml"
    handoff_path.write_text(yaml.safe_dump(handoff, sort_keys=False), encoding="utf-8")
    return {**handoff, "path": str(handoff_path), "ok": source.is_file()}


def _normal_key(value: str) -> str:
    try:
        return str(int(value, 0))
    except ValueError:
        return value
