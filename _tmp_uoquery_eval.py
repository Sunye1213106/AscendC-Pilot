# -*- coding: utf-8 -*-
"""Run uo-query battery using the same 4 morphologies as skills/uo-query."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOTS = [
    Path(r"d:\TEST\AscendC-Pilot\engines\understand-operator\src"),
    Path(r"d:\TEST\AscendC-Pilot\engines\common"),
    Path(r"d:\TEST\AscendC-Pilot\pilot"),
]
for p in ROOTS:
    sys.path.insert(0, str(p))

from uo_init.uo_query import open_query  # noqa: E402

OUT = Path(r"d:\TEST\AscendC-Pilot\_tmp_uoquery_eval.json")

OPS = [
    {
        "id": "FAG",
        "label": "FlashAttentionScoreGrad",
        "project": Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
        "arch": "arch35",
        "family": "FlashAttention",
        "uo_mb": 33.6,
    },
    {
        "id": "IFA",
        "label": "IncreFlashAttention",
        "project": Path(r"d:\TEST\ops-transformer\attention\incre_flash_attention"),
        "arch": "arch35",
        "family": "FlashAttention-decode",
        "uo_mb": 53.8,
    },
    {
        "id": "GMM",
        "label": "GroupedMatmul",
        "project": Path(r"d:\TEST\ops-transformer\gmm\grouped_matmul"),
        "arch": "arch35",
        "family": "MatMul",
        "uo_mb": None,
    },
    {
        "id": "NSA",
        "label": "NsaCompress",
        "project": Path(r"d:\TEST\ops-transformer\attention\nsa_compress"),
        "arch": "arch35",
        "family": "Attention-aux",
        "uo_mb": 1.4,
    },
]


def payload_bytes(payload: dict) -> int:
    raw = json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))
    return len(raw.encode("utf-8"))


def card_brief(card: dict) -> dict:
    extras = card.get("extras") if isinstance(card.get("extras"), dict) else {}
    edges = card.get("edges") if isinstance(card.get("edges"), dict) else {}
    writers = extras.get("writers") or []
    readers = extras.get("readers") or []
    snippet = str(card.get("snippet") or extras.get("definition") or "")
    return {
        "kind": card.get("kind"),
        "name": card.get("name"),
        "file": card.get("file"),
        "line": card.get("line") or card.get("line_start"),
        "edge_kinds": sorted(edges.keys()),
        "writers": len(writers) if isinstance(writers, list) else writers,
        "readers": len(readers) if isinstance(readers, list) else readers,
        "snippet_len": len(snippet),
        "snippet_head": snippet.replace("\n", " ")[:160],
    }


def summarize(payload: dict) -> dict:
    s: dict = {
        "ok": payload.get("ok"),
        "shape": payload.get("shape"),
        "bytes": payload_bytes(payload),
        "count": payload.get("count"),
        "error": payload.get("error"),
        "hint": str(payload.get("hint") or "")[:280],
        "canonical": payload.get("canonical"),
        "next": (payload.get("next") or [])[:10] if isinstance(payload.get("next"), list) else payload.get("next"),
        "truncated": payload.get("truncated"),
    }
    shape = payload.get("shape")
    if shape == "index":
        dims = list(payload.get("dim_names") or [])
        tds = list(payload.get("tiling_data_names") or [])
        phases = payload.get("phases") or []
        s["dim_count"] = len(dims)
        s["dims_head"] = dims[:20]
        s["tiling_data"] = tds[:12]
        s["phases"] = [
            {
                "pipe": r.get("pipe"),
                "phase": r.get("phase"),
                "file": r.get("file"),
                "line": r.get("line"),
            }
            for r in phases[:8]
        ]
        s["entry"] = payload.get("entry")
        s["gaps_count"] = payload.get("gaps_count")
        s["coverage_keys"] = sorted((payload.get("coverage") or {}).keys())
    elif shape == "cover":
        dc = payload.get("dim_coverage") or {}
        s["matching_block_count"] = payload.get("matching_block_count") or payload.get("total_matched")
        s["template_block_count"] = len(payload.get("template_blocks") or [])
        s["dim_coverage_lens"] = {
            k: (len(v) if isinstance(v, list) else 1) for k, v in dc.items()
        }
        s["dim_coverage_head"] = {
            k: (v[:12] if isinstance(v, list) else v) for k, v in list(dc.items())[:12]
        }
        s["has_keys"] = bool(payload.get("keys") or payload.get("legal_keys"))
    elif shape == "name":
        cards = payload.get("cards") or []
        s["card_kinds"] = [c.get("kind") for c in cards]
        s["cards"] = [card_brief(c) for c in cards[:6]]
    elif shape == "around":
        seeds = payload.get("seeds") or payload.get("hits") or []
        neigh = payload.get("neighbors") or []
        s["seed_count"] = len(seeds)
        s["neighbor_count"] = len(neigh) if isinstance(neigh, list) else (
            sum(len(v) for v in neigh.values()) if isinstance(neigh, dict) else None
        )
        s["seeds"] = [
            {
                "kind": r.get("kind"),
                "name": r.get("name"),
                "file": r.get("file"),
                "line": r.get("line") or r.get("line_start"),
            }
            for r in seeds[:8]
        ]
        if isinstance(neigh, list):
            s["neighbors_head"] = [
                {"kind": r.get("kind"), "name": r.get("name"), "rel": r.get("rel") or r.get("type")}
                for r in neigh[:8]
            ]
        elif isinstance(neigh, dict):
            s["neighbor_kinds"] = {k: len(v) if isinstance(v, list) else 1 for k, v in neigh.items()}
    return s


def run_one(q, argv: dict) -> dict:
    t0 = time.perf_counter()
    payload = q.agent_query(
        pattern=str(argv.get("pattern") or ""),
        file=str(argv.get("file") or ""),
        line=int(argv.get("line") or 0),
        limit=int(argv.get("limit") or 8),
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    summary = summarize(payload)
    summary["elapsed_ms"] = elapsed_ms
    return summary, payload


def main() -> None:
    report: dict = {"ops": {}, "queries": []}
    handles = {}
    for op in OPS:
        t0 = time.perf_counter()
        q = open_query(op["project"], architecture=op["arch"])
        handles[op["id"]] = q
        report["ops"][op["id"]] = {
            **{k: v for k, v in op.items() if k != "project"},
            "project": str(op["project"]),
            "open_ms": int((time.perf_counter() - t0) * 1000),
            "product": str(getattr(q, "product", "")),
        }

    # ---- Round 1: index every op ----
    indexes = {}
    for op in OPS:
        oid = op["id"]
        summary, payload = run_one(handles[oid], {"pattern": ""})
        indexes[oid] = payload
        report["queries"].append(
            {
                "qid": f"{oid}-Q1-index",
                "op": oid,
                "scenario": "tiling-design N10 / runtime-debug 多阶段 launch：从哪开始",
                "morph": "index",
                "argv": "uo-query --project <op> --architecture arch35",
                "summary": summary,
            }
        )

    # ---- Designed follow-ups per cannbot scenario ----
    planned = [
        # FAG
        {
            "qid": "FAG-Q2-dim-IsTnd",
            "op": "FAG",
            "scenario": "whitebox / tiling-design 分支覆盖：IsTnd 合法值",
            "morph": "Dim=<维名>",
            "argv": "Dim=IsTnd",
            "pattern": "Dim=IsTnd",
        },
        {
            "qid": "FAG-Q3a-IsTnd-true",
            "op": "FAG",
            "scenario": "kernel_binary_debug 561003：开发者按 C++ bool 写 IsTnd=true",
            "morph": "Name=Value",
            "argv": "IsTnd=true",
            "pattern": "IsTnd=true",
        },
        {
            "qid": "FAG-Q3b-IsTnd-1",
            "op": "FAG",
            "scenario": "kernel_binary_debug 561003：源码 SEL 实际是 0/1",
            "morph": "Name=Value",
            "argv": "IsTnd=1",
            "pattern": "IsTnd=1",
        },
        {
            "qid": "FAG-Q3c-Dim-IsTnd-true",
            "op": "FAG",
            "scenario": "历史写法 Dim=IsTnd=true 被剥成 combo",
            "morph": "Name=Value (Dim=剥前缀)",
            "argv": "Dim=IsTnd=true",
            "pattern": "Dim=IsTnd=true",
        },
        {
            "qid": "FAG-Q4-s1Inner",
            "op": "FAG",
            "scenario": "tiling-design N9 / 561002：Tiling 字段谁写谁读",
            "morph": "identifier",
            "argv": "s1Inner",
            "pattern": "s1Inner",
        },
        {
            "qid": "FAG-Q6-EnQue",
            "op": "FAG",
            "scenario": "crash-debug：卡死查 EnQue/DeQue 配对（skill 声明配对不在 UO）",
            "morph": "identifier",
            "argv": "EnQue",
            "pattern": "EnQue",
        },
        {
            "qid": "FAG-Q7-SetScheduleMode",
            "op": "FAG",
            "scenario": "crash-debug hang：PostTiling SetScheduleMode",
            "morph": "identifier",
            "argv": "SetScheduleMode",
            "pattern": "SetScheduleMode",
        },
        {
            "qid": "FAG-Q8-DTemplateNum",
            "op": "FAG",
            "scenario": "whitebox 参数枚举 + 561003 D 维砍组合",
            "morph": "Dim=<维名>",
            "argv": "Dim=DTemplateNum",
            "pattern": "Dim=DTemplateNum",
        },
        {
            "qid": "FAG-Q9-combo-d80",
            "op": "FAG",
            "scenario": "runtime-debug 561003：FP16 D=80 dropout 能否编过",
            "morph": "Name=Value combo",
            "argv": "DTemplateNum=80,InputDType=1",
            "pattern": "DTemplateNum=80,InputDType=1",
        },
        {
            "qid": "FAG-Q10-CrossCoreWaitFlag",
            "op": "FAG",
            "scenario": "crash-debug AIV 卡死：CrossCoreWaitFlag",
            "morph": "identifier",
            "argv": "CrossCoreWaitFlag",
            "pattern": "CrossCoreWaitFlag",
        },
        {
            "qid": "FAG-Q11-SoftmaxFlashV2",
            "op": "FAG",
            "scenario": "FA N4 precision：SoftmaxFlashV2 / isBasicBlock 一致性",
            "morph": "identifier",
            "argv": "SoftmaxFlashV2",
            "pattern": "SoftmaxFlashV2",
        },
        {
            "qid": "FAG-Q12-isBasicBlock",
            "op": "FAG",
            "scenario": "FA N4：isBasicBlock 模板参数",
            "morph": "identifier",
            "argv": "isBasicBlock",
            "pattern": "isBasicBlock",
        },
        # IFA — true/false encoding
        {
            "qid": "IFA-Q2-dim-HasAttenMask",
            "op": "IFA",
            "scenario": "FA feature_flags / 分支覆盖：HasAttenMask 合法集",
            "morph": "Dim=<维名>",
            "argv": "Dim=HasAttenMask",
            "pattern": "Dim=HasAttenMask",
        },
        {
            "qid": "IFA-Q3a-HasAttenMask-true",
            "op": "IFA",
            "scenario": "kernel_binary_debug：源码 BOOL_SEL 写的是 false,true",
            "morph": "Name=Value",
            "argv": "HasAttenMask=true",
            "pattern": "HasAttenMask=true",
        },
        {
            "qid": "IFA-Q3b-HasAttenMask-1",
            "op": "IFA",
            "scenario": "对照：用 0/1 习惯去查 IFA（源码是 true/false）",
            "morph": "Name=Value",
            "argv": "HasAttenMask=1",
            "pattern": "HasAttenMask=1",
        },
        {
            "qid": "IFA-Q4-batchSize",
            "op": "IFA",
            "scenario": "tiling-design N9：Host 写出的 batchSize 谁写谁读",
            "morph": "identifier",
            "argv": "batchSize",
            "pattern": "batchSize",
        },
        {
            "qid": "IFA-Q5-HasRope",
            "op": "IFA",
            "scenario": "FA specialization feature_flags：HasRope 能否编过",
            "morph": "Name=Value",
            "argv": "HasRope=true",
            "pattern": "HasRope=true",
        },
        {
            "qid": "IFA-Q6-scaleValue",
            "op": "IFA",
            "scenario": "FA N4 / precision：softmax scale 字段",
            "morph": "identifier",
            "argv": "scaleValue",
            "pattern": "scaleValue",
        },
        {
            "qid": "IFA-Q7-EnQue",
            "op": "IFA",
            "scenario": "crash-debug Buffer 配对（对照 FAG）",
            "morph": "identifier",
            "argv": "EnQue",
            "pattern": "EnQue",
        },
        # GMM
        {
            "qid": "GMM-Q2-dim-TRANS_B",
            "op": "GMM",
            "scenario": "matmul tiling / 分支覆盖：TRANS_B",
            "morph": "Dim=<维名>",
            "argv": "Dim=TRANS_B",
            "pattern": "Dim=TRANS_B",
        },
        {
            "qid": "GMM-Q3a-TRANS_B-true",
            "op": "GMM",
            "scenario": "561003：C++ bool 习惯 TRANS_B=true（源码 0/1）",
            "morph": "Name=Value",
            "argv": "TRANS_B=true",
            "pattern": "TRANS_B=true",
        },
        {
            "qid": "GMM-Q3b-TRANS_B-1",
            "op": "GMM",
            "scenario": "561003：源码 BOOL_SEL(TRANS_B, 0, 1)",
            "morph": "Name=Value",
            "argv": "TRANS_B=1",
            "pattern": "TRANS_B=1",
        },
        {
            "qid": "GMM-Q4-groupNum",
            "op": "GMM",
            "scenario": "tiling-design N9 / 561002：groupNum 谁写",
            "morph": "identifier",
            "argv": "groupNum",
            "pattern": "groupNum",
        },
        {
            "qid": "GMM-Q5-ubBaseK",
            "op": "GMM",
            "scenario": "tiling-design UB 切分：ubBaseK",
            "morph": "identifier",
            "argv": "ubBaseK",
            "pattern": "ubBaseK",
        },
        {
            "qid": "GMM-Q6-GMMTilingData",
            "op": "GMM",
            "scenario": "opParaSize / TilingData 结构体",
            "morph": "identifier",
            "argv": "GMMTilingData",
            "pattern": "GMMTilingData",
        },
        {
            "qid": "GMM-Q7-D_T_A",
            "op": "GMM",
            "scenario": "kernel_binary_debug 流程3：SEL dtype 条目 D_T_A",
            "morph": "Dim=<维名>",
            "argv": "Dim=D_T_A",
            "pattern": "Dim=D_T_A",
        },
        {
            "qid": "GMM-Q8-coreNum",
            "op": "GMM",
            "scenario": "tiling-design 多核切分：coreNum",
            "morph": "identifier",
            "argv": "coreNum",
            "pattern": "coreNum",
        },
        # NSA small graph
        {
            "qid": "NSA-Q2-first-dim",
            "op": "NSA",
            "scenario": "小图对照：第一维覆盖列表",
            "morph": "Dim=<维名>",
            "argv": None,
            "pattern": None,
        },
        {
            "qid": "NSA-Q3-td-first",
            "op": "NSA",
            "scenario": "小图对照：第一个 TilingData 名",
            "morph": "identifier",
            "argv": None,
            "pattern": None,
        },
    ]

    # fill NSA dynamic from index
    nsa_idx = indexes["NSA"]
    nsa_dims = list(nsa_idx.get("dim_names") or [])
    nsa_td = list(nsa_idx.get("tiling_data_names") or [])
    for item in planned:
        if item["qid"] == "NSA-Q2-first-dim":
            dim = nsa_dims[0] if nsa_dims else "DimX"
            item["argv"] = f"Dim={dim}"
            item["pattern"] = f"Dim={dim}"
        if item["qid"] == "NSA-Q3-td-first":
            name = nsa_td[0] if nsa_td else (nsa_idx.get("next") or ["TilingData"])[0]
            item["argv"] = str(name)
            item["pattern"] = str(name)

    around_sources = {}
    for item in planned:
        summary, payload = run_one(handles[item["op"]], {"pattern": item["pattern"]})
        report["queries"].append({**item, "summary": summary})
        if item["qid"] in {"FAG-Q4-s1Inner", "IFA-Q4-batchSize", "GMM-Q4-groupNum"}:
            cards = payload.get("cards") or []
            card = next((c for c in cards if c.get("file") and int(c.get("line") or 0) > 0), None)
            if card:
                around_sources[item["op"]] = {
                    "file": card.get("file"),
                    "line": int(card.get("line") or 0),
                    "from": item["qid"],
                    "name": card.get("name"),
                }

    # around from copied file:line
    around_plan = [
        ("FAG", "crash/code-review：从 s1Inner 写点扩 1 跳邻居"),
        ("IFA", "code-review：从 batchSize 写点扩邻居"),
        ("GMM", "code-review：从 groupNum 写点扩邻居"),
    ]
    for oid, scenario in around_plan:
        src = around_sources.get(oid)
        if not src:
            report["queries"].append(
                {
                    "qid": f"{oid}-Qaround-missing",
                    "op": oid,
                    "scenario": scenario,
                    "morph": "--file --line",
                    "argv": "(no card span)",
                    "summary": {"ok": False, "error": "no_span_from_identifier"},
                }
            )
            continue
        argv = {"file": src["file"], "line": src["line"]}
        summary, _ = run_one(handles[oid], argv)
        report["queries"].append(
            {
                "qid": f"{oid}-Qaround",
                "op": oid,
                "scenario": scenario,
                "morph": "--file --line",
                "argv": f"--file {src['file']} --line {src['line']}",
                "from_card": src,
                "summary": summary,
            }
        )

    # NSA around from its identifier if possible
    nsa_name_q = next(q for q in report["queries"] if q["qid"] == "NSA-Q3-td-first")
    nsa_cards = (nsa_name_q.get("summary") or {}).get("cards") or []
    nsa_card = next((c for c in nsa_cards if c.get("file") and int(c.get("line") or 0) > 0), None)
    if nsa_card:
        summary, _ = run_one(
            handles["NSA"], {"file": nsa_card["file"], "line": int(nsa_card["line"])}
        )
        report["queries"].append(
            {
                "qid": "NSA-Qaround",
                "op": "NSA",
                "scenario": "小图对照：从 TilingData 定义扩邻居",
                "morph": "--file --line",
                "argv": f"--file {nsa_card['file']} --line {nsa_card['line']}",
                "from_card": nsa_card,
                "summary": summary,
            }
        )

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sizes = [q["summary"].get("bytes") or 0 for q in report["queries"] if isinstance(q.get("summary"), dict)]
    print(f"wrote {OUT} queries={len(report['queries'])} min={min(sizes)} max={max(sizes)} median={sorted(sizes)[len(sizes)//2]}")
    for q in report["queries"]:
        s = q.get("summary") or {}
        print(
            f"{q['qid']:28} {s.get('shape','?'):7} {s.get('bytes',0):8}B  "
            f"count={s.get('count')} match={s.get('matching_block_count')} ok={s.get('ok')}"
        )


if __name__ == "__main__":
    main()
