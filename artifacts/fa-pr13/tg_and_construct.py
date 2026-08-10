#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""After fresh .uo: tg-init engines + construct coverage over D."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
OP_NAME = "flash_attention_score_grad"
OUT = PILOT / "artifacts" / "fa-pr13"
LOG = OUT / "tg_and_construct.log"


def log(msg: str) -> None:
    text = msg if msg.endswith("\n") else msg + "\n"
    sys.stdout.write(text)
    sys.stdout.flush()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    sys.path[:0] = [
        str(PILOT / "pilot"),
        str(PILOT / "engines" / "testcase-generation"),
        str(PILOT / "engines" / "understand-operator" / "src"),
        str(PILOT / "scripts"),
    ]
    os.environ.update(
        {
            "ASCENDC_PROJECT_ROOT": str(OP),
            "UO_OP_DIR": str(OP),
            "UO_OPERATOR": OP_NAME,
            "UO_ARCH": ARCH,
            "UO_OPS_ROOT": "/work/ops-transformer",
            "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
        }
    )

    product = OP / ".ascendc-pilot" / "uo" / f"{OP_NAME}.{ARCH}.uo"
    if not product.is_file():
        log(f"MISSING product {product}")
        return 2
    shutil.copy2(product, OUT / f"{OP_NAME}.{ARCH}.uo")
    log(f"PRODUCT {product} size={product.stat().st_size}")

    from uo_init.store.reader import find_uo_product, load_view_blob, read_meta
    from uo_init.tg_projection import ensure_tg_views, legal_key_rows

    p = find_uo_product(OP, op_name=OP_NAME, architecture=ARCH)
    meta = read_meta(p)
    space = load_view_blob(p, "tiling/exhaustive_key_space.yaml") or {}
    host = load_view_blob(p, "ir/tg_host_view.yaml") or {}
    log(
        json.dumps(
            {
                "meta": {
                    k: meta.get(k)
                    for k in (
                        "schema",
                        "op_name",
                        "architecture",
                        "entity_count",
                        "relation_count",
                    )
                },
                "legal_key_count": (space or {}).get("legal_key_count"),
                "host_fields": len((host or {}).get("fields") or []),
                "ensure": ensure_tg_views(OP, op_name=OP_NAME, architecture=ARCH),
            },
            ensure_ascii=False,
            default=str,
        )
    )

    from ascendc_pilot.actions import engines as E
    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(OP, arch=ARCH)
    ctx = {
        "op_name": OP_NAME,
        "architecture": ARCH,
        "mode": "tilingkey_full_coverage",
        "level": "L0",
    }
    for name, fn in [
        ("init_intent", E._run_tg_init_intent),
        ("kb_check", E._run_tg_kb_check),
        ("contract_build", E._run_tg_contract_build),
        ("semantic_bind", E._run_tg_semantic_bind),
        ("integrity", E._run_tg_integrity),
    ]:
        log(f"-- {name} --")
        out = fn(OP, ctx)
        brief = {k: out.get(k) for k in ("ok", "error", "mode", "engine", "field_count")}
        if name == "contract_build":
            brief["declared"] = (out.get("payload") or {}).get("declared_set")
        log(json.dumps(brief, ensure_ascii=False, default=str)[:4000])
        if not out.get("ok") and name in {"kb_check", "contract_build", "semantic_bind"}:
            log(f"FATAL {name}")
            return 3

    tg = tg_root(OP, arch=ARCH)
    for rel in [
        "init/uo_ready.yaml",
        "contract/tilingkey_contract.yaml",
        "realization/binding_inventory.yaml",
    ]:
        path = tg / rel
        log(f"{rel}: {'OK' if path.is_file() else 'MISSING'}")

    # ---- construct over D ----
    from testcase_agent.closure import construct as C

    rows = legal_key_rows(p)
    log(f"D_rows={len(rows)}")
    ok = empty = errors = 0
    samples_ok: list = []
    samples_fail: list = []
    reason_hist: dict[str, int] = {}
    t0 = time.time()
    for i, row in enumerate(rows):
        dims = row.get("dims") or row.get("values") or {}
        if not isinstance(dims, dict) or not dims:
            empty += 1
            reason_hist["no_dims"] = reason_hist.get("no_dims", 0) + 1
            if len(samples_fail) < 8:
                samples_fail.append({"i": i, "key": row.get("tiling_key"), "reason": "no_dims"})
            continue
        t = {str(k): str(v) for k, v in dims.items()}
        try:
            cases = C.build(t, seed=0)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            reason_hist["exception"] = reason_hist.get("exception", 0) + 1
            if len(samples_fail) < 8:
                samples_fail.append(
                    {"i": i, "key": row.get("tiling_key"), "error": str(exc)[:240]}
                )
            continue
        if cases:
            ok += 1
            if len(samples_ok) < 3:
                samples_ok.append(
                    {"key": row.get("tiling_key"), "n_cases": len(cases), "dims": t}
                )
        else:
            empty += 1
            reason_hist["no_case"] = reason_hist.get("no_case", 0) + 1
            if len(samples_fail) < 8:
                samples_fail.append(
                    {"i": i, "key": row.get("tiling_key"), "dims": t, "reason": "no_case"}
                )
        if (i + 1) % 500 == 0:
            log(f"progress {i+1}/{len(rows)} ok={ok} empty={empty} errors={errors}")

    report = {
        "D": len(rows),
        "construct_ok": ok,
        "construct_empty": empty,
        "construct_errors": errors,
        "coverage": round(ok / len(rows), 4) if rows else 0.0,
        "elapsed_sec": round(time.time() - t0, 2),
        "reason_hist": reason_hist,
        "samples_ok": samples_ok,
        "samples_fail": samples_fail,
        "traces_tail": (C.last_traces() or [])[-5:],
    }
    report_path = OUT / "construct_coverage.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(json.dumps(report, ensure_ascii=False, indent=2)[:8000])
    log(f"WROTE {report_path}")
    return 0 if ok > 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
