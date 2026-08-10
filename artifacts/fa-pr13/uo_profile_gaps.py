#!/usr/bin/env python3
import time
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.passes import source_contract, source_inventory
from uo_init.passes import source_resolution as S
from uo_init.passes.source_text_cache import clear

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"


def main() -> int:
    clear()
    cm = CodeMap(op_name="fag", architecture=ARCH)
    source_inventory.inventory_source_files(cm, OP, architecture=ARCH)
    source_contract.enrich_codemap_from_operator_source(cm, OP, architecture=ARCH)
    files = S._kernel_files(OP, ARCH)
    print("kernel_files", len(files), flush=True)

    t_fn = t_mac = t_call = t_type = t_branch = 0.0
    n_fn = n_call = 0
    for path in files:
        text = S._read(path)
        file = S._rel(OP, path)
        t0 = time.perf_counter()
        functions = S._function_scopes(text, file)
        t_fn += time.perf_counter() - t0
        n_fn += len(functions)
        t0 = time.perf_counter()
        macros = S._macro_scopes(text, file)
        t_mac += time.perf_counter() - t0
        all_scopes = functions + macros
        for scope in all_scopes:
            body = text[scope.body_start:scope.body_end]
            t0 = time.perf_counter()
            for _ in S._CALL_RE.finditer(body):
                n_call += 1
            t_call += time.perf_counter() - t0
            t0 = time.perf_counter()
            for _ in S._BRANCH_RE.finditer(body):
                pass
            t_branch += time.perf_counter() - t0
    print(
        f"fn={t_fn:.2f}s({n_fn}) mac={t_mac:.2f}s call={t_call:.2f}s({n_call}) "
        f"branch={t_branch:.2f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
