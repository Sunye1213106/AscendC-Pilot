# -*- coding: utf-8 -*-
"""Force a cold FAG extract_host and record wall clock."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]

OP = Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad")
ARCH = "arch35"
OUT = REPO / "docs" / "test" / "results" / "uo-cannbot" / "fag_extract.json"


def main() -> int:
    from uo_init.codemap_engines import extract
    from uo_init.extract_cache import fingerprint_meta_path
    from uo_init.paths import require_architecture
    from uo_init.pilot_engines import _uo_root
    from uo_init.tu_cache import tu_cache_dir, uo_cache_root

    os.environ["UO_ARCH"] = ARCH
    os.environ["UO_TIMING"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"

    arch = require_architecture(ARCH)
    uo = _uo_root(OP, arch=arch)
    cache = uo_cache_root(OP, arch)
    tu = tu_cache_dir(OP, arch)
    fp = fingerprint_meta_path(uo)
    pkl = uo / "ir" / "host_ir.pkl"
    wiped: list[str] = []
    if cache.is_dir():
        shutil.rmtree(cache)
        wiped.append(str(cache))
    if fp.is_file():
        fp.unlink()
        wiped.append(str(fp))
    if pkl.is_file():
        pkl.unlink()
        wiped.append(str(pkl))
    print("wiped", wiped, flush=True)
    ctx = {
        "op_name": OP.name,
        "architecture": ARCH,
        "arch_dir": ARCH,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "confirm",
    }
    t0 = time.perf_counter()
    out = extract(OP, ctx)
    dt = round(time.perf_counter() - t0, 3)
    payload = {
        "elapsed_s": dt,
        "ok": bool(out.get("ok")),
        "error": out.get("error"),
        "failed_step": out.get("failed_step"),
        "target_s": 120,
        "hard_cap_s": 150,
        "within_target": dt <= 120,
        "within_cap": dt <= 150,
        "profile": "fast",
        "cache_mode": "true-cold-extract",
        "tu_cache": str(tu),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0 if out.get("ok") and dt <= 150 else 1


if __name__ == "__main__":
    raise SystemExit(main())
