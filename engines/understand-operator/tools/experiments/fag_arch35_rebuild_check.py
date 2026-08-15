# -*- coding: utf-8 -*-
"""Rebuild FAG arch35 CodeMap and check job-map facts (check_sites / rhs / tposition)."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
_OP_CANDIDATES = (
    Path(r"D:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad"),
    Path(r"D:\TEST\ops-transformer\attention\flash_attention_score_grad"),
)
OP = next((p for p in _OP_CANDIDATES if p.is_dir()), _OP_CANDIDATES[0])
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
    from uo_init.diagnostics.product_check import check_cannbot_product
    from uo_init.ir.entity import EntityKind
    from uo_init.query.evidence import project_entity
    from uo_init.store.reader import find_uo_product, read_codemap
    from uo_init.uo_query import open_query

    product = find_uo_product(OP, op_name="flash_attention_score_grad", architecture=ARCH)
    if product is None:
        product = OP / ".ascendc-pilot" / ARCH / "uo" / "FlashAttentionScoreGrad.arch35.uo"
    if not Path(product).is_file():
        product = OP / ".ascendc-pilot" / ARCH / "uo" / "flash_attention_score_grad.arch35.uo"
    cm = read_codemap(product)
    generic = check_cannbot_product(cm, source_root=OP, architecture=ARCH)
    keys = list(cm.by_kind(EntityKind.TILING_KEY))
    fields = list(cm.by_kind(EntityKind.TILING_FIELD))
    q = open_query(product)
    locate_s1 = q.aggregate_locate("s1Inner") if hasattr(q, "aggregate_locate") else {"count": 0}
    field_rhs = 0
    field_checks = 0
    for field in fields:
        hit = project_entity(field, require_span_for_branch=False) or {}
        facts = hit.get("facts") or {}
        if facts.get("rhs"):
            field_rhs += 1
        if facts.get("check_sites"):
            field_checks += 1
    control = {
        "tiling_key_count_ge_19": len(keys) >= 19,
        "locate_s1Inner": int(locate_s1.get("count") or 0) >= 1,
        "field_rhs": field_rhs >= 1,
        "field_check_sites": field_checks >= 1,
    }
    return {
        "ok": bool(generic.get("ok")),
        "product": str(product),
        "generic": generic,
        "control_sample": control,
        "control_failures": [k for k, v in control.items() if not v],
        "counts": generic.get("counts") or {},
        "expected": generic.get("expected") or {},
        "failures": generic.get("failures") or [],
        "kernel_tiling_closure": dict(cm.meta.get("kernel_tiling_closure") or {}),
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
