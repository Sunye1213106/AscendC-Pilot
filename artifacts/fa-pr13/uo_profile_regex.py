#!/usr/bin/env python3
import time
from pathlib import Path

from uo_init.passes import kernel_tiling_closure as K
from uo_init.passes.source_text_cache import clear

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")


def main() -> int:
    clear()
    texts = K._selected_kernel_texts(OP, "arch35")
    print("files", len(texts), "bytes", sum(len(r) for r, _ in texts.values()), flush=True)
    t0 = time.perf_counter()
    n = sum(len(K._iter_function_defs(masked)) for _p, (_r, masked) in texts.items())
    print(f"_iter_function_defs {time.perf_counter()-t0:.2f}s hits={n}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
