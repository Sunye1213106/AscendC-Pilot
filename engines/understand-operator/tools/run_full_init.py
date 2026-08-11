# -*- coding: utf-8 -*-
"""Run full deterministic uo-init pipeline and print timing + completeness."""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

# Ensure local package is importable when run from repo.
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uo_init import codemap_engines as ce
from uo_init.query.engine import CodeMapQuery
from uo_init.store.reader import find_uo_product, read_codemap


def main() -> int:
    op = Path(os.environ.get("UO_OP_DIR") or "").expanduser()
    if not op.is_dir():
        print("UO_OP_DIR missing")
        return 2
    arch = os.environ.get("UO_ARCH") or "arch35"
    run_id = os.environ.get("UO_RUN_ID") or f"full-init-{int(time.time())}"
    payload = {
        "arch_dir": arch,
        "architecture": arch,
        "run_id": run_id,
        "keep_other_runs": True,
    }
    phases = [
        ("prepare", ce.prepare),
        ("extract", ce.extract),
        ("analyze", ce.analyze),
        ("commit", ce.commit),
        ("verify", ce.verify),
    ]
    results = []
    t_all = time.perf_counter()
    for name, fn in phases:
        print(f"\n===== {name} start =====", flush=True)
        t0 = time.perf_counter()
        try:
            out = fn(op, payload)
        except Exception as exc:  # noqa: BLE001
            dt = time.perf_counter() - t0
            print(f"===== {name} CRASH {dt:.2f}s =====")
            traceback.print_exc()
            results.append({"phase": name, "ok": False, "elapsed_s": round(dt, 3), "error": str(exc)[:400]})
            break
        dt = time.perf_counter() - t0
        ok = bool(out.get("ok"))
        row = {
            "phase": name,
            "ok": ok,
            "elapsed_s": round(dt, 3),
            "error": out.get("error"),
            "failed_step": out.get("failed_step"),
            "gap_count": out.get("gap_count"),
            "semantic_completeness": out.get("semantic_completeness"),
            "path": out.get("path"),
            "summary": out.get("summary"),
            "verdict": out.get("verdict"),
        }
        # Carry op_name forward.
        if out.get("op_name"):
            payload["op_name"] = out["op_name"]
        if isinstance(out.get("uo_product"), dict) and out["uo_product"].get("path"):
            row["path"] = out["uo_product"]["path"]
        results.append(row)
        print(f"===== {name} done ok={ok} {dt:.2f}s =====", flush=True)
        if not ok:
            print(json.dumps(out, ensure_ascii=False, default=str)[:2000])
            break
    total = time.perf_counter() - t_all

    # Completeness inspection from committed .uo
    completeness: dict = {}
    product = find_uo_product(op, op_name=str(payload.get("op_name") or ""), architecture=arch)
    if product and product.is_file():
        cm = read_codemap(product)
        q = CodeMapQuery(codemap=cm, path=str(product))
        audit = q.audit()
        summary = dict(audit.get("summary") or {})
        ke = dict(cm.meta.get("kernel_execution") or {})
        pipe = dict(cm.meta.get("kernel_execution_pipeline") or {})
        closure = dict(cm.meta.get("kernel_tiling_closure") or {})
        by_kind = {}
        for kind in (
            "INPUT", "OUTPUT", "TILING_KEY", "TILING_DATA", "TILING_FIELD",
            "KERNEL", "FUNCTION", "METHOD", "OPERATION", "BUFFER", "BUFFER_VIEW",
            "SYNC_EVENT", "EXEC_REGION", "BRANCH", "TEMPLATE",
        ):
            by_kind[kind] = len(cm.by_kind(kind))
        completeness = {
            "uo_path": str(product),
            "entity_count": len(cm.entities),
            "relation_count": len(cm.relations),
            "by_kind": by_kind,
            "audit_summary": summary,
            "kernel_execution": ke,
            "kernel_pipeline": {
                "operation_count": pipe.get("operation_count"),
                "overlap_capable_count": pipe.get("overlap_capable_count"),
                "copy_in_hints": pipe.get("copy_in_hints"),
                "copy_out_hints": pipe.get("copy_out_hints"),
                "stages": sorted((pipe.get("stages") or {}).keys()) if isinstance(pipe.get("stages"), dict) else [],
            },
            "kernel_tiling_closure": {
                k: closure.get(k)
                for k in (
                    "kernel_reachable_scopes",
                    "selected_kernel_files",
                    "tiling_entry_reachable_fields",
                    "tiling_entry_reachable_read_sites",
                )
                if k in closure or True
            },
            "operator_api": {
                "tensor_inputs": len(q.operator_api().get("tensor_inputs") or []),
                "attributes": len(q.operator_api().get("attributes") or []),
                "outputs": len(q.operator_api().get("outputs") or []),
            },
            "tiling_keys": len(q.tiling_keys()),
            "legal_key_count": q.legal_key_count(),
        }

    report = {
        "op": str(op),
        "arch": arch,
        "run_id": run_id,
        "profile": os.environ.get("UO_INIT_PROFILE") or "fast(default)",
        "total_s": round(total, 3),
        "phases": results,
        "completeness": completeness,
    }
    out_path = op / ".ascendc-pilot" / arch / "uo" / "ir" / "full_init_timing_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n===== FULL INIT REPORT =====")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {out_path}")
    return 0 if all(r.get("ok") for r in results) and results else 1


if __name__ == "__main__":
    raise SystemExit(main())
