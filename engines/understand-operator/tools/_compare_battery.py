# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(r"d:\TEST\AscendC-Pilot")
BEFORE = REPO / "docs" / "test" / "results" / "uo-cannbot" / "query_battery.baseline.json"
AFTER = REPO / "docs" / "test" / "results" / "uo-cannbot" / "query_battery.after.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(rows, key):
    vals = sorted(float(r[key]) for r in rows)
    if not vals:
        return {"n": 0, "p50": 0, "p95": 0, "max": 0, "avg": 0}
    return {
        "n": len(vals),
        "p50": round(vals[len(vals) // 2], 1),
        "p95": round(vals[min(len(vals) - 1, int(len(vals) * 0.95))], 1),
        "max": round(max(vals), 1),
        "avg": round(sum(vals) / len(vals), 1),
    }


def morph_table(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["morph"]].append(r)
    out = {}
    for morph, group in sorted(by.items()):
        ms = pct(group, "ms")
        bys = pct(group, "bytes")
        out[morph] = {
            "n": len(group),
            "ok": sum(1 for r in group if r.get("ok")),
            "ms": ms,
            "bytes": bys,
        }
    return out


def catalog_false(rows):
    names = {"LocalTensor", "TQue", "HardEvent", "TPipe"}
    return [
        {
            "op": r["op"],
            "argv": r["argv"],
            "ok": r.get("ok"),
            "count": r.get("count"),
            "bytes": r.get("bytes"),
        }
        for r in rows
        if r.get("morph") == "identifier" and r.get("argv") in names
    ]


def main() -> None:
    b = load(BEFORE)
    a = load(AFTER)
    payload = {
        "before": b["summary"],
        "after": a["summary"],
        "morph_before": morph_table(b["rows"]),
        "morph_after": morph_table(a["rows"]),
        "catalog_before": catalog_false(b["rows"]),
        "catalog_after": catalog_false(a["rows"]),
        "ok_false_after": [
            {"op": r["op"], "morph": r["morph"], "argv": r["argv"], "hint": r.get("hint")}
            for r in a["rows"]
            if not r.get("ok")
        ],
        "largest_after": sorted(a["rows"], key=lambda r: r["bytes"], reverse=True)[:8],
        "slowest_after": sorted(a["rows"], key=lambda r: r["ms"], reverse=True)[:8],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
