# -*- coding: utf-8 -*-
"""Turn an ImpactReport into regression cases from the reachable corpus."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from code_engineering.impact import ImpactReport


def regress_cases(
    impact: ImpactReport,
    *,
    reachable_csv: str | Path | None = None,
    project_root: str | Path | None = None,
    limit: int = 64,
) -> dict[str, Any]:
    """Pick existing witnesses that exercise the impacted dimensions.

    Falls back to the closure reachable_cases deliverable when present.
    """
    root = Path(project_root or ".")
    candidates = []
    if reachable_csv:
        candidates.append(Path(reachable_csv))
    candidates.extend([
        root / "docs" / "fag" / "data" / "fag_arch35_reachable_cases.csv",
        root / ".ascendc-pilot" / "tg" / "closure" / "reachable_cases.csv",
    ])
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {
            "ok": False,
            "error": "no reachable_cases.csv found",
            "cases": [],
            "fields": impact.fields,
        }

    dims = impact.key_dims or impact.fields
    selected = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if len(selected) >= limit:
                break
            # Prefer rows whose dim_* columns mention a hit field value change;
            # otherwise take any row as a baseline when dims are host_state only.
            keep = not dims
            for d in dims:
                col = f"dim_{d}" if not d.startswith("dim_") else d
                # Also try camelCase host field → PascalCase dim.
                alt = "dim_" + (d[0].upper() + d[1:] if d else d)
                if row.get(col) not in (None, "") or row.get(alt) not in (None, ""):
                    keep = True
                    break
            if keep:
                selected.append(dict(row))

    out_path = root / ".ascendc-pilot" / "ce" / "regress_cases.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if selected:
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(selected[0].keys()))
            w.writeheader()
            w.writerows(selected)

    return {
        "ok": True,
        "source": str(path),
        "path": str(out_path),
        "count": len(selected),
        "fields": impact.fields,
        "key_dims": impact.key_dims,
        "cases": selected[:10],
    }
