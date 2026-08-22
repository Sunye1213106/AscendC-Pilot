# -*- coding: utf-8 -*-
"""Follow hint/next/file:line on non-usable FAG asks until usable or stuck."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]

FAG = Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad")
OUT = REPO / "docs" / "test" / "results" / "uo-cannbot" / "fag_followup_rounds.json"


def _cards(p: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (p.get("cards") or []) if isinstance(c, dict)]


def _head(p: dict[str, Any]) -> dict[str, Any]:
    rows = _cards(p) or [c for c in (p.get("phases") or []) if isinstance(c, dict)]
    return rows[0] if rows else {}


def _span(c: dict[str, Any]) -> str:
    f = str(c.get("file") or "").replace("\\", "/")
    n = int(c.get("line") or c.get("line_start") or 0)
    return f"{f}:{n}" if f and n else ""


def _kind_hit(p: dict[str, Any], kinds: set[str]) -> dict[str, Any] | None:
    for c in _cards(p):
        if str(c.get("kind") or "") in kinds:
            return c
    return None


def run_case(q, case: dict[str, Any]) -> dict[str, Any]:
    hops: list[dict[str, Any]] = []
    payload: dict[str, Any] | None = None
    grade = "partial"
    stop = ""

    for i, step in enumerate(case["steps"], start=1):
        payload = q.agent_query(**step["argv"])
        card = _head(payload)
        extras = card.get("extras") if isinstance(card.get("extras"), dict) else {}
        hop = {
            "round": i,
            "why": step["why"],
            "argv": step["argv"],
            "shape": payload.get("shape"),
            "ok": bool(payload.get("ok")),
            "span": _span(card),
            "kind": card.get("kind") or "",
            "name": card.get("name") or card.get("pipe") or "",
            "blocks": payload.get("matching_block_count"),
            "writers": len(extras.get("writers") or []),
            "readers": len(extras.get("readers") or []),
            "next": list(payload.get("next") or [])[:4],
            "hint": str(payload.get("hint") or "")[:180],
        }
        hops.append(hop)
        grade, stop = case["judge"](payload)
        hop["grade"] = grade
        hop["stop"] = stop
        print(f"{case['id']} R{i} {grade:8} {hop['shape']} {hop['span'] or hop.get('blocks')} {stop}", flush=True)
        if grade == "usable":
            break

    return {
        "id": case["id"],
        "question": case["question"],
        "rounds": len(hops),
        "final": grade,
        "stop": stop,
        "hops": hops,
    }


def main() -> int:
    from uo_init.uo_query import open_query

    q = open_query(FAG, architecture="arch35")

    def judge_q6(p: dict[str, Any]) -> tuple[str, str]:
        blocks = int(p.get("matching_block_count") or 0)
        nearby = ((p.get("coverage") or {}).get("nearby") or []) if isinstance(p.get("coverage"), dict) else []
        values = []
        for row in nearby:
            values.extend(row.get("values") or [])
        if blocks > 0:
            return "usable", f"retry hit {blocks} blocks; true itself does not alias"
        if values:
            return "partial", f"empty cover; nearby values={values}"
        return "partial", "no nearby"

    def judge_q9(p: dict[str, Any]) -> tuple[str, str]:
        extras = (_head(p).get("extras") or {}) if _head(p) else {}
        writers = extras.get("writers") or []
        readers = extras.get("readers") or []
        edges = (_head(p).get("edges") or {}) if _head(p) else {}
        reads = int((edges.get("READS") or {}).get("count") or 0)
        if writers and (readers or reads):
            return "usable", f"writers={len(writers)} readers={len(readers) or reads}"
        if writers:
            return "partial", "writers only; kernel READS still missing"
        return "partial", "no writers/readers"

    def judge_q10(p: dict[str, Any]) -> tuple[str, str]:
        hit = _kind_hit(p, {"TILING_DATA"})
        if hit and _span(hit):
            return "usable", f"TILING_DATA {_span(hit)}"
        kind = str(_head(p).get("kind") or "")
        if kind == "FIELD":
            return "partial", "still a member FIELD, not the struct"
        if kind in {"FUNCTION", "METHOD"} and "Tiling" in str(_head(p).get("name") or ""):
            return "partial", f"{kind} {_head(p).get('name')} — not the struct yet"
        return "partial", f"kind={kind or p.get('shape')}"

    def judge_q13(p: dict[str, Any]) -> tuple[str, str]:
        cards = _cards(p) or [_head(p)]
        names = []
        for c in cards:
            span = _span(c)
            name = str(c.get("name") or "")
            file = str(c.get("file") or "")
            names.append(f"{name}@{span}")
            if "empty_tensor" in file.replace("\\", "/"):
                continue
            if c.get("kind") in {"METHOD", "FUNCTION"} and span and "Process" in name:
                if any(key in file.replace("\\", "/") for key in ("kernel.h", "kernel_base.h", "post_regbase", "pre_regbase")):
                    return "usable", f"non-empty Process {span}"
        if _head(p).get("kind") in {"METHOD", "FUNCTION"} and _span(_head(p)):
            return "partial", f"still EmptyTensor or other: {names[:3]}"
        return "partial", f"shape={p.get('shape')} {names[:2]}"

    def judge_q20(p: dict[str, Any]) -> tuple[str, str]:
        card = _head(p)
        extras = card.get("extras") if isinstance(card.get("extras"), dict) else {}
        role = str(extras.get("role") or card.get("role") or "")
        catalog = str(extras.get("catalog") or card.get("catalog") or "")
        span = _span(card)
        if (role == "host_refuse" or catalog == "ge.graphStatus") and span:
            return "usable", f"host_refuse {span}"
        if span and "graph" in str(card.get("name") or "").lower():
            return "usable", f"refuse site {span}"
        if role == "host_refuse" or catalog == "ge.graphStatus":
            return "partial", "typed host_refuse, no file:line"
        if span:
            return "partial", f"span {span} but not typed as refuse root"
        return "partial", f"kind={card.get('kind')} span=none"

    cases = [
        {
            "id": "Q6",
            "question": "BOOL 别名 IsTnd=true 能否对上 0/1？",
            "judge": judge_q6,
            "steps": [
                {"why": "first ask", "argv": {"pattern": "IsTnd=true"}},
                {"why": "hint nearby values 0/1 → IsTnd=1", "argv": {"pattern": "IsTnd=1"}},
            ],
        },
        {
            "id": "Q9",
            "question": "s1Inner 谁写谁读？",
            "judge": judge_q9,
            "steps": [
                {"why": "first ask", "argv": {"pattern": "s1Inner"}},
                {
                    "why": "around Host writer from extras",
                    "argv": {
                        "file": "op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp",
                        "line": 1899,
                    },
                },
                {
                    "why": "around kernel field decl",
                    "argv": {
                        "file": "op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h",
                        "line": 197,
                    },
                },
                {"why": "follow next owner struct", "argv": {"pattern": "FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase"}},
            ],
        },
        {
            "id": "Q10",
            "question": "tilingData / TilingData 结构在哪？",
            "judge": judge_q10,
            "steps": [
                {"why": "first ask", "argv": {"pattern": "tilingData"}},
                {"why": "follow next InitTilingData", "argv": {"pattern": "InitTilingData"}},
                {
                    "why": "around member FIELD",
                    "argv": {
                        "file": "op_kernel/arch35/flash_attention_score_grad_block_cube.h",
                        "line": 158,
                    },
                },
                {"why": "battery ident struct name", "argv": {"pattern": "FlashAttentionScoreGradTilingData"}},
            ],
        },
        {
            "id": "Q13",
            "question": "Process 定义体在哪？",
            "judge": judge_q13,
            "steps": [
                {"why": "first ask", "argv": {"pattern": "Process"}},
                {
                    "why": "definition_sites kernel.h:493",
                    "argv": {
                        "file": "op_kernel/arch35/flash_attention_score_grad_kernel.h",
                        "line": 493,
                    },
                },
                {
                    "why": "definition_sites kernel_base.h:237",
                    "argv": {
                        "file": "op_kernel/arch35/flash_attention_score_grad_kernel_base.h",
                        "line": 237,
                    },
                },
            ],
        },
        {
            "id": "Q20",
            "question": "GRAPH_FAILED 是不是 Host 拒单入口？",
            "judge": judge_q20,
            "steps": [
                {"why": "first ask", "argv": {"pattern": "GRAPH_FAILED"}},
                {"why": "catalog name ge.graphStatus", "argv": {"pattern": "graphStatus"}},
                {
                    "why": "follow next guard as around from CheckShapeValid family",
                    "argv": {"pattern": "CheckVarLenSparseModeValue"},
                },
                {"why": "OP_CHECK_IF host refuse sites", "argv": {"pattern": "OP_CHECK_IF"}},
            ],
        },
    ]

    results = []
    try:
        for case in cases:
            results.append(run_case(q, case))
    finally:
        q.close()

    summary = {
        "n": len(results),
        "reached_usable": sum(1 for r in results if r["final"] == "usable"),
        "stuck_partial": sum(1 for r in results if r["final"] != "usable"),
        "rounds": {r["id"]: r["rounds"] if r["final"] == "usable" else None for r in results},
        "final": {r["id"]: r["final"] for r in results},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
