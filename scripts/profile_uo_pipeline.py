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


def _resolve_run_id(uo_root: Path) -> str:
    try:
        from uo.scripts._ir_io import read_yaml

        manifest = read_yaml(uo_root / "manifest.yaml") or {}
        rid = str(manifest.get("current_run_id") or manifest.get("current_run") or "").strip()
        if rid:
            return rid
    except Exception:  # noqa: BLE001
        pass
    return f"profile-{int(time.time())}"


def profile_uo(repo_root: Path, op_name: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    uo_root_pkg = root / "engines" / "understand-operator"
    if str(uo_root_pkg) not in sys.path:
        sys.path.insert(0, str(uo_root_pkg))

    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.build_layered_kb import build_layered_kb
    from uo.scripts.publish_kb_products import publish_kb_products
    from uo.scripts.semantic_resolution_ledger import rebuild_derived_graphs

    uo = existing_operator_root(repo_root, op_name)
    run_id = _resolve_run_id(uo)

    out: dict[str, object] = {"run_id": run_id, "errors": {}}
    t0 = time.perf_counter()
    try:
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
    except Exception as exc:  # noqa: BLE001
        out["extract_plan_finalize"] = _ms(t0)
        out["errors"]["extract_plan_finalize"] = f"{type(exc).__name__}: {exc}"[:300]

    t0 = time.perf_counter()
    try:
        rebuild_derived_graphs(repo_root, op_name, run_id=run_id, architecture="arch35")
        out["rebuild"] = _ms(t0)
    except Exception as exc:  # noqa: BLE001
        out["rebuild"] = _ms(t0)
        out["errors"]["rebuild"] = f"{type(exc).__name__}: {exc}"[:300]

    t0 = time.perf_counter()
    try:
        publish_kb_products(repo_root, op_name, write=True)
        out["export_integrity"] = _ms(t0)
    except Exception as exc:  # noqa: BLE001
        out["export_integrity"] = _ms(t0)
        out["errors"]["export_integrity"] = f"{type(exc).__name__}: {exc}"[:300]
    return out


def profile_tg_contract(repo_root: Path, op_name: str, consumer_root: Path | None = None) -> dict[str, object]:
    """Time TG contract build twice to surface consumer_index cache effect."""
    root = Path(__file__).resolve().parents[1]
    tg_root = root / "engines" / "testcase-generation"
    if str(tg_root) not in sys.path:
        sys.path.insert(0, str(tg_root))
    uo_pkg = root / "engines" / "understand-operator"
    if str(uo_pkg) not in sys.path:
        sys.path.insert(0, str(uo_pkg))

    try:
        from testcase_agent.contract import tg_contract
    except Exception as exc:  # noqa: BLE001
        return {"error": f"import_failed: {exc}"[:300]}

    csv_root = Path(consumer_root) if consumer_root else repo_root
    times: list[int] = []
    errors: list[str] = []
    for i in range(2):
        t0 = time.perf_counter()
        try:
            tg_contract(
                repo_root,
                op_name,
                csv_consumer_root=csv_root,
                reuse_snapshot=(i > 0),
            )
            times.append(_ms(t0))
        except Exception as exc:  # noqa: BLE001
            times.append(_ms(t0))
            errors.append(f"run{i+1}: {type(exc).__name__}: {exc}"[:200])

    return {
        "tg_contract_run1_ms": times[0] if times else None,
        "tg_contract_run2_ms": times[1] if len(times) > 1 else None,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--out", default="docs/performance/profile.json")
    parser.add_argument("--with-tg", action="store_true", help="Also profile TG contract twice")
    parser.add_argument("--consumer-root", default="", help="CSV/consumer root for --with-tg")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    payload: dict[str, object] = {"uo": profile_uo(repo, args.op_name)}
    if args.with_tg:
        consumer = Path(args.consumer_root).resolve() if args.consumer_root else None
        payload["tg"] = profile_tg_contract(repo, args.op_name, consumer_root=consumer)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
