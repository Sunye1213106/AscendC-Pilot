#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
sys.path[:0] = [
    str(PILOT / "engines" / "understand-operator" / "src"),
    str(PILOT / "pilot"),
]
os.environ.update(
    {
        "UO_OP_DIR": str(OP),
        "UO_OPERATOR": "flash_attention_score_grad",
        "UO_ARCH": "arch35",
        "UO_OPS_ROOT": "/work/ops-transformer",
    }
)

from uo_init.query.engine import CodeMapQuery  # noqa: E402
from uo_init.store.reader import read_codemap  # noqa: E402

uo = OP / ".ascendc-pilot" / "uo" / "flash_attention_score_grad.arch35.uo"
if not uo.is_file():
    uo = PILOT / "artifacts" / "fa-pr13" / "flash_attention_score_grad.arch35.uo"
q = CodeMapQuery(read_codemap(uo), path=str(uo))
keys = {row["name"]: row for row in q.tiling_keys()}
report = {"uo": str(uo)}
for dim in ["IsTndSwizzle", "IsAttenMask", "SplitAxis", "DeterType", "IsRope"]:
    entry = {"dim": dim, "tiling_key": keys.get(dim)}
    try:
        entry["path_to_kernel"] = q.find_path(dim, end_kind="KERNEL")
    except Exception as exc:  # noqa: BLE001
        entry["path_to_kernel"] = {"error": str(exc)[:300]}
    for meth in ("producers", "guards", "writers", "all_writes"):
        fn = getattr(q, meth, None)
        if fn is None:
            continue
        try:
            r = fn(dim)
        except TypeError:
            try:
                r = fn(name=dim)
            except Exception as exc:  # noqa: BLE001
                entry[meth] = {"error": str(exc)[:300]}
                continue
        except Exception as exc:  # noqa: BLE001
            entry[meth] = {"error": str(exc)[:300]}
            continue
        entry[meth] = r
    report[dim] = entry

out = PILOT / "artifacts" / "fa-pr13" / "codemap_blame_dims.json"
# Make JSON-safe
out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)[:200000], encoding="utf-8")
print("WROTE", out)
for dim, e in report.items():
    print("==", dim)
    for k in ("packing", "producer", "guards"):
        v = e.get(k)
        print(k, str(v)[:350].replace("\n", " "))
