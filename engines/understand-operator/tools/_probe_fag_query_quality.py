# -*- coding: utf-8 -*-
"""Probe FAG uo-query payload size and answer quality for cannbot-style asks."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]

FAG = Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad")
ARCH = "arch35"
OUT = REPO / "docs" / "test" / "results" / "uo-cannbot" / "fag_query_quality_probe.json"


def _size(payload: dict[str, Any]) -> tuple[int, int]:
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    n = len(raw.encode("utf-8"))
    return n, max(1, round(n / 4))


def _first_card(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("cards", "phases", "seeds"):
        rows = payload.get(key)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0]
    return {}


def _span(payload: dict[str, Any]) -> str:
    card = _first_card(payload)
    file = str(card.get("file") or "").replace("\\", "/")
    line = int(card.get("line") or card.get("line_start") or 0)
    if file and line:
        return f"{file}:{line}"
    return ""


def judge(case: dict[str, Any], payload: dict[str, Any], bytes_n: int) -> dict[str, Any]:
    want = case["expect"]
    shape = str(payload.get("shape") or "")
    ok = bool(payload.get("ok"))
    card = _first_card(payload)
    extras = card.get("extras") if isinstance(card.get("extras"), dict) else {}
    edges = card.get("edges") if isinstance(card.get("edges"), dict) else {}
    snippet = str(card.get("snippet") or "")
    span = _span(payload)
    writers = extras.get("writers") or []
    readers = extras.get("readers") or []
    blocks = int(payload.get("matching_block_count") or 0)
    dim_cov = payload.get("dim_coverage") if isinstance(payload.get("dim_coverage"), dict) else {}
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    completeness = str(coverage.get("completeness") or "")
    hint = str(payload.get("hint") or "")
    notes: list[str] = []
    grade = "usable"

    if want == "index":
        phases = list(payload.get("phases") or [])
        dims = list(payload.get("dim_names") or [])
        if not phases or not dims:
            grade = "weak"
            notes.append("missing launch phases or dim_names")
        elif "IsTnd=1" in hint:
            grade = "weak"
            notes.append("hint still hardcodes IsTnd=1")
        else:
            notes.append(f"{len(phases)} phases, {len(dims)} dims")
    elif want == "name_located":
        if not ok or shape != "name" or not span:
            grade = "fail"
            notes.append(f"shape={shape} span={span or 'none'}")
        else:
            if not snippet:
                notes.append("no snippet")
                grade = "partial"
            if want_writers := case.get("need_writers"):
                if not writers:
                    notes.append("writers empty")
                    grade = "partial" if grade != "fail" else grade
            if case.get("need_readers") and not readers:
                notes.append("readers empty")
                grade = "partial" if grade != "fail" else grade
            if not notes:
                notes.append(f"{card.get('kind')} @ {span}")
    elif want == "catalog_empty":
        if ok and (payload.get("cards") or []):
            grade = "weak"
            notes.append("catalog ident returned a card (should stay empty)")
        else:
            notes.append("empty as designed; follow hint")
            if not hint:
                grade = "partial"
                notes.append("no hint for retry")
    elif want == "cover_domain":
        values = dim_cov.get(case.get("dim") or "") or []
        if not values:
            grade = "fail"
            notes.append("dim_coverage empty")
        else:
            notes.append(f"{case.get('dim')}={values}")
    elif want == "cover_combo":
        if blocks <= 0:
            grade = "fail"
            notes.append("matching_block_count=0")
        elif completeness and completeness != "coverage_checked":
            grade = "partial"
            notes.append(f"completeness={completeness} blocks={blocks}")
        else:
            notes.append(f"{blocks} blocks, coverage_checked")
    elif want == "cover_empty_honest":
        if blocks != 0:
            grade = "fail"
            notes.append(f"expected 0, got {blocks}")
        elif completeness != "coverage_checked":
            grade = "partial"
            notes.append(f"0 hits but completeness={completeness or 'missing'}")
        else:
            notes.append("honest empty + coverage_checked")
    elif want == "around":
        if shape != "around" or not span:
            grade = "fail"
            notes.append(f"shape={shape} span={span or 'none'}")
        elif not snippet:
            grade = "partial"
            notes.append("around without snippet")
        else:
            notes.append(f"around {span}")
    elif want == "refuse_nl":
        if shape in {"name", "cover", "around"} and ok:
            grade = "weak"
            notes.append("NL/multi-token was answered as a structured hit")
        else:
            notes.append(f"shape={shape} ok={ok}")
    else:
        notes.append("unscored")

    if bytes_n > 24000:
        grade = "fail"
        notes.append(f"payload {bytes_n}B over 24k cap")
    elif bytes_n > 16000:
        notes.append("large payload (>16kB)")

    return {
        "grade": grade,
        "shape": shape,
        "ok": ok,
        "span": span,
        "kind": card.get("kind") or card.get("phase") or "",
        "name": card.get("name") or card.get("pipe") or "",
        "snippet_chars": len(snippet),
        "writers": len(writers),
        "readers": len(readers),
        "edge_kinds": sorted(edges),
        "blocks": blocks,
        "dim_keys": sorted(dim_cov)[:8],
        "completeness": completeness,
        "hint": hint[:160],
        "notes": notes,
    }


def main() -> int:
    from uo_init.uo_query import open_query

    cases: list[dict[str, Any]] = [
        {
            "id": "Q1",
            "scene": "index / launch",
            "question": "这个算子 launch 分几段？有哪些 tiling 维？",
            "argv": {},
            "expect": "index",
        },
        {
            "id": "Q2",
            "scene": "tilingkey / domain",
            "question": "IsTnd 声明域是什么？",
            "argv": {"pattern": "Dim=IsTnd"},
            "expect": "cover_domain",
            "dim": "IsTnd",
        },
        {
            "id": "Q3",
            "scene": "tilingkey / combo",
            "question": "IsTnd=1 模板能不能编过？有多少块？",
            "argv": {"pattern": "IsTnd=1"},
            "expect": "cover_combo",
        },
        {
            "id": "Q4",
            "scene": "tilingkey / combo",
            "question": "IsTnd=1 且 S2TemplateNum=1 这组能否编过？",
            "argv": {"pattern": "IsTnd=1,S2TemplateNum=1"},
            "expect": "cover_combo",
        },
        {
            "id": "Q5",
            "scene": "tilingkey / honesty",
            "question": "IsTnd=9 有没有合法块？（应诚实空集）",
            "argv": {"pattern": "IsTnd=9"},
            "expect": "cover_empty_honest",
        },
        {
            "id": "Q6",
            "scene": "tilingkey / alias",
            "question": "BOOL 别名 IsTnd=true 能否对上 0/1？",
            "argv": {"pattern": "IsTnd=true"},
            "expect": "cover_combo",
        },
        {
            "id": "Q7",
            "scene": "tilingkey / name",
            "question": "InputDType 是什么、谁写？",
            "argv": {"pattern": "InputDType"},
            "expect": "name_located",
            "need_writers": True,
        },
        {
            "id": "Q8",
            "scene": "tilingkey / name",
            "question": "S1TemplateNum 定义和 packing 在哪？",
            "argv": {"pattern": "S1TemplateNum"},
            "expect": "name_located",
            "need_writers": True,
        },
        {
            "id": "Q9",
            "scene": "tilingdata",
            "question": "s1Inner 谁写谁读？",
            "argv": {"pattern": "s1Inner"},
            "expect": "name_located",
            "need_writers": True,
            "need_readers": True,
        },
        {
            "id": "Q10",
            "scene": "tilingdata",
            "question": "tilingData / TilingData 结构在哪？",
            "argv": {"pattern": "tilingData"},
            "expect": "name_located",
        },
        {
            "id": "Q11",
            "scene": "host / api",
            "question": "keep_prob 这个属性登记在哪？",
            "argv": {"pattern": "keep_prob"},
            "expect": "name_located",
        },
        {
            "id": "Q12",
            "scene": "host / kernel",
            "question": "Init 定义体在哪？",
            "argv": {"pattern": "Init"},
            "expect": "name_located",
        },
        {
            "id": "Q13",
            "scene": "host / kernel",
            "question": "Process 定义体在哪？",
            "argv": {"pattern": "Process"},
            "expect": "name_located",
        },
        {
            "id": "Q14",
            "scene": "sync / pipe",
            "question": "pipeBase 对应哪段 launch？",
            "argv": {"pattern": "pipeBase"},
            "expect": "name_located",
        },
        {
            "id": "Q15",
            "scene": "sync / pipe",
            "question": "pipePost 对应哪段 launch？",
            "argv": {"pattern": "pipePost"},
            "expect": "name_located",
        },
        {
            "id": "Q16",
            "scene": "buffer / catalog",
            "question": "LocalTensor 类型根（应空，跟实例名）",
            "argv": {"pattern": "LocalTensor"},
            "expect": "catalog_empty",
        },
        {
            "id": "Q17",
            "scene": "buffer / catalog",
            "question": "TQue 类型根（应空）",
            "argv": {"pattern": "TQue"},
            "expect": "catalog_empty",
        },
        {
            "id": "Q18",
            "scene": "template / macro",
            "question": "ASCENDC_TPL_ARGS_DECL 登记点在哪？",
            "argv": {"pattern": "ASCENDC_TPL_ARGS_DECL"},
            "expect": "name_located",
        },
        {
            "id": "Q19",
            "scene": "template / macro",
            "question": "GET_TPL_TILING_KEY packing 入口在哪？",
            "argv": {"pattern": "GET_TPL_TILING_KEY"},
            "expect": "name_located",
        },
        {
            "id": "Q20",
            "scene": "host / refuse",
            "question": "GRAPH_FAILED 是不是 Host 拒单入口？",
            "argv": {"pattern": "GRAPH_FAILED"},
            "expect": "name_located",
        },
        {
            "id": "Q21",
            "scene": "host / check",
            "question": "CheckShapeValid 定义窗够不够读？",
            "argv": {"pattern": "CheckShapeValid"},
            "expect": "name_located",
        },
        {
            "id": "Q22",
            "scene": "nl refuse",
            "question": "自然语言整句（应拒绝当结构化命中）",
            "argv": {"pattern": "who writes s1Inner in the kernel"},
            "expect": "refuse_nl",
        },
    ]

    q = open_query(FAG, architecture=ARCH)
    rows: list[dict[str, Any]] = []
    try:
        index = q.agent_query()
        phase = (index.get("phases") or [{}])[0]
        around_file = str(phase.get("file") or "")
        around_line = int(phase.get("line") or 0)
        cases.append(
            {
                "id": "Q23",
                "scene": "around / launch",
                "question": "从索引第一段 launch 位点扩邻居",
                "argv": {"file": around_file, "line": around_line},
                "expect": "around",
            }
        )
        keep = q.agent_query(pattern="keep_prob")
        kcard = _first_card(keep)
        if kcard.get("file") and kcard.get("line"):
            cases.append(
                {
                    "id": "Q24",
                    "scene": "around / attr",
                    "question": "从 keep_prob 卡片位点扩 1 跳邻居",
                    "argv": {
                        "file": str(kcard.get("file") or ""),
                        "line": int(kcard.get("line") or 0),
                    },
                    "expect": "around",
                }
            )

        for case in cases:
            t0 = time.perf_counter()
            payload = q.agent_query(**case["argv"])
            ms = round((time.perf_counter() - t0) * 1000, 1)
            bytes_n, tokens = _size(payload)
            judged = judge(case, payload, bytes_n)
            rows.append(
                {
                    "id": case["id"],
                    "scene": case["scene"],
                    "question": case["question"],
                    "argv": case["argv"],
                    "ms": ms,
                    "bytes": bytes_n,
                    "tokens": tokens,
                    **judged,
                }
            )
            print(
                f"{case['id']} {judged['grade']:8} {bytes_n:5}B ~{tokens:4}tok "
                f"{ms:7.1f}ms {judged['shape']:8} {judged['notes']}",
                flush=True,
            )
    finally:
        q.close()

    grades = {g: sum(1 for r in rows if r["grade"] == g) for g in ("usable", "partial", "weak", "fail")}
    summary = {
        "op": "flash_attention_score_grad",
        "arch": ARCH,
        "n": len(rows),
        "avg_bytes": int(sum(r["bytes"] for r in rows) / max(len(rows), 1)),
        "avg_tokens": int(sum(r["tokens"] for r in rows) / max(len(rows), 1)),
        "p50_bytes": sorted(r["bytes"] for r in rows)[len(rows) // 2],
        "max_bytes": max(r["bytes"] for r in rows),
        "max_tokens": max(r["tokens"] for r in rows),
        "p50_ms": sorted(r["ms"] for r in rows)[len(rows) // 2],
        "max_ms": max(r["ms"] for r in rows),
        "grades": grades,
        "cap_bytes": 24000,
        "cap_tokens": 6000,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
