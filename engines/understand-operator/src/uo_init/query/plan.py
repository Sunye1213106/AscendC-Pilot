# -*- coding: utf-8 -*-
"""Compile a natural-language uo-query into a QueryPlan.

The LLM must not invent the first identifier. This module maps symptoms onto
canonical modes/tokens and a differential answer contract.
"""
from __future__ import annotations

import re
from typing import Any

from uo_init.query.hints import identifier_tokens

MAX_SLICES = 5

_STOPWORDS = frozenset(
    {
        "if",
        "and",
        "for",
        "not",
        "the",
        "with",
        "from",
        "this",
        "that",
        "true",
        "false",
        "case",
        "host",
        "kernel",
        "shape",
        "test",
        "type",
        "fp16",
        "fp32",
        "bf16",
        "int32",
        "int8",
        "uint8",
        "arch35",
        "codemap",
        "ascendc",
        "tilingkey",
        "tiling",
        "pre",
        "main",
        "post",
        "core",
        "pipe",
        "pipein",
        "pipebase",
        "pipepost",
        "aic",
        "aiv",
        "vf",
        "ut",
        "dq",
        "dk",
        "dv",
        "dropout",
        "vendor",
        "msprof",
        "seq",
    }
)
_BUFF_TOKEN_RE = re.compile(r"\b(\d+[Bb]uff)\b")
_REGISTER_TOKEN_RE = re.compile(
    r"\bREGISTER_TILING_(?:DEFAULT|TEMPLATE(?:_WITH_ARCH)?)\b"
)

_UT_MARKERS = (
    "静默错",
    "补“一改",
    "补\"一改",
    "列 5 个",
    "列五个",
    "要补",
    "test_",
    "/ut/",
    "tests/ut",
)

_DIFF_MARKERS = (
    "精度",
    "dq",
    "dK",
    "dQ",
    "561003",
    "找不到 kernel",
    "kernel 找不到",
    "一进核",
    "hang",
    "卡死",
    "分核",
    "四个 AIC",
    "4 个 AIC",
    "确定性",
)

_MISSING_INPUTS = ("actual_seq", "aivNum", "TilingKey log", "shape")

# Keep in lockstep with skills/operator-analysis/capabilities/uo-query/METHOD.md
_SLICE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "slice_id": "sel",
        "focus": "kernel 找不到 / 561003 / 某维有没有编进 SEL",
        "first_mode": "template_match",
        "canonical": "dim_coverage",
        "keywords": (
            "561003",
            "kernel 找不到",
            "找不到 kernel",
            "找不到kernel",
            "ASCENDC_TPL_SEL",
            "TPL_SEL",
            "DTemplateNum",
            "没注册",
            "ORIG_DTYPE_QUERY",
            "IsNzOut",
            "IsDNoEqual",
        ),
    },
    {
        "slice_id": "locate",
        "focus": "同名函数 / virtual override / REGISTER_TILING 竞赛",
        "first_mode": "locate",
        "canonical": "",
        "keywords": (
            "virtual",
            "override",
            "同名",
            "CalcleTNDDeterParam",
            "REGISTER_TILING_TEMPLATE",
            "REGISTER_TILING_DEFAULT",
            "RegbaseFAG",
            "definition_sites",
            "IsCapable",
            "TND",
            "coreNum",
            "SetScheduleMode",
            "SyncALLCores",
            "一进核",
            "一进 kernel",
        ),
    },
    {
        "slice_id": "field",
        "focus": "分核 / 占核 / tiling 字段与其 local_aliases",
        "first_mode": "field",
        "canonical": "",
        "keywords": (
            "fusedOuter",
            "blockOuter",
            "blockFactor",
            "分核轴",
            "BN2GS1S2",
            "BN2S2",
            "只有 4 个 AIC",
            "只有四个 AIC",
            "四个 AIC",
            "4 个 AIC",
            "核占不满",
            "核数",
        ),
    },
    {
        "slice_id": "pipe",
        "focus": "Pre/Main/Post 三相 launch / PIPE / TPipe",
        "first_mode": "kernel_launch",
        "canonical": "",
        "keywords": (
            "Pre/Main/Post",
            "三相",
            "pipeIn",
            "pipeBase",
            "pipePost",
            "单 launch",
        ),
    },
    {
        "slice_id": "buffer",
        "focus": "3buff / 4buff / Policy* / L1 策略",
        "first_mode": "buffer",
        "canonical": "",
        "keywords": (
            "MutexBuffer",
            "MutexBuffersPolicy",
            "3buff",
            "4buff",
            "PolicyDB",
            "PolicySingleBuffer",
            "pL1Buf",
            "dSL1Buf",
            "等 AIV",
            "等 L1",
            "L1 dS",
        ),
    },
    {
        "slice_id": "flag",
        "focus": "HardEvent / CrossCore flag 是否复用",
        "first_mode": "locate",
        "canonical": "",
        "keywords": (
            "SYNC_DETER_FIX_FLAG",
            "SYNC_V2_TO_C1_FLAG",
            "BufferID",
            "CrossCore",
        ),
    },
)


def _keyword_hit(blob: str, lowered: str, key: str) -> bool:
    if not key:
        return False
    if key.isascii() and key.isalnum() and len(key) <= 5:
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])", blob, re.I) is not None
    return key.lower() in lowered or key in blob


def is_ut_authoring(question: str) -> bool:
    blob = str(question or "")
    if not blob.strip():
        return False
    hits = sum(1 for m in _UT_MARKERS if m in blob)
    return hits >= 2 or ("静默错" in blob) or ("tests/ut" in blob.replace("\\", "/"))


def is_differential_question(question: str) -> bool:
    blob = str(question or "")
    lowered = blob.lower()
    return any(_keyword_hit(blob, lowered, m) for m in _DIFF_MARKERS)


def _matched_slices(question: str) -> list[dict[str, str]]:
    blob = str(question or "")
    if not blob.strip() or is_ut_authoring(blob):
        return []
    lowered = blob.lower()
    hits: list[dict[str, str]] = []
    for row in _SLICE_CATALOG:
        matched = False
        for raw in row["keywords"]:
            if _keyword_hit(blob, lowered, str(raw)):
                matched = True
                break
        if not matched:
            continue
        hits.append(
            {
                "slice_id": str(row["slice_id"]),
                "focus": str(row["focus"]),
                "first_mode": str(row["first_mode"]),
                "canonical": str(row.get("canonical") or ""),
            }
        )
        if len(hits) >= MAX_SLICES:
            break
    return hits


def plan_query_slices(question: str) -> list[dict[str, str]]:
    """Return 2–5 METHOD slices, or empty when a single child is enough."""
    hits = _matched_slices(question)
    return hits if len(hits) >= 2 else []


def _cli(mode: str, pattern: str = "") -> str:
    cmd = f"acp uo-query --mode {mode}"
    if pattern:
        cmd += f" --query {pattern}"
    return cmd


def _question_idents(blob: str) -> list[str]:
    """Identifiers actually written in the question — never invented names."""
    out: list[str] = []
    seen: set[str] = set()
    for tok in identifier_tokens(blob):
        key = tok.lower()
        if key in _STOPWORDS or len(tok) < 3 or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _pattern_from_question(blob: str, mode: str, slice_id: str = "") -> str:
    """First-query token must occur in the question. Empty is a valid miss."""
    idents = _question_idents(blob)
    if mode in {"kernel_launch", "template_match"}:
        return ""
    if mode == "field":
        prefer = [
            tok
            for tok in idents
            if any(part in tok.lower() for part in ("outer", "fused", "factor", "split", "block"))
        ]
        return prefer[0] if prefer else ""
    if mode == "buffer":
        buff = _BUFF_TOKEN_RE.search(blob)
        if buff:
            return buff.group(1)
        for tok in idents:
            low = tok.lower()
            if "buff" in low or "policy" in low:
                return tok
        return ""
    if mode == "locate":
        registered = _REGISTER_TOKEN_RE.search(blob)
        if registered:
            return registered.group(0)
        if slice_id == "flag":
            for tok in idents:
                if (
                    "flag" in tok.lower()
                    or tok.startswith("SYNC_")
                    or tok in {"BufferID", "CrossCore"}
                ):
                    return tok
        if not idents:
            return ""
        return max(idents, key=lambda tok: (len(tok), tok))
    return idents[0] if idents else ""


def _first_queries(question: str, slices: list[dict[str, str]]) -> list[dict[str, str]]:
    blob = str(question or "")
    lowered = blob.lower()
    if is_ut_authoring(blob):
        return [
            {
                "mode": "locate",
                "pattern": "",
                "canonical": "",
                "cli": _cli("locate"),
            }
        ]
    if not slices:
        if "三相" in blob or "单 launch" in blob or "pipeIn" in blob:
            return [
                {
                    "mode": "kernel_launch",
                    "pattern": "",
                    "canonical": "",
                    "cli": _cli("kernel_launch"),
                }
            ]
        singles: list[dict[str, Any]] = []
        for row in _SLICE_CATALOG:
            if any(_keyword_hit(blob, lowered, str(k)) for k in row["keywords"]):
                singles.append(row)
                break
        if singles:
            row = singles[0]
            mode = str(row["first_mode"])
            pattern = _pattern_from_question(blob, mode, str(row.get("slice_id") or ""))
            return [
                {
                    "mode": mode,
                    "pattern": pattern,
                    "canonical": str(row.get("canonical") or ""),
                    "cli": _cli(mode, pattern),
                }
            ]
        return [
            {
                "mode": "locate",
                "pattern": "",
                "canonical": "",
                "cli": _cli("locate"),
            }
        ]
    out: list[dict[str, str]] = []
    for row in slices:
        mode = str(row.get("first_mode") or "locate")
        pattern = _pattern_from_question(blob, mode, str(row.get("slice_id") or ""))
        out.append(
            {
                "mode": mode,
                "pattern": pattern,
                "canonical": str(row.get("canonical") or ""),
                "cli": _cli(mode, pattern),
            }
        )
    return out


def compile_query(question: str, *, architecture: str = "") -> dict[str, Any]:
    """NL question → QueryPlan (modes, canonical tokens, answer contract)."""
    blob = str(question or "")
    slices = plan_query_slices(blob)
    matched = _matched_slices(blob)
    differential = is_differential_question(blob) and not is_ut_authoring(blob)
    first = _first_queries(blob, slices or matched[:1])
    contract = {
        "adequacy_default": "PARTIAL" if differential else "ANSWERED",
        "require_decision_tree": differential,
        "forbid": ["根因已定位"] if differential else [],
        "missing_inputs": list(_MISSING_INPUTS) if differential else [],
    }
    return {
        "ok": True,
        "mode": "compile",
        "question": blob,
        "architecture": architecture,
        "ut_authoring": is_ut_authoring(blob),
        "differential": differential,
        "answer_contract": contract,
        "first_query": first,
        "slices": slices,
        "forbidden_first_tokens": ["PRE_CORE_POST", "Process", "ProcessVec1", "ARGS_SEL"],
    }


def focused_user_question(original: str, slice_row: dict[str, str]) -> str:
    """Original question plus a hard FOCUS gate for one child Task."""
    sid = str(slice_row.get("slice_id") or "").strip() or "slice"
    focus = str(slice_row.get("focus") or "").strip()
    mode = str(slice_row.get("first_mode") or "").strip()
    canonical = str(slice_row.get("canonical") or "").strip()
    body = str(original or "").rstrip()
    first = _first_queries(body, [dict(slice_row)])
    cli = first[0]["cli"] if first else f"acp uo-query --mode {mode}"
    contract = compile_query(body).get("answer_contract") or {}
    forbid = "、".join(contract.get("forbid") or []) or "(none)"
    missing = ", ".join(contract.get("missing_inputs") or []) or "(none)"
    return (
        f"{body}\n"
        "\n"
        "---\n"
        f"SLICE_ID={sid}\n"
        f"FOCUS (this child only): {focus}\n"
        f"First mode: {mode}\n"
        f"Canonical token: {canonical or mode}\n"
        f"FIRST_QUERY: {cli}\n"
        "Run FIRST_QUERY as written. Do NOT invent PRE_CORE_POST / Process / "
        "the first ARGS_SEL block as the launch or coverage proof.\n"
        "Do not inherit hypotheses from other questions or slices.\n"
        f"Answer contract: adequacy_default={contract.get('adequacy_default')}; "
        f"decision_tree={'yes' if contract.get('require_decision_tree') else 'no'}; "
        f"forbidden={forbid}; missing_inputs={missing}.\n"
        "Answer ONLY this slice against the CodeMap. Ignore other parts of the "
        "original question. Do not claim facts outside this FOCUS. List-type "
        "answers need completeness siblings_checked or coverage_checked. "
        "Coverage envelope (sibling_files / dim_coverage) is the first page; "
        "snippets are an appendix.\n"
    )
