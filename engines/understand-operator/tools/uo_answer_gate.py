#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Answer-equivalence gate for the uo product.

A refactor is free to change how the graph is represented -- entity ids, node
granularity, interned attributes, relation counts -- as long as an Agent asking
the same question still gets the same answer. This gate freezes the *answers*
and diffs them, so representation churn does not read as a regression and a real
answer change cannot hide behind it.

Deliberately compared: cover counts, dim domains, alias targets, locate
file:line, launch pipe names and order, honest-empty staying empty.
Deliberately ignored: entity ids, relation totals, extra neighbours, payload
size, snippet whitespace, wall-clock.

    freeze:  uo_answer_gate.py --op <dir> --arch arch35 --freeze
    check:   uo_answer_gate.py --op <dir> --arch arch35
"""
from __future__ import annotations

import argparse
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

#: Lives under the tracked baselines directory on purpose. The golden used to
#: sit in ``artifacts/``, which ``.gitignore`` excludes, so it never reached the
#: repository: a new machine could only re-freeze against whatever state it
#: found, and the gate degraded from "answers did not change" to "answers match
#: my own last run". Committing it is what connects a check to the answers the
#: optimisation started from.
DEFAULT_GOLDEN = (
    REPO
    / "engines"
    / "understand-operator"
    / "tests"
    / "baselines"
    / "flash_attention_score_grad.arch35.answers.json"
)


def source_digest(op: Path, arch: str) -> dict[str, Any]:
    """Identify the sources the answers were frozen against.

    The golden pins answers, and an answer is only meaningful about a particular
    operator checkout. Freeze on one checkout, check on another, and every case
    diffs at once -- which reads like 53 regressions instead of "this golden is
    about different code". Recording what was read lets the check say which of
    the two it is.

    ``confirmed_sources`` is the file list extract already settled on, so this
    follows the build's own notion of scope rather than re-deriving one.
    """
    import hashlib

    import yaml

    manifest = op / ".ascendc-pilot" / arch / "uo" / "cache" / "extract_fingerprint.yaml"
    try:
        loaded = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {"available": False}
    rows = loaded.get("confirmed_sources") if isinstance(loaded, dict) else None
    if not isinstance(rows, list):
        return {"available": False}
    digest = hashlib.sha256()
    counted = 0
    for rel in sorted(str(r) for r in rows):
        path = op / rel
        try:
            body = path.read_bytes()
        except OSError:
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(hashlib.sha256(body).digest())
        counted += 1
    return {"available": True, "file_count": counted, "digest": digest.hexdigest()[:16]}


def _tail_path(value: Any, keep: int = 2) -> str:
    """Last ``keep`` path components, so absolute-path spelling cannot fail the gate."""
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return ""
    parts = [p for p in text.split("/") if p]
    return "/".join(parts[-keep:])


def _cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("cards", "phases", "seeds"):
        rows = payload.get(key)
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
    return []


def _first_card(payload: dict[str, Any]) -> dict[str, Any]:
    rows = _cards(payload)
    return rows[0] if rows else {}


def _span(card: dict[str, Any]) -> str:
    span = card.get("definition_span") if isinstance(card.get("definition_span"), dict) else {}
    file = _tail_path(card.get("file") or span.get("file"))
    line = int(card.get("line") or card.get("line_start") or span.get("line_start") or 0)
    return f"{file}:{line}" if file and line else ""


def _names(rows: Any) -> list[str]:
    """Sorted unique display names. Dedup upstream must not shift this set."""
    out: set[str] = set()
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                name = row.get("name") or row.get("symbol") or row.get("function") or ""
            else:
                name = row
            text = str(name or "").strip()
            if text:
                out.add(text)
    return sorted(out)


def _norm_nearby(rows: Any) -> list[Any]:
    """Normalise cover ``nearby`` rows.

    These arrive as dicts whose ``values`` come out of a set, so their order is
    not stable across runs; stringifying them wholesale would make the gate
    fail at random. Sort the values and keep only the identifying fields.
    """
    out: list[Any] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            out.append(
                {
                    "dropped": str(row.get("dropped") or ""),
                    "matching_block_count": int(row.get("matching_block_count") or 0),
                    "values": sorted(str(v) for v in (row.get("values") or [])),
                }
            )
        else:
            out.append(str(row))
    return sorted(out, key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))


def answer_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce a query payload to the facts an Agent would act on."""
    card = _first_card(payload)
    extras = card.get("extras") if isinstance(card.get("extras"), dict) else {}
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    dim_cov = payload.get("dim_coverage") if isinstance(payload.get("dim_coverage"), dict) else {}

    facts: dict[str, Any] = {
        "shape": str(payload.get("shape") or ""),
        "ok": bool(payload.get("ok")),
        "card_count": len(_cards(payload)),
        "primary": {
            "kind": str(card.get("kind") or card.get("phase") or ""),
            "name": str(card.get("name") or card.get("pipe") or ""),
            "span": _span(card),
        },
        "has_snippet": bool(str(card.get("snippet") or "").strip()),
        "writers": _names(extras.get("writers")),
        "readers": _names(extras.get("readers")),
        "canonical": str(extras.get("canonical") or card.get("canonical") or ""),
        "matching_block_count": int(payload.get("matching_block_count") or 0),
        "completeness": str(coverage.get("completeness") or ""),
        "dim_coverage": {k: sorted(str(x) for x in (v or [])) for k, v in sorted(dim_cov.items())},
        "nearby": _norm_nearby(coverage.get("nearby") or payload.get("nearby")),
        "has_hint": bool(str(payload.get("hint") or "").strip()),
    }
    # The launch index is an ordered answer: pipe order is part of the fact.
    if payload.get("phases"):
        facts["phases"] = [
            {"name": str(p.get("pipe") or p.get("name") or ""), "span": _span(p)}
            for p in _cards(payload)
        ]
        facts["dim_names"] = sorted(str(d) for d in (payload.get("dim_names") or []))
    return facts


def build_cases() -> list[dict[str, Any]]:
    """Probe Q1-Q22 plus the exam identifiers that pin FAG graph facts."""
    probe: list[tuple[str, dict[str, Any]]] = [
        ("Q1_index", {}),
        ("Q2_dim_istnd", {"pattern": "Dim=IsTnd"}),
        ("Q3_istnd_1", {"pattern": "IsTnd=1"}),
        ("Q4_istnd_s2", {"pattern": "IsTnd=1,S2TemplateNum=1"}),
        ("Q5_istnd_9_empty", {"pattern": "IsTnd=9"}),
        ("Q6_istnd_true_alias", {"pattern": "IsTnd=true"}),
        ("Q7_inputdtype", {"pattern": "InputDType"}),
        ("Q8_s1templatenum", {"pattern": "S1TemplateNum"}),
        ("Q9_s1inner", {"pattern": "s1Inner"}),
        ("Q10_tilingdata", {"pattern": "tilingData"}),
        ("Q11_keep_prob", {"pattern": "keep_prob"}),
        ("Q12_init", {"pattern": "Init"}),
        ("Q13_process", {"pattern": "Process"}),
        ("Q14_pipebase", {"pattern": "pipeBase"}),
        ("Q15_pipepost", {"pattern": "pipePost"}),
        ("Q16_localtensor_catalog", {"pattern": "LocalTensor"}),
        ("Q17_tque_catalog", {"pattern": "TQue"}),
        ("Q18_tpl_args_decl", {"pattern": "ASCENDC_TPL_ARGS_DECL"}),
        ("Q19_get_tpl_key", {"pattern": "GET_TPL_TILING_KEY"}),
        ("Q20_graph_failed", {"pattern": "GRAPH_FAILED"}),
        ("Q21_checkshapevalid", {"pattern": "CheckShapeValid"}),
        ("Q22_refuse_nl", {"pattern": "who writes s1Inner in the kernel"}),
    ]
    # Exam set: the only place that pins matching_block_count==7, the
    # fusedOuter->blockOuter alias, and the D=320 nearby ladder.
    exam: list[tuple[str, dict[str, Any]]] = [
        ("E1_dtpl128_combo", {"pattern": "DTemplateNum=128,DeterType=0,InputDType=3"}),
        ("E2_dtpl320_empty", {"pattern": "DTemplateNum=320"}),
        ("E3_dtpl1_empty", {"pattern": "DTemplateNum=1"}),
        ("E4_fusedouter_alias", {"pattern": "fusedOuter"}),
        ("E5_splitaxis_istnd", {"pattern": "SplitAxis=1,IsTnd=1"}),
        ("E6_ispse", {"pattern": "IsPse"}),
        ("E7_ispse_1", {"pattern": "IsPse=1"}),
        ("E8_calcle_tnd_deter", {"pattern": "CalcleTNDDeterParam"}),
        ("E9_reg_tiling_default", {"pattern": "REGISTER_TILING_DEFAULT"}),
        ("E10_reg_tiling_template", {"pattern": "REGISTER_TILING_TEMPLATE"}),
        ("E11_setschedulemode", {"pattern": "SetScheduleMode"}),
        ("E12_syncallcores", {"pattern": "SyncALLCores"}),
        ("E13_mutexbuffer", {"pattern": "MutexBuffer"}),
        ("E14_processdqkv", {"pattern": "ProcessDqkv"}),
        ("E15_processmulscast", {"pattern": "ProcessMulsAndCast"}),
        ("E16_cast", {"pattern": "Cast"}),
        ("E17_tpl_sel", {"pattern": "ASCENDC_TPL_SEL"}),
        ("E18_orig_dtype_query", {"pattern": "ORIG_DTYPE_QUERY"}),
        ("E19_isdnoequal", {"pattern": "IsDNoEqual"}),
        ("E20_isnzout", {"pattern": "IsNzOut"}),
        ("E21_splitaxis", {"pattern": "splitAxis"}),
        ("E22_scalevalue", {"pattern": "scaleValue"}),
        ("E23_enablepresfmg", {"pattern": "enablePreSfmg"}),
        ("E24_small_d_preload", {"pattern": "IS_SMALL_D_PRELOAD"}),
        ("E25_opcheckif", {"pattern": "OP_CHECK_IF"}),
        ("E26_checkvarlensparse", {"pattern": "CheckVarLenSparseModeValue"}),
        ("E27_graphstatus", {"pattern": "graphStatus"}),
        ("E28_inittilingdata", {"pattern": "InitTilingData"}),
        ("E29_fag_tilingdata", {"pattern": "FlashAttentionScoreGradTilingData"}),
        ("E30_regtensor", {"pattern": "RegTensor"}),
        ("E31_vregsrc", {"pattern": "vregSrc"}),
        ("E32_tpl_3_bw", {"pattern": "ASCENDC_TPL_3_BW"}),
        ("E33_reg_tpl_varlen", {"pattern": "REGISTER_TILING_TEMPLATE_FlashAttentionScoreGradTilingVarlenRegbase"}),
        ("E34_scale_value_attr", {"pattern": "scale_value"}),
        ("E35_pse_type", {"pattern": "pse_type"}),
    ]
    return [{"id": cid, "argv": argv} for cid, argv in probe + exam]


def collect(op: Path, arch: str) -> dict[str, Any]:
    from uo_init.uo_query import open_query

    q = open_query(op, architecture=arch)
    rows: dict[str, Any] = {}
    timings: dict[str, float] = {}
    try:
        cases = build_cases()
        # Two around-hops are seeded from live answers, so they follow the
        # graph instead of hardcoding a line that a re-extract may move.
        try:
            index = q.agent_query()
            phase = (_cards(index) or [{}])[0]
            if phase.get("file") and phase.get("line"):
                cases.append(
                    {
                        "id": "Q23_around_launch",
                        "argv": {"file": str(phase["file"]), "line": int(phase["line"])},
                    }
                )
            keep = _first_card(q.agent_query(pattern="keep_prob"))
            if keep.get("file") and keep.get("line"):
                cases.append(
                    {
                        "id": "Q24_around_keep_prob",
                        "argv": {"file": str(keep["file"]), "line": int(keep["line"])},
                    }
                )
        except Exception as exc:  # noqa: BLE001
            rows["_seed_error"] = {"error": str(exc)[:200]}

        for case in cases:
            cid = case["id"]
            t0 = time.perf_counter()
            try:
                payload = q.agent_query(**case["argv"])
            except Exception as exc:  # noqa: BLE001
                timings[cid] = round((time.perf_counter() - t0) * 1000, 1)
                rows[cid] = {"query_error": str(exc)[:200]}
                continue
            timings[cid] = round((time.perf_counter() - t0) * 1000, 1)
            rows[cid] = answer_facts(payload)
    finally:
        q.close()

    ms = sorted(timings.values())
    return {
        "schema": "uo-answer-gate/v1",
        "arch": arch,
        "source": source_digest(op, arch),
        "answers": rows,
        "latency_ms": {
            "n": len(ms),
            "p50": ms[len(ms) // 2] if ms else 0,
            "p95": ms[max(0, int(len(ms) * 0.95) - 1)] if ms else 0,
            "max": ms[-1] if ms else 0,
            "mean": round(sum(ms) / len(ms), 1) if ms else 0,
            "per_case": timings,
        },
    }


def _walk_diff(path: str, gold: Any, new: Any, out: list[str]) -> None:
    if isinstance(gold, dict) and isinstance(new, dict):
        for key in sorted(set(gold) | set(new)):
            if key not in gold:
                out.append(f"{path}.{key}: ADDED {json.dumps(new[key], ensure_ascii=False)[:120]}")
            elif key not in new:
                out.append(f"{path}.{key}: REMOVED {json.dumps(gold[key], ensure_ascii=False)[:120]}")
            else:
                _walk_diff(f"{path}.{key}", gold[key], new[key], out)
        return
    if gold != new:
        out.append(
            f"{path}: {json.dumps(gold, ensure_ascii=False)[:100]}"
            f"  ->  {json.dumps(new, ensure_ascii=False)[:100]}"
        )


def compare(gold: dict[str, Any], new: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    g = gold.get("answers") or {}
    n = new.get("answers") or {}
    for cid in sorted(set(g) | set(n)):
        if cid not in g:
            diffs.append(f"{cid}: case ADDED (re-freeze if intended)")
        elif cid not in n:
            diffs.append(f"{cid}: case MISSING from this run")
        else:
            _walk_diff(cid, g[cid], n[cid], diffs)
    return diffs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="uo answer-equivalence gate")
    parser.add_argument("--op", type=Path, required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--freeze", action="store_true", help="write the golden instead of checking")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.op.is_dir():
        print(f"operator not found: {args.op}", flush=True)
        return 2

    current = collect(args.op, args.arch)
    lat = current["latency_ms"]
    errors = sorted(k for k, v in current["answers"].items() if isinstance(v, dict) and "query_error" in v)
    print(
        f"cases={lat['n']} latency mean={lat['mean']}ms p50={lat['p50']}ms "
        f"p95={lat['p95']}ms max={lat['max']}ms errors={len(errors)}",
        flush=True,
    )
    for cid in errors:
        print(f"  QUERY ERROR {cid}: {current['answers'][cid]['query_error']}", flush=True)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"wrote report {args.report}", flush=True)

    if args.freeze:
        args.golden.parent.mkdir(parents=True, exist_ok=True)
        args.golden.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"froze golden {args.golden}", flush=True)
        return 0

    if not args.golden.is_file():
        print(f"golden missing: {args.golden} (run --freeze first)", flush=True)
        return 2

    gold = json.loads(args.golden.read_text(encoding="utf-8"))
    gold_src = gold.get("source") if isinstance(gold.get("source"), dict) else {}
    cur_src = current.get("source") if isinstance(current.get("source"), dict) else {}
    if gold_src.get("digest") and cur_src.get("digest") != gold_src.get("digest"):
        print(
            "NOTE: golden was frozen against different operator sources "
            f"({gold_src.get('digest')}/{gold_src.get('file_count')} files vs "
            f"{cur_src.get('digest')}/{cur_src.get('file_count')} files). "
            "Diffs below may describe the source change, not a regression.",
            flush=True,
        )
    diffs = compare(gold, current)
    if not diffs:
        print("ANSWER GATE PASS: no answer changed", flush=True)
        return 0
    print(f"ANSWER GATE FAIL: {len(diffs)} answer diffs", flush=True)
    for line in diffs[:60]:
        print(f"  {line}", flush=True)
    if len(diffs) > 60:
        print(f"  ... {len(diffs) - 60} more", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
