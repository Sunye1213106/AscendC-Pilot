# -*- coding: utf-8 -*-
"""Rebuild FAG arch35 CodeMap and check job-map facts (check_sites / rhs / tposition)."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OP = Path(r"D:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")
ARCH = "arch35"
OUT = REPO / "artifacts" / "fag-arch35-rebuild"

sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]


def _brief(out: dict) -> dict:
    keys = (
        "ok",
        "engine",
        "error",
        "failed_step",
        "summary",
        "blocking",
        "uo_product",
        "gap_count",
        "semantic_completeness",
        "verdict",
        "run_id",
        "phase",
    )
    return {k: out.get(k) for k in keys if k in out}


def rebuild() -> dict:
    from ascendc_pilot.run_resume import apply_resume_decision
    from uo_init.codemap_engines import analyze, commit, extract, prepare, verify

    started = apply_resume_decision(
        OP,
        "uo-init",
        "reinit",
        require_receipt=False,
        start_kwargs={
            "op_name": "flash_attention_score_grad",
            "architecture": ARCH,
        },
    )
    run_id = str(started.get("run_id") or "")
    results: dict = {"start": _brief(started), "run_id": run_id}
    if not started.get("ok") or not run_id:
        results["ok"] = False
        results["error"] = "reinit_failed"
        return results

    ctx = {
        "op_name": "flash_attention_score_grad",
        "architecture": ARCH,
        "arch_dir": ARCH,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "confirm",
        "run_id": run_id,
    }
    if "--with-api" in sys.argv:
        ctx["with_api"] = True
    for name, fn in (
        ("prepare", prepare),
        ("extract", extract),
        ("analyze", analyze),
        ("commit", commit),
        ("verify", verify),
    ):
        t0 = time.perf_counter()
        print(f"\n----- {name} -----", flush=True)
        try:
            out = fn(OP, ctx)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            out = {"ok": False, "engine": name, "error": str(exc)[:800]}
        out["_elapsed_s"] = round(time.perf_counter() - t0, 3)
        results[name] = {**_brief(out), "elapsed_s": out["_elapsed_s"]}
        for key in ("op_name", "architecture", "arch_dir", "run_id"):
            if out.get(key):
                ctx[key] = out[key]
        print(json.dumps(results[name], ensure_ascii=False, default=str)[:3000], flush=True)
        if not out.get("ok"):
            results["ok"] = False
            results["failed_step"] = name
            return results
    results["ok"] = True
    return results


def check_job_facts() -> dict:
    from uo_init.ir.entity import EntityKind
    from uo_init.query.evidence import project_entity
    from uo_init.store.reader import read_codemap
    from uo_init.uo_query import open_query

    product = OP / ".ascendc-pilot" / ARCH / "uo" / "FlashAttentionScoreGrad.arch35.uo"
    if not product.is_file():
        product = OP / ".ascendc-pilot" / ARCH / "uo" / "flash_attention_score_grad.arch35.uo"
    cm = read_codemap(product)
    keys = list(cm.by_kind(EntityKind.TILING_KEY))
    fields = list(cm.by_kind(EntityKind.TILING_FIELD))
    bufs = list(cm.by_kind(EntityKind.BUFFER))
    queues = list(cm.by_kind(EntityKind.QUEUE))
    branches = list(cm.by_kind(EntityKind.BRANCH))
    ops = list(cm.by_kind(EntityKind.OPERATION))
    kernels = list(cm.by_kind(EntityKind.KERNEL))
    inputs = list(cm.by_kind(EntityKind.INPUT))

    host_checks = [
        e for e in branches if str(e.attrs.get("branch_kind") or "") == "host_check" and e.file and e.line_start > 0
    ]
    spanned_branches = [e for e in branches if e.file and e.line_start > 0]
    field_rhs = 0
    field_checks = 0
    for field in fields:
        hit = project_entity(field, require_span_for_branch=False) or {}
        facts = hit.get("facts") or {}
        if facts.get("rhs"):
            field_rhs += 1
        if facts.get("check_sites"):
            field_checks += 1
    tpos = [
        e
        for e in (*bufs, *queues)
        if str(e.attrs.get("tposition") or "") in {"VECIN", "VECOUT", "VECCALC", "A1", "B1", "GM"}
    ]
    dummy_kernels = [
        e
        for e in kernels
        if not e.file and not e.attrs.get("source_signature") and not e.attrs.get("variants")
    ]
    callees = {str(e.attrs.get("callee") or e.name) for e in ops}
    input_dtype = [
        e
        for e in inputs
        if e.attrs.get("dtype") or str(e.attrs.get("declaration") or "")
    ]
    foreign = [
        e.file
        for e in cm.entities.values()
        if any(tok in str(e.file or "").replace("\\", "/").lower() for tok in ("/arch22/", "/arch32/", "/arch40/"))
    ]

    q = open_query(product)
    locate_s1 = q.aggregate_locate("s1Inner") if hasattr(q, "aggregate_locate") else {"count": 0}
    api = q.aggregate_kernel_api("DataCopy") if hasattr(q, "aggregate_kernel_api") else {"count": 0}

    expected = {
        "tiling_key_count_ge_19": len(keys) >= 19,
        "host_check_sites": len(host_checks) >= 1,
        "spanned_branches": len(spanned_branches) >= 1,
        "field_rhs": field_rhs >= 1,
        "field_check_sites": field_checks >= 1,
        "buffer_or_queue_tposition": len(tpos) >= 1,
        "no_dummy_kernel": not dummy_kernels,
        "kernel_api_datacopy": "DataCopy" in callees or int(api.get("count") or 0) >= 1,
        "kernel_api_sync": bool(callees & {"SetFlag", "WaitFlag", "CrossCoreSetFlag", "CrossCoreWaitFlag"}),
        "input_dtype_declared": len(input_dtype) >= 1,
        "no_foreign_arch": not foreign,
        "locate_s1Inner": int(locate_s1.get("count") or 0) >= 1,
    }
    return {
        "ok": all(expected.values()),
        "product": str(product),
        "counts": {
            "tiling_keys": len(keys),
            "tiling_fields": len(fields),
            "buffers": len(bufs),
            "queues": len(queues),
            "host_checks": len(host_checks),
            "spanned_branches": len(spanned_branches),
            "field_rhs": field_rhs,
            "field_check_sites": field_checks,
            "tposition": len(tpos),
            "operations": len(ops),
            "kernels": len(kernels),
            "inputs_with_dtype": len(input_dtype),
        },
        "expected": expected,
        "failures": [k for k, v in expected.items() if not v],
        "sample_tposition": sorted({str(e.attrs.get("tposition")) for e in tpos})[:8],
        "sample_check": [
            {"file": e.file, "line": e.line_start, "name": e.name[:80]} for e in host_checks[:5]
        ],
        "kernel_tiling_closure": dict(cm.meta.get("kernel_tiling_closure") or {}),
        "foreign_arch_sample": foreign[:10],
        "dummy_kernels": [e.id for e in dummy_kernels[:10]],
    }


def analyze_commit_verify() -> dict:
    from uo_init.codemap_engines import analyze, commit, verify

    ctx = {
        "op_name": "flash_attention_score_grad",
        "architecture": ARCH,
        "arch_dir": ARCH,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "confirm",
    }
    results: dict = {}
    for name, fn in (("analyze", analyze), ("commit", commit), ("verify", verify)):
        t0 = time.perf_counter()
        print(f"\n----- {name} -----", flush=True)
        try:
            out = fn(OP, ctx)
        except Exception as exc:
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            results["ok"] = False
            return results
        brief = _brief(out if isinstance(out, dict) else {"ok": True, "raw": str(out)[:400]})
        brief["elapsed_s"] = round(time.perf_counter() - t0, 3)
        results[name] = brief
        if isinstance(out, dict) and not out.get("ok", True):
            results["ok"] = False
            results["failed_step"] = name
            return results
    results["ok"] = True
    return results


def main() -> int:
    global OUT
    args = set(sys.argv[1:])
    if "--with-api" in args:
        OUT = REPO / "artifacts" / "fag-arch35-rebuild" / "with-api"
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    if "--check-only" in args:
        rebuild_doc = {"ok": True, "skipped": "check-only"}
    elif "--analyze-only" in args:
        rebuild_doc = analyze_commit_verify()
        rebuild_doc["elapsed_s"] = round(time.perf_counter() - t0, 3)
        (OUT / "rebuild-analyze.json").write_text(
            json.dumps(rebuild_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    else:
        rebuild_doc = rebuild()
        rebuild_doc["elapsed_s"] = round(time.perf_counter() - t0, 3)
        (OUT / "rebuild.json").write_text(
            json.dumps(rebuild_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    if not rebuild_doc.get("ok"):
        print("REBUILD_FAILED", flush=True)
        return 1
    facts = check_job_facts()
    (OUT / "job-facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(facts, ensure_ascii=False, indent=2, default=str)[:4000], flush=True)
    print("ALL_DONE ok=" + str(facts.get("ok")), flush=True)
    return 0 if facts.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
