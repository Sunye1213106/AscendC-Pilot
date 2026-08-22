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
    from uo_init.paths import architecture_from_env
    arch = architecture_from_env()
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
        ke = dict(cm.meta.get("kernel_root_trace") or cm.meta.get("kernel_execution") or {})
        closure = dict(cm.meta.get("kernel_tiling_closure") or {})
        by_kind = {}
        for kind in (
            "INPUT", "OUTPUT", "TILING_KEY", "TILING_DATA", "TILING_FIELD",
            "KERNEL", "FUNCTION", "METHOD", "OPERATION", "BUFFER",
            "REGISTER", "TYPE", "BRANCH", "TEMPLATE",
        ):
            by_kind[kind] = len(cm.by_kind(kind))
        wraps = sum(1 for r in cm.relations.values() if r.kind_name() == "WRAPS")
        rooted = sum(1 for r in cm.relations.values() if r.kind_name() == "ROOTED_AT")
        # Wrapper recognition: MutexBuffer is a storage_wrapper_type → AscendC::LocalTensor,
        # not a BUFFER kind. Decl sites carry role=storage_wrapper + file:line.
        mutex_types = [
            t.to_dict()
            for t in cm.by_kind("TYPE")
            if t.name == "MutexBuffer" and t.attrs.get("role") == "storage_wrapper_type"
        ]
        mutex_sites = [
            b.to_dict()
            for b in cm.by_kind("BUFFER")
            if b.attrs.get("wrapper") == "MutexBuffer"
            or (
                b.attrs.get("role") == "storage_wrapper"
                and "MutexBuffer" in str(b.attrs.get("trace") or [])
            )
        ]
        mutex_sync = [
            o.to_dict()
            for o in cm.by_kind("OPERATION")
            if o.file and "mutex_buffer" in str(o.file).replace("\\", "/")
            and o.attrs.get("root_status") == "REACHED"
        ]
        completeness = {
            "uo_path": str(product),
            "entity_count": len(cm.entities),
            "relation_count": len(cm.relations),
            "by_kind": by_kind,
            "audit_summary": summary,
            "kernel_root_trace": {
                "operations": ke.get("operations"),
                "buffers": ke.get("buffers"),
                "registers": ke.get("registers"),
                "reached_buffers": ke.get("reached_buffers"),
                "reached_operations": ke.get("reached_operations"),
                "gap_count": ke.get("gap_count"),
                "gap_counts": ke.get("gap_counts"),
                "elapsed_s": ke.get("elapsed_s"),
            },
            "wraps_relations": wraps,
            "rooted_at_relations": rooted,
            "mutex_wrapper_type_reached": sum(
                1 for t in mutex_types if t.get("root_status") == "REACHED" and "LocalTensor" in str(t.get("root") or "")
            ),
            "mutex_wrapper_type_samples": [
                {
                    "name": t.get("name"),
                    "role": t.get("role"),
                    "root": t.get("root"),
                    "root_status": t.get("root_status"),
                    "file": t.get("file"),
                    "line": t.get("line_start"),
                    "trace": t.get("trace"),
                }
                for t in mutex_types[:4]
            ],
            "mutex_decl_sites": len(mutex_sites),
            "mutex_decl_reached": sum(1 for b in mutex_sites if b.get("root_status") == "REACHED"),
            "mutex_decl_samples": [
                {
                    "name": b.get("name"),
                    "wrapper": b.get("wrapper"),
                    "root": b.get("root"),
                    "root_status": b.get("root_status"),
                    "file": b.get("file"),
                    "line": b.get("line_start"),
                    "trace": b.get("trace"),
                }
                for b in mutex_sites[:8]
            ],
            "mutex_sync_ops_reached": len(mutex_sync),
            "mutex_sync_samples": [
                {
                    "name": o.get("name"),
                    "root": o.get("root"),
                    "file": o.get("file"),
                    "line": o.get("line_start"),
                }
                for o in mutex_sync[:8]
            ],
            "kernel_tiling_closure": {
                k: closure.get(k)
                for k in (
                    "kernel_reachable_scopes",
                    "selected_kernel_files",
                    "tiling_entry_reachable_fields",
                    "tiling_entry_reachable_read_sites",
                )
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
        "kernel_max_variants": os.environ.get("UO_KERNEL_MAX_VARIANTS") or "1",
        "with_kernel": os.environ.get("UO_WITH_KERNEL") or "1",
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
