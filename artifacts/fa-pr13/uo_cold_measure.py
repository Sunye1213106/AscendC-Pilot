#!/usr/bin/env python3
"""Cold uo-init measurement + CodeMap semantic comparison.

Baseline for comparison (rebuild_uo_construct.log, 2026-08-10 16:32):
  extract_host_bundle TOTAL 311.9s, host||kernel 286.793s,
  controls=684 writes=286 kernel_branches=471,
  entity_count=4442 relation_count=8443, dependency_coverage=12/19.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
OUT = Path("/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13")


def wipe_cold() -> None:
    for rel in (f".ascendc-pilot/{ARCH}/uo", ".ascendc-pilot/uo"):
        shutil.rmtree(OP / rel, ignore_errors=True)
    (OP / ".ascendc-pilot" / ARCH / "uo").mkdir(parents=True, exist_ok=True)
    (OP / ".ascendc-pilot" / "uo").mkdir(parents=True, exist_ok=True)


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "python"
    wipe_cold()

    from uo_init import codemap_engines as ce

    ctx = {
        "op_name": "flash_attention_score_grad",
        "architecture": ARCH,
        "arch_dir": ARCH,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "continue",
        "run_id": f"coldmeasure_{int(time.time())}",
    }
    phases: dict[str, float] = {}
    summary: dict = {}
    steps = [
        ("prepare", ce.prepare),
        ("extract", ce.extract),
        ("analyze", ce.analyze),
        ("resolve", ce.resolve),
        ("commit", ce.commit),
    ]
    t_all = time.time()
    for name, fn in steps:
        t0 = time.time()
        print(f"-- {name} --", flush=True)
        out = fn(OP, ctx)
        phases[name] = round(time.time() - t0, 2)
        print(f"[measure] {name} wall={phases[name]}s ok={out.get('ok')}", flush=True)
        if name == "analyze":
            summary = out.get("summary") or {}
        if not out.get("ok") and name in {"prepare", "extract", "analyze", "commit"}:
            print(f"[measure] {name} FAILED err={out.get('error')}", flush=True)
            break
    phases["total"] = round(time.time() - t_all, 2)

    keep = (
        "entity_count",
        "relation_count",
        "has_host",
        "has_kernel",
        "has_host_kernel_path",
        "has_input_tilingkey_kernel_path",
        "has_tilingdata_kernel_path",
        "has_input_output_path",
        "tiling_key_declaration_coverage",
        "tiling_key_host_packing_coverage",
        "tiling_key_host_producer_coverage",
        "tiling_key_root_coverage",
        "tiling_key_dependency_coverage",
    )
    result = {
        "label": label,
        "native_walk": os.environ.get("UO_NATIVE_WALK", "unset"),
        "phases": phases,
        "codemap": {k: summary.get(k) for k in keep},
        "entities_by_kind": summary.get("entities_by_kind"),
        "relations_by_kind": summary.get("relations_by_kind"),
    }

    try:
        from uo_init.store.reader import find_uo_product, load_view_blob, read_meta

        product = find_uo_product(
            OP, op_name="flash_attention_score_grad", architecture=ARCH
        )
        if product is not None:
            meta = read_meta(product)
            space = load_view_blob(product, "tiling/exhaustive_key_space.yaml") or {}
            host = load_view_blob(product, "ir/tg_host_view.yaml") or {}
            graph = load_view_blob(product, "ir/operator_graph.yaml") or {}
            result["product"] = {
                "entity_count": meta.get("entity_count"),
                "relation_count": meta.get("relation_count"),
                "legal_key_count": space.get("legal_key_count"),
                "host_fields": len(host.get("fields") or []),
                "graph_fp": graph.get("fingerprint"),
            }
    except Exception as exc:  # noqa: BLE001
        result["product_error"] = str(exc)[:300]

    path = OUT / f"uo_cold_{label}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str), flush=True)
    print("WROTE", path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
