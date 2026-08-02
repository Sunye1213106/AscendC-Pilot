# -*- coding: utf-8 -*-
"""Classify HostIR functions that have writes but empty calls_to (FAG arch35).

Read-only diagnostic. Uses `.probe_cache/fag_bundle.pkl` when present; otherwise
rebuilds via extract_host_bundle (slow).

    python scripts/_probe_orphan_calls.py
"""
from __future__ import annotations

import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"


def load_ir():
    if not BUNDLE.is_file():
        raise SystemExit(f"missing {BUNDLE}; run scripts/_probe_derive.py --refresh first")
    with BUNDLE.open("rb") as fh:
        return pickle.load(fh)["host_ir"]


def file_bucket(path: str) -> str:
    f = path.replace("\\", "/")
    if "/op_kernel/arch22/" in f:
        return "op_kernel/arch22"
    if "tiling_data_regbase" in f:
        return "op_kernel/arch35/tiling_data_regbase"
    if "/op_host/arch35/" in f and f.endswith(".cpp"):
        return "op_host/arch35/*.cpp"
    if f.endswith("flash_attention_score_grad_tiling.cpp"):
        return "op_host/*_tiling.cpp"
    return Path(f).name


def main() -> int:
    ir = load_ir()
    write_fns: dict[str, list] = defaultdict(list)
    for w in list(ir.writes) + list(ir.local_writes):
        if w.function:
            write_fns[w.function].append(w)

    orphan = sorted(fn for fn in write_fns if not ir.calls_to(fn))
    callees = {s.callee for s in ir.call_sites}

    rows = []
    for fn in orphan:
        ev = write_fns[fn][0]
        if fn.startswith("get_"):
            kind = "accessor_get"
        elif fn.startswith("set_"):
            kind = "accessor_set"
        elif fn in {
            "DoOpTiling",
            "DoLibApiTiling",
            "GetShapeAttrsInfo",
            "GetTilingKey",
            "GetWorkspaceSize",
            "IsCapable",
            "PostTiling",
        }:
            kind = "tiling_base_virtual"
        elif fn in {
            "TilingFlashAttentionGradScore",
            "TilingPrepareForFlashAttentionScoreGrad",
        }:
            kind = "impl_op_registry_entry"
        else:
            kind = "other"
        rows.append((kind, file_bucket(ev.file), fn, ev.file, ev.line, ev.path))

    print(f"write_fns={len(write_fns)} orphan={len(orphan)} call_sites={len(ir.call_sites)}")
    print("\n=== by (kind, file_bucket) ===")
    ctr = Counter((k, b) for k, b, *_ in rows)
    for (k, b), n in ctr.most_common():
        print(f"{n:4}  {k:28}  {b}")

    print("\n=== case-only spelling pairs (orphan set_X vs called set_x) ===")
    hits = []
    for kind, _bucket, fn, _file, _line, _path in rows:
        if kind != "accessor_set":
            continue
        alt = "set_" + fn[4:].lower()
        if alt in callees and alt != fn:
            hits.append((fn, alt, len(ir.calls_to(alt))))
    for h in hits:
        print(" ", h)
    if not hits:
        print("  (none)")

    print("\n=== examples per kind ===")
    seen = set()
    for kind, bucket, fn, file, line, path in rows:
        key = (kind, bucket)
        if key in seen:
            continue
        seen.add(key)
        print(f"[{kind} / {bucket}] {fn} @ {file}:{line} path={path}")

    print("\n=== note ===")
    print(
        "tiling_base_virtual calls exist in ops-transformer/common/include/op_host/"
        "tiling_base.h but are dropped by clang_walk _in_scope (op_needle)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
