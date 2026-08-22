# -*- coding: utf-8 -*-
"""Serial uo-query probe for the 13 FAG arch35 host lemmas. One connection."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(r"d:\TEST\AscendC-Pilot")
OP = Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad")
ARCH = "arch35"
OUT = Path(r"d:\TEST\AscendC-Pilot\docs\history\fag_test\uoquery-lemma-cards.json")

sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]

from uo_init.uo_query import open_query  # noqa: E402

DIMS = [
    "InputDType",
    "IsRope",
    "DTemplateNum",
    "IsDNoEqual",
    "IsBn2MultiBlk",
    "IsTnd",
    "DeterType",
    "SplitAxis",
    "IsDrop",
    "S1TemplateNum",
    "S2TemplateNum",
    "IsAttenMask",
    "IsNEqual",
    "IsTndSwizzle",
]

COMBOS = [
    # L1
    ("L1", "InputDType=4", "expect_template_empty"),
    ("L1", "InputDType=5", "expect_template_empty"),
    ("L1", "InputDType=6", "expect_template_empty"),
    ("L1", "S1TemplateNum=512", "expect_template_empty"),
    ("L1", "S2TemplateNum=256", "expect_template_empty"),
    ("L1", "S2TemplateNum=512", "expect_template_empty"),
    # L2
    ("L2", "IsRope=1,DTemplateNum=64", "expect_template_hit_host_exclude"),
    ("L2", "IsRope=1,DTemplateNum=128", "expect_template_hit_host_exclude"),
    ("L2", "IsRope=1,DTemplateNum=256", "expect_template_hit_host_exclude"),
    ("L2", "IsRope=1,DTemplateNum=768", "expect_template_hit_host_exclude"),
    ("L2", "IsRope=1,DTemplateNum=192", "control_should_hit"),
    # L3
    ("L3", "IsRope=1,IsDNoEqual=0", "expect_template_hit_host_exclude"),
    ("L3", "IsRope=1,IsDNoEqual=1", "control_should_hit"),
    # L4
    ("L4", "IsBn2MultiBlk=1,IsRope=1", "expect_template_hit_host_exclude"),
    ("L4", "IsBn2MultiBlk=1,IsDNoEqual=1", "expect_template_hit_host_exclude"),
    # L5
    ("L5", "IsTnd=1,IsBn2MultiBlk=1", "expect_template_hit_host_exclude"),
    # L6
    ("L6", "IsBn2MultiBlk=1,DeterType=1", "expect_template_empty"),
    ("L6", "IsBn2MultiBlk=1,DeterType=2", "expect_template_empty"),
    ("L6", "IsBn2MultiBlk=1,DeterType=3", "expect_template_empty"),
    ("L6", "IsBn2MultiBlk=1,DeterType=4", "expect_template_empty"),
    ("L6", "IsBn2MultiBlk=1,DeterType=0", "control_should_hit"),
    # L7
    ("L7", "SplitAxis=5,IsDrop=1,DTemplateNum=192", "expect_template_hit_host_exclude"),
    ("L7", "SplitAxis=5,IsDrop=1,DTemplateNum=256", "expect_template_hit_host_exclude"),
    ("L7", "SplitAxis=5,IsDrop=1,DTemplateNum=768", "expect_template_hit_host_exclude"),
    ("L7", "SplitAxis=5,IsDrop=1,DTemplateNum=128", "control_should_hit"),
    # L8
    ("L8", "SplitAxis=5,IsTnd=0,DTemplateNum=192", "expect_template_hit_host_exclude"),
    ("L8", "SplitAxis=5,IsTnd=0,DTemplateNum=256", "expect_template_hit_host_exclude"),
    ("L8", "SplitAxis=5,IsTnd=0,DTemplateNum=768", "expect_template_hit_host_exclude"),
    # L9
    ("L9", "SplitAxis=1,IsTnd=1,DTemplateNum=192", "expect_template_hit_host_exclude"),
    ("L9", "SplitAxis=1,IsTnd=1,DTemplateNum=256", "expect_template_hit_host_exclude"),
    ("L9", "SplitAxis=1,IsTnd=1,DTemplateNum=768", "expect_template_hit_host_exclude"),
    ("L9", "SplitAxis=1,IsTnd=1,DTemplateNum=128", "control_should_hit"),
    # L10
    ("L10", "InputDType=1,DTemplateNum=768,S1TemplateNum=128", "expect_template_hit_host_exclude"),
    ("L10", "InputDType=1,DTemplateNum=768,S1TemplateNum=64", "control_should_hit"),
    # L11
    ("L11", "IsNEqual=1,DeterType=0", "expect_template_empty"),
    ("L11", "IsNEqual=1,DeterType=1", "expect_template_empty"),
    ("L11", "IsNEqual=1,DeterType=2", "control_should_hit"),
    # L12
    ("L12", "IsAttenMask=0,DeterType=4", "expect_template_hit_host_exclude"),
    ("L12", "IsAttenMask=0,DeterType=3", "expect_template_hit_host_exclude"),
    ("L12", "IsAttenMask=0,DeterType=0", "control_should_hit"),
    ("L12", "IsAttenMask=0,DeterType=1", "control_should_hit"),
    ("L12", "IsAttenMask=0,DeterType=2", "control_should_hit"),
    # L13
    ("L13", "IsTndSwizzle=1,DeterType=2", "expect_template_hit_host_exclude"),
    ("L13", "IsTndSwizzle=1,DeterType=3", "expect_template_hit_host_exclude"),
    ("L13", "IsTndSwizzle=1,DeterType=4", "expect_template_hit_host_exclude"),
    ("L13", "IsTndSwizzle=1,DeterType=0", "control_should_hit"),
]

IDENTS = [
    "ProcessQuantInfo",
    "DetermineMode",
    "GetS1S2TemplateType",
    "GetDTemplateType",
    "GetTilingKey",
    "hasRope",
    "IsRope",
    "isBn2MultiBlk",
    "SetSparseParams",
    "GetDeterSparseTilingKey",
    "isTndSwizzle",
    "GRAPH_FAILED",
    "SetSplitAxis",
    "isDeterNEqual",
    "keepProb",
    "bn2S2RouteLimit",
    "bn2S2NotTndLimit",
    "templateSupportCond",
]


def _snip_head(text: str, n: int = 12) -> str:
    lines = str(text or "").splitlines()
    return "\n".join(lines[:n])


def _edge_counts(edges: dict) -> dict:
    out = {}
    if not isinstance(edges, dict):
        return out
    for rel, bucket in edges.items():
        if isinstance(bucket, dict):
            out[rel] = int(bucket.get("count") or 0)
        else:
            out[rel] = bucket
    return out


def compact(payload: dict, *, ms: float) -> dict:
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    cards = payload.get("cards") or payload.get("phases") or []
    if not isinstance(cards, list):
        cards = []
    cover = payload.get("dim_coverage") or payload.get("coverage") or {}
    if not isinstance(cover, dict):
        cover = {}
    slim_cards = []
    for c in cards[:8]:
        if not isinstance(c, dict):
            continue
        slim_cards.append(
            {
                "kind": c.get("kind"),
                "name": c.get("name") or c.get("phase") or c.get("id"),
                "file": c.get("file") or "",
                "line": c.get("line") or c.get("line_start") or 0,
                "truncated": bool(c.get("truncated")),
                "catalog": c.get("catalog"),
                "role": c.get("role"),
                "definition_span": c.get("definition_span"),
                "writers": (c.get("writers") or [])[:6],
                "readers": (c.get("readers") or [])[:4],
                "edge_counts": _edge_counts(c.get("edges") or {}),
                "snippet_head": _snip_head(c.get("snippet") or c.get("text") or ""),
            }
        )
    return {
        "ok": payload.get("ok"),
        "shape": payload.get("shape") or payload.get("mode"),
        "count": payload.get("count"),
        "matching_block_count": payload.get("matching_block_count"),
        "completeness": payload.get("completeness") or cover.get("completeness"),
        "declared": cover.get("declared") or payload.get("declared"),
        "product": cover.get("product") or payload.get("product"),
        "nearby": cover.get("nearby") or payload.get("nearby"),
        "hint": (payload.get("hint") or "")[:240],
        "next": payload.get("next"),
        "canonical": payload.get("canonical"),
        "ms": round(ms, 1),
        "bytes": len(raw.encode("utf-8")),
        "cards": slim_cards,
        "error": payload.get("error") or payload.get("message_zh"),
    }


def run_one(q, *, pattern: str = "", file: str = "", line: int = 0) -> dict:
    t0 = time.perf_counter()
    payload = q.agent_query(pattern=pattern, file=file, line=line)
    ms = (time.perf_counter() - t0) * 1000
    return compact(payload, ms=ms)


def main() -> int:
    q = open_query(OP, architecture=ARCH)
    rows = []
    print("INDEX", flush=True)
    rows.append({"lemma": "INDEX", "query": "", "form": "index", **run_one(q)})

    for dim in DIMS:
        pat = f"Dim={dim}"
        print(pat, flush=True)
        rows.append({"lemma": "DIM", "query": pat, "form": "dim", **run_one(q, pattern=pat)})

    for lemma, pat, expect in COMBOS:
        print(pat, flush=True)
        rec = run_one(q, pattern=pat)
        rec.update({"lemma": lemma, "query": pat, "form": "combo", "expect": expect})
        rows.append(rec)

    arounds = []
    for name in IDENTS:
        print(name, flush=True)
        rec = run_one(q, pattern=name)
        rec.update({"lemma": "IDENT", "query": name, "form": "ident"})
        rows.append(rec)
        for card in rec.get("cards") or []:
            f = str(card.get("file") or "")
            line = int(card.get("line") or 0)
            if card.get("truncated") and f and line:
                arounds.append((name, f, line))

    seen = set()
    for name, f, line in arounds:
        key = (f, line)
        if key in seen:
            continue
        seen.add(key)
        print(f"AROUND {name} {f}:{line}", flush=True)
        rec = run_one(q, file=f, line=line)
        rec.update(
            {
                "lemma": "AROUND",
                "query": f"--file {f} --line {line}",
                "form": "around",
                "from_ident": name,
            }
        )
        rows.append(rec)

    report = {
        "op": str(OP),
        "arch": ARCH,
        "n": len(rows),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} n={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
