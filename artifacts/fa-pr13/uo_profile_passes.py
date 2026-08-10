#!/usr/bin/env python3
"""Break down source_gaps + kernel_tiling_closure wall time."""
from __future__ import annotations

import time
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.passes import source_contract, source_inventory
from uo_init.passes import source_resolution as SR
from uo_init.passes import kernel_tiling_closure as KTC
from uo_init.passes.source_text_cache import clear as clear_cache

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"


def main() -> int:
    clear_cache()
    cm = CodeMap(op_name="flash_attention_score_grad", architecture=ARCH)
    t0 = time.perf_counter()
    source_inventory.inventory_source_files(cm, OP, architecture=ARCH)
    source_contract.enrich_codemap_from_operator_source(cm, OP, architecture=ARCH)
    print(f"seed {time.perf_counter()-t0:.2f}s entities={len(cm.entities)}", flush=True)

    t0 = time.perf_counter()
    stats = {}
    for name, fn in (
        ("calls_macros", lambda: SR._extract_calls_macros_and_frontiers(cm, OP, ARCH)),
        ("tiling_reads", lambda: SR._resolve_tiling_reads(cm, OP, ARCH)),
        ("compile_facts", lambda: SR._extract_compile_facts(cm, OP, ARCH)),
        ("runtime_structs", lambda: SR._extract_runtime_structs_and_resources(cm, OP, ARCH)),
    ):
        t1 = time.perf_counter()
        stats.update(fn())
        print(f"  gaps.{name} {time.perf_counter()-t1:.2f}s", flush=True)
    t1 = time.perf_counter()
    stats.update(SR._resolve_gap_records(cm, stats))
    print(f"  gaps.resolve_records {time.perf_counter()-t1:.2f}s", flush=True)
    print(f"source_gaps total {time.perf_counter()-t0:.2f}s", flush=True)

    t0 = time.perf_counter()
    t1 = time.perf_counter()
    kernel_texts = KTC._selected_kernel_texts(OP, ARCH)
    print(f"  closure.read_kernel {time.perf_counter()-t1:.2f}s files={len(kernel_texts)}", flush=True)
    t1 = time.perf_counter()
    host_texts = KTC._host_texts(OP, ARCH)
    print(f"  closure.read_host {time.perf_counter()-t1:.2f}s files={len(host_texts)}", flush=True)
    allowed = {KTC._rel(OP, p) for p in kernel_texts}
    t1 = time.perf_counter()
    removed = KTC._purge_broad_kernel_facts(cm, allowed)
    print(f"  closure.purge {time.perf_counter()-t1:.2f}s removed={removed}", flush=True)
    t1 = time.perf_counter()
    KTC._rebuild_kernel_contract(cm, OP, ARCH, kernel_texts)
    print(f"  closure.contract {time.perf_counter()-t1:.2f}s", flush=True)
    t1 = time.perf_counter()
    scopes, class_names = KTC._rebuild_kernel_scopes(cm, OP, ARCH, kernel_texts)
    print(f"  closure.scopes {time.perf_counter()-t1:.2f}s scopes={len(scopes)}", flush=True)
    t1 = time.perf_counter()
    KTC._rebuild_kernel_calls(cm, scopes, class_names)
    print(f"  closure.calls {time.perf_counter()-t1:.2f}s", flush=True)
    td = KTC._tiling_index(cm)
    t1 = time.perf_counter()
    KTC._rebuild_tiling_reads(cm, scopes, td)
    print(f"  closure.tiling_reads {time.perf_counter()-t1:.2f}s", flush=True)
    t1 = time.perf_counter()
    KTC._rebuild_host_tiling_writes(cm, OP, host_texts, td)
    print(f"  closure.host_writes {time.perf_counter()-t1:.2f}s", flush=True)
    print(f"closure total {time.perf_counter()-t0:.2f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
