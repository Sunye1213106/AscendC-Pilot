#!/usr/bin/env python3
"""Profile UO/TG pipeline stages for docs/performance/*.md."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def profile_uo(repo_root: Path, op_name: str) -> dict[str, int]:
    root = Path(__file__).resolve().parents[1]
    uo_root = root / "engines" / "understand-operator"
    if str(uo_root) not in sys.path:
        sys.path.insert(0, str(uo_root))

    from uo.scripts.build_layered_kb import build_layered_kb
    from uo.scripts.publish_kb_products import publish_kb_products
    from uo.scripts.semantic_resolution_ledger import rebuild_derived_graphs

    out: dict[str, int] = {}
    t0 = time.perf_counter()
    layered = build_layered_kb(
        repo_root,
        op_name,
        layers={"entrypoints", "host", "kernel", "tilingkey", "bridge"},
        allow_empty_plan=True,
        mode="structural",
        parallel=True,
    )
    out["extract_plan_finalize"] = _ms(t0)
    stats = (layered or {}).get("stats") or {}
    timing = stats.get("timing_ms") or {}
    if isinstance(timing, dict):
        out.update({f"build_{k}": int(v) for k, v in timing.items() if isinstance(v, (int, float))})

    t0 = time.perf_counter()
    try:
        rebuild_derived_graphs(repo_root, op_name, run_id="profile-run", architecture="arch35")
    except Exception:
        out["rebuild"] = _ms(t0)
    else:
        out["rebuild"] = _ms(t0)

    t0 = time.perf_counter()
    publish_kb_products(repo_root, op_name, write=True)
    out["export_integrity"] = _ms(t0)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--out", default="docs/performance/profile.json")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    payload = {"uo": profile_uo(repo, args.op_name)}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
