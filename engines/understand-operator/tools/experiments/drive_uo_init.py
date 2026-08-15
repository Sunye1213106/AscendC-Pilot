#!/usr/bin/env python3
"""FAG experiment driver for uo-init stages. Not a product entry point.

Product path is ``codemap_engines`` / ``acp start uo-init``.
Set ``UO_OP_DIR`` (or ``ASCENDC_PROJECT_ROOT``) to the operator source root.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OP = Path(
    os.environ.get("UO_OP_DIR")
    or os.environ.get("ASCENDC_PROJECT_ROOT")
    or ""
)
ARCH = os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or ""
SUMMARY = REPO / "_uo_init_full_summary.json"

sys.path[:0] = [
    str(REPO / "engines/understand-operator/src"),
    str(REPO / "engines/common"),
    str(REPO / "pilot"),
]

from uo_init.codemap_engines import (  # noqa: E402
    analyze,
    commit,
    extract,
    prepare,
    verify,
)


def _brief(out: dict) -> dict:
    keys = (
        "ok",
        "engine",
        "error",
        "failed_step",
        "path",
        "steps",
        "summary",
        "blocking",
        "uo_product",
        "gaps",
        "gap_count",
        "semantic_completeness",
        "verdict",
    )
    return {k: out.get(k) for k in keys if k in out}


def main() -> int:
    from ascendc_pilot.state import start_workflow

    if not str(OP) or not ARCH:
        print("Set UO_OP_DIR (or ASCENDC_PROJECT_ROOT) and UO_ARCH", flush=True)
        return 2

    print("----- acp start uo-init -----", flush=True)
    started = start_workflow(
        OP,
        "uo-init",
        op_name="flash_attention_score_grad",
        architecture=ARCH,
    )
    run_id = str(started.get("run_id") or "")
    print(json.dumps({"run_id": run_id, "phase": started.get("phase")}, ensure_ascii=False), flush=True)
    if not run_id:
        print("STOP: start_workflow did not return run_id", flush=True)
        return 1

    ctx = {
        "op_name": "flash_attention_score_grad",
        "architecture": ARCH,
        "arch_dir": ARCH,
        "auto_accept_clean": True,
        # WSL often lacks full CANN include path; kernel probe is dirty but
        # arch35 host/kernel paths are already resolved — continue like primary confirm.
        "force_confirm": True,
        "decision": "confirm",
        "run_id": run_id,
    }
    results: dict = {"start": {"ok": True, "run_id": run_id, "phase": started.get("phase")}}

    for name, fn in (
        ("prepare", prepare),
        ("extract", extract),
        ("analyze", analyze),
        ("commit", commit),
        ("verify", verify),
    ):
        print(f"\n----- {name} -----", flush=True)
        try:
            out = fn(OP, ctx)
        except Exception as exc:
            traceback.print_exc()
            out = {"ok": False, "engine": name, "error": str(exc)[:800]}
        results[name] = _brief(out)
        for key in ("op_name", "architecture", "arch_dir", "run_id"):
            if out.get(key):
                ctx[key] = out[key]
        print(json.dumps(results[name], ensure_ascii=False, indent=2, default=str)[:4000], flush=True)
        if not out.get("ok"):
            SUMMARY.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(f"STOP at {name}", flush=True)
            return 1

    print("\n----- unresolved residual (retained; not LLM-patched) -----", flush=True)
    from uo_init import pilot_engines as pe  # noqa: E402

    uo = pe._uo_root(OP, arch=ARCH)
    unresolved = uo / "ir" / "unresolved.yaml"
    print(f"uo_root={uo} unresolved_exists={unresolved.is_file()}", flush=True)
    if unresolved.is_file():
        print(unresolved.read_text(encoding="utf-8", errors="replace")[:2000], flush=True)

    print("\n===== Product inventory =====", flush=True)
    root = OP / ".ascendc-pilot"
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                print(f"{p.relative_to(OP)}  {p.stat().st_size}", flush=True)
    else:
        print("no .ascendc-pilot under operator", flush=True)

    SUMMARY.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("summary ->", SUMMARY, flush=True)
    print("ALL_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
