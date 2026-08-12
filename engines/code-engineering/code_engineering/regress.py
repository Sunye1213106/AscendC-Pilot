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

    Prefers TG's ``tg/closure/closure.csv`` under the arch-scoped pilot root.
    Falls back to legacy ``reachable_cases.csv`` when present.
    """
    root = Path(project_root or ".")
    candidates: list[Path] = []
    if reachable_csv:
        candidates.append(Path(reachable_csv))
    # Prefer runtime closure corpus; never fall back to checked-in FAG answers.
    arch_dirs = (
        sorted(p for p in (root / ".ascendc-pilot").glob("*") if p.is_dir())
        if (root / ".ascendc-pilot").is_dir()
        else []
    )
    # TG writes closure.csv; keep reachable_cases.csv for backward compatibility.
    for name in ("closure.csv", "reachable_cases.csv"):
        for arch_dir in arch_dirs:
            candidates.append(arch_dir / "tg" / "closure" / name)
        candidates.append(root / ".ascendc-pilot" / "tg" / "closure" / name)
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {
            "ok": False,
            "error": (
                "no closure.csv / reachable_cases.csv found "
                "(pass --reachable-csv or run TG closure first)"
            ),
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
