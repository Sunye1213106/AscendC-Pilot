# -*- coding: utf-8 -*-
"""True cold-start uo-init wall-clock for FAG arch35.

Wipes ``.ascendc-pilot/arch35`` (including TU cache), starts a fresh run, and
drives prepare → extract → analyze → commit → verify. No prior UO product.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OP = Path(r"D:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")
ARCH = "arch35"
OUT = REPO / "artifacts" / "fag-arch35-rebuild" / "cold-start-120s"

sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]


def _wipe_arch35() -> None:
    arch_dir = OP / ".ascendc-pilot" / ARCH
    if arch_dir.exists():
        shutil.rmtree(arch_dir)
        print(f"WIPED {arch_dir}", flush=True)
    else:
        print(f"NO_CACHE {arch_dir}", flush=True)


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
        "kernel_branches",
        "closure_mode",
        "closure_selected",
        "reused_analyze",
    )
    return {k: out.get(k) for k in keys if k in out}


def main() -> int:
    os.environ["UO_TIMING"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["UO_ARCH"] = ARCH
    os.environ.pop("UO_INIT_PROFILE", None)
    os.environ.pop("UO_CACHE_ROOT", None)
    os.environ.pop("UO_COLD_BUDGET_S", None)

    OUT.mkdir(parents=True, exist_ok=True)
    _wipe_arch35()

    from ascendc_pilot.state import start_workflow
    from uo_init.codemap_engines import analyze, commit, extract, prepare, verify

    t_all = time.perf_counter()
    started = start_workflow(
        OP,
        "uo-init",
        op_name="flash_attention_score_grad",
        architecture=ARCH,
        intent="cold-start timing FAG arch35",
    )
    run_id = str(started.get("run_id") or "")
    results: dict = {
        "start": _brief(started) if isinstance(started, dict) else {"raw": str(started)[:400]},
        "run_id": run_id,
        "profile": {
            "UO_INIT_PROFILE": os.environ.get("UO_INIT_PROFILE", ""),
            "UO_ARCH": os.environ.get("UO_ARCH", ""),
            "UO_TU_CACHE": os.environ.get("UO_TU_CACHE", "1(default)"),
            "cpu_count": os.cpu_count(),
        },
    }
    print(json.dumps({"start": results["start"]}, ensure_ascii=False, default=str), flush=True)
    if not started.get("ok") or not run_id:
        results["ok"] = False
        results["error"] = "start_failed"
        (OUT / "rebuild.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print("REBUILD_FAILED start", flush=True)
        return 1

    ctx = {
        "op_name": "flash_attention_score_grad",
        "architecture": ARCH,
        "arch_dir": ARCH,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "confirm",
        "run_id": run_id,
    }
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
            out = {"ok": False, "engine": name, "error": f"{type(exc).__name__}: {exc}"[:800]}
        elapsed = round(time.perf_counter() - t0, 3)
        brief = _brief(out if isinstance(out, dict) else {"ok": True, "raw": str(out)[:400]})
        brief["elapsed_s"] = elapsed
        results[name] = brief
        for key in ("op_name", "architecture", "arch_dir", "run_id"):
            if isinstance(out, dict) and out.get(key):
                ctx[key] = out[key]
        print(json.dumps(brief, ensure_ascii=False, default=str)[:3000], flush=True)
        if not (out.get("ok") if isinstance(out, dict) else True):
            results["ok"] = False
            results["failed_step"] = name
            results["elapsed_s"] = round(time.perf_counter() - t_all, 3)
            (OUT / "rebuild.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            print("REBUILD_FAILED", flush=True)
            return 1

    results["ok"] = True
    results["elapsed_s"] = round(time.perf_counter() - t_all, 3)
    (OUT / "rebuild.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "elapsed_s": results["elapsed_s"]}, ensure_ascii=False), flush=True)
    print("ALL_DONE ok=True", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
