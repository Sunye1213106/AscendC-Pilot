#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from pathlib import Path

from uo_init.query.engine import CodeMapQuery
from uo_init.store.reader import read_codemap
from uo_init.ir.entity import EntityKind

UO = Path(r"D:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo")
OP = Path(r"D:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")


def window(file: str, line: int, before=2, after=10):
    rel = file.replace("\\", "/")
    if rel.startswith("flash_attention_score_grad/"):
        rel = rel[len("flash_attention_score_grad/") :]
    path = OP / rel
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(1, line - before), min(len(lines), line + after)
    return path, [f"{i}|{lines[i-1].rstrip()}" for i in range(lo, hi + 1)]


def main():
    t0 = time.perf_counter()
    q = CodeMapQuery(read_codemap(UO))
    cm = q.codemap

    names = [
        "templateSupportCond",
        "fBaseParams.enableSwizzle",
        "NZ_OUT_MIN_S_SIZE",
        "TND_SWIZZLE_PREFIX_NUM",
        "TND_SWIZZLE_MIN_S1_SIZE",
        "TND_SWIZZLE_MIN_S1_SIZE_1",
        "FP16_C0_SIZE",
        "CheckExceedL2Cache",
        "CheckIsLargeInvalidBlk",
        "tailZeroCount",
        "isSeqExistZero",
    ]
    out = {}
    for name in names:
        hits = q.find_symbol(name)
        # summarize
        rows = []
        for h in hits[:8]:
            rows.append(
                {
                    "kind": h.get("kind"),
                    "name": h.get("name"),
                    "file": h.get("file"),
                    "line": h.get("line_start"),
                    "status": h.get("status"),
                    "provenance": h.get("provenance"),
                    "value_expr": h.get("value_expr"),
                    "producer_sites": h.get("producer_sites"),
                    "expression": h.get("expression"),
                    "lhs": h.get("lhs"),
                    "guards": h.get("guards"),
                    "compile_root": h.get("compile_root"),
                }
            )
        out[name] = {"count": len(hits), "hits": rows}
        # callers for helpers
        if name.startswith("Check"):
            out[name]["callers"] = q.callers(name)[:10]
            out[name]["callees"] = q.callees(name)[:10]

    # predicate for templateSupportCond via entity attrs
    for e in cm.entities.values():
        if e.name == "templateSupportCond" or e.attrs.get("lhs") == "templateSupportCond":
            out.setdefault("templateSupportCond_entities", []).append(
                {
                    "kind": e.kind_name(),
                    "name": e.name[:200],
                    "file": e.file,
                    "line": e.line_start,
                    "attrs": {
                        k: e.attrs.get(k)
                        for k in (
                            "expression",
                            "lhs",
                            "guards",
                            "producer_sites",
                            "provenance",
                            "function",
                        )
                    },
                }
            )

    # Get predicate expression entity that defines templateSupportCond
    preds = []
    for e in cm.by_kind(EntityKind.PREDICATE):
        if e.attrs.get("lhs") == "templateSupportCond":
            preds.append(
                {
                    "expression": e.attrs.get("expression") or e.name,
                    "file": e.file,
                    "line": e.line_start,
                    "guards": e.attrs.get("guards"),
                    "function": e.attrs.get("function"),
                }
            )
    out["templateSupportCond_predicates"] = preds

    for e in cm.by_kind(EntityKind.PREDICATE):
        if e.attrs.get("lhs") == "fBaseParams.enableSwizzle":
            out.setdefault("enableSwizzle_predicates", []).append(
                {
                    "expression": e.attrs.get("expression") or e.name,
                    "file": e.file,
                    "line": e.line_start,
                    "guards": e.attrs.get("guards"),
                }
            )

    # Minimal source verify for constants / helpers using UO locations only
    verify = []
    targets = []
    for name, payload in out.items():
        if not isinstance(payload, dict):
            continue
        for h in payload.get("hits") or []:
            if h.get("file") and h.get("line"):
                targets.append((name, h["file"], int(h["line"])))
                break
    for name, f, ln in targets:
        path, win = window(f, ln, before=1, after=8)
        verify.append({"name": name, "path": str(path), "line": ln, "window": win})

    # Independent gap hunt: does UO mention early-return before GetTilingKey affecting these keys?
    # Search graph for GetTilingKey / DoOpTiling return paths CONTROLS - limited.
    get_key = q.find_symbol("GetTilingKey")
    do_op = q.find_symbol("FlashAttentionScoreGradTilingNormalRegbase::DoOpTiling")
    if not do_op:
        do_op = [h for h in q.find_symbol("DoOpTiling") if "NormalRegbase" in str(h.get("name") or h.get("file") or "")]
    out["GetTilingKey_hits"] = [
        {"name": h.get("name"), "file": h.get("file"), "line": h.get("line_start"), "kind": h.get("kind")}
        for h in get_key[:6]
    ]
    out["DoOpTiling_hits"] = [
        {"name": h.get("name"), "file": h.get("file"), "line": h.get("line_start"), "kind": h.get("kind")}
        for h in do_op[:6]
    ]

    # Read only the UO-pointed GetTilingKey packing line window
    for h in get_key:
        if h.get("file") and "normal_regbase.cpp" in str(h.get("file")) and h.get("kind") in {"METHOD", "FUNCTION"}:
            path, win = window(h["file"], int(h["line_start"] or 1435), before=0, after=40)
            verify.append({"name": "GetTilingKey_body_from_uo", "path": str(path), "line": h["line_start"], "window": win})
            break

    report = {
        "elapsed_s": round(time.perf_counter() - t0, 4),
        "symbols": out,
        "verify_windows": verify,
    }
    Path(__file__).with_name("agent_uo_gap_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("elapsed", report["elapsed_s"])
    print("\n## templateSupportCond predicates from UO")
    for p in preds:
        print(p["file"], p["line"])
        print(p["expression"])
        print("guards", p["guards"])
    print("\n## enableSwizzle predicates")
    for p in out.get("enableSwizzle_predicates") or []:
        print(p["file"], p["line"])
        print(p["expression"])
    print("\n## constants / helpers")
    for name in names:
        hits = out[name]["hits"]
        if not hits:
            print(name, "MISSING_IN_UO")
            continue
        h = hits[0]
        print(
            name,
            "->",
            h.get("kind"),
            h.get("file"),
            h.get("line"),
            "value=",
            h.get("value_expr"),
            "status=",
            h.get("status"),
            "prov=",
            h.get("provenance"),
        )
    print("\n## windows")
    for v in verify:
        print("\n[", v["name"], "]", v["path"], ":", v["line"])
        print("\n".join(v["window"][:12]))


if __name__ == "__main__":
    main()
