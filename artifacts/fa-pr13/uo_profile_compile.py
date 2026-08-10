#!/usr/bin/env python3
"""Profile analyze+commit reuse on an already-extracted UO tree."""
from __future__ import annotations

import time
from pathlib import Path

from uo_init import codemap_engines as ce

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ctx = {
    "op_name": "flash_attention_score_grad",
    "architecture": "arch35",
    "arch_dir": "arch35",
    "auto_accept_clean": True,
    "force_confirm": True,
    "decision": "continue",
    "run_id": "profile_compile",
}


def main() -> int:
    t0 = time.time()
    out = ce.analyze(OP, ctx)
    print(
        "analyze",
        round(time.time() - t0, 2),
        "ok",
        out.get("ok"),
        "entities",
        (out.get("summary") or {}).get("entity_count"),
        flush=True,
    )
    if not out.get("ok"):
        print("analyze_err", out.get("error"), flush=True)
        return 1
    t1 = time.time()
    out2 = ce.commit(OP, ctx)
    print(
        "commit",
        round(time.time() - t1, 2),
        "ok",
        out2.get("ok"),
        "reused",
        out2.get("reused_analyze"),
        flush=True,
    )
    if not out2.get("ok"):
        print("commit_err", out2.get("error"), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
