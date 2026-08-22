#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic FAG/arch35 uo-init performance + precision gate.

Cache modes are explicit: true-cold wipes ``.ascendc-pilot/<arch>``;
frontend-warm keeps TU/frontend cache; uo-update keeps the whole tree.
Wall-clock gates apply only to true-cold. Warm numbers are never success.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
DEFAULT_OP = Path(
    os.environ.get("UO_OP_DIR")
    or r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"
)
DEFAULT_IFA = Path(
    os.environ.get("UO_IFA_DIR")
    or r"d:\TEST\ops-transformer\attention\incre_flash_attention"
)
GOLD = REPO / "artifacts" / "uo-init-perf" / "gold" / "fag-arch35.yaml"
_CPP = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}

sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _pct_ok(actual: float, gold: float, pct: float) -> bool:
    if gold <= 0:
        return actual == gold
    return abs(actual - gold) <= (pct / 100.0) * gold


def _wipe(op: Path, arch: str, mode: str) -> None:
    arch_dir = op / ".ascendc-pilot" / arch
    if mode == "uo-update":
        return
    if mode == "true-cold":
        if arch_dir.exists():
            shutil.rmtree(arch_dir)
        return
    # frontend-warm: keep uo/cache (TU + frontend WalkResult), drop the rest.
    if not arch_dir.exists():
        return
    cache = arch_dir / "uo" / "cache"
    kept: Path | None = None
    if cache.is_dir():
        tmp = arch_dir.parent / f".{arch}.cache-keep"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(cache, tmp)
        kept = tmp
    shutil.rmtree(arch_dir)
    if kept is not None:
        (arch_dir / "uo").mkdir(parents=True, exist_ok=True)
        shutil.move(str(kept), str(arch_dir / "uo" / "cache"))


def _precision_from_quality(quality: dict[str, Any]) -> dict[str, Any]:
    graph = quality.get("graph") or {}
    surfaces = quality.get("surfaces") or {}
    tiling = surfaces.get("tiling_key") or {}
    apis = ((surfaces.get("kernel_api") or {}).get("apis") or {})
    api_reached = {
        name: int((row or {}).get("reached") or 0)
        for name, row in apis.items()
        if isinstance(row, dict)
    }
    unresolved = quality.get("unresolved") or {}
    other = int((graph.get("entities_by_kind") or {}).get("OTHER") or 0)
    return {
        "grade": quality.get("grade"),
        "integrity": quality.get("integrity"),
        "locate_ready": quality.get("locate_ready"),
        "locate_blocking": int(unresolved.get("locate_blocking") or 0),
        "other_count": other,
        "packing": str(tiling.get("packing") or ""),
        "tiling_key_coverage": str(tiling.get("coverage") or ""),
        "host_kernel": bool((surfaces.get("paths") or {}).get("host_kernel")),
        "tilingdata_kernel": bool((surfaces.get("paths") or {}).get("tilingdata_kernel")),
        "entity_count": int(graph.get("entity_count") or 0),
        "relation_count": int(graph.get("relation_count") or 0),
        "entities_by_kind": dict(graph.get("entities_by_kind") or {}),
        "relations_by_kind": dict(graph.get("relations_by_kind") or {}),
        "kernel_api": api_reached,
    }


def _enrich_from_product(precision: dict[str, Any], product: Path) -> dict[str, Any]:
    if not product.is_file():
        return precision
    try:
        from uo_init.ir.entity import EntityKind
        from uo_init.store.reader import read_codemap

        cm = read_codemap(product)
        precision["legal_keys"] = sorted({e.name for e in cm.by_kind(EntityKind.TILING_KEY)})
        precision["tiling_fields"] = sorted(
            {e.name for e in cm.by_kind(EntityKind.TILING_FIELD)}
        )
        krt = cm.meta.get("kernel_root_trace") or {}
        precision["gated_fill_complete"] = krt.get("gated_fill_complete")
        precision["budget_expired"] = krt.get("budget_expired")
        precision["kernel_root_trace_s"] = krt.get("elapsed_s")
    except Exception as exc:  # noqa: BLE001
        precision["product_error"] = f"{type(exc).__name__}: {exc}"
    return precision


def compare_gold(actual: dict[str, Any], gold: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    gq = gold.get("quality") or gold
    gg = gold.get("graph") or gold
    tol = gold.get("tolerance") or {}
    graph_pct = float(tol.get("graph_pct") or 3.0)
    kind_pct = float(tol.get("kind_pct") or 5.0)
    api_pct = float(tol.get("api_pct") or 3.0)

    if str(actual.get("grade")) != str(gq.get("grade") or "ready"):
        fails.append(f"grade {actual.get('grade')} != {gq.get('grade')}")
    if str(actual.get("integrity")) != str(gq.get("integrity") or "pass"):
        fails.append(f"integrity {actual.get('integrity')} != {gq.get('integrity')}")
    if int(actual.get("other_count") or 0) != int(gq.get("other_count") or 0):
        fails.append(f"OTHER {actual.get('other_count')} != {gq.get('other_count')}")
    if int(actual.get("locate_blocking") or 0) != int(gq.get("locate_blocking") or 0):
        fails.append(f"locate_blocking {actual.get('locate_blocking')}")
    packing = str(actual.get("packing") or "")
    if packing and packing != str(gq.get("packing") or packing):
        fails.append(f"packing {packing} != {gq.get('packing')}")
    if gq.get("host_kernel") is True and not actual.get("host_kernel"):
        fails.append("host_kernel is not true")
    if gq.get("tilingdata_kernel") is True and not actual.get("tilingdata_kernel"):
        fails.append("tilingdata_kernel is not true")
    if actual.get("gated_fill_complete") is False:
        fails.append("gated_fill_complete is false (truncated scan)")
    if actual.get("budget_expired") is True and actual.get("gated_fill_complete") is False:
        fails.append("budget_expired with incomplete gated fill")
    if not _pct_ok(
        float(actual.get("entity_count") or 0),
        float(gg.get("entity_count") or 0),
        graph_pct,
    ):
        fails.append(
            f"entity_count {actual.get('entity_count')} vs gold {gg.get('entity_count')} (±{graph_pct}%)"
        )
    if not _pct_ok(
        float(actual.get("relation_count") or 0),
        float(gg.get("relation_count") or 0),
        graph_pct,
    ):
        fails.append(
            f"relation_count {actual.get('relation_count')} vs gold {gg.get('relation_count')} (±{graph_pct}%)"
        )
    for kind, gold_n in (gg.get("entities_by_kind") or {}).items():
        got = int((actual.get("entities_by_kind") or {}).get(kind) or 0)
        if not _pct_ok(float(got), float(gold_n), kind_pct):
            fails.append(f"entities.{kind} {got} vs {gold_n} (±{kind_pct}%)")
    for kind, gold_n in (gg.get("relations_by_kind") or {}).items():
        got = int((actual.get("relations_by_kind") or {}).get(kind) or 0)
        if not _pct_ok(float(got), float(gold_n), kind_pct):
            fails.append(f"relations.{kind} {got} vs {gold_n} (±{kind_pct}%)")
    for name, gold_n in (gold.get("kernel_api") or {}).items():
        got = int((actual.get("kernel_api") or {}).get(name) or 0)
        if not _pct_ok(float(got), float(gold_n), api_pct):
            fails.append(f"kernel_api.{name} {got} vs {gold_n} (±{api_pct}%)")
    gold_keys = gold.get("legal_keys")
    if gold_keys:
        got_keys = set(actual.get("legal_keys") or [])
        want = set(gold_keys)
        if got_keys != want:
            fails.append(
                f"legal_keys mismatch extra={sorted(got_keys - want)} missing={sorted(want - got_keys)}"
            )
    gold_fields = gold.get("tiling_fields")
    if gold_fields:
        got_fields = set(actual.get("tiling_fields") or [])
        want = set(gold_fields)
        if got_fields != want:
            fails.append(
                f"tiling_fields mismatch extra={len(got_fields - want)} missing={len(want - got_fields)}"
            )
    return fails


def _hot_file_fails(perf: dict[str, Any], op: Path, max_reads: int = 2) -> list[str]:
    fails: list[str] = []
    root = str(op.resolve()).replace("\\", "/").lower()
    files = perf.get("files") or {}
    for path, row in files.items():
        n = int((row or {}).get("read_count") or 0)
        if n <= max_reads:
            continue
        norm = str(path).replace("\\", "/").lower()
        if not norm.startswith(root):
            continue
        if Path(path).suffix.lower() not in _CPP:
            continue
        fails.append(f"read_count {n} > {max_reads} for {path}")
    return fails


def run_pipeline(op: Path, arch: str, *, cache_mode: str, profile: str) -> dict[str, Any]:
    from ascendc_pilot.state import start_workflow
    from uo_init.codemap_engines import analyze, commit, extract, prepare, verify
    from uo_init.perf import dump_yaml, record_stage, reset, set_meta

    os.environ["UO_TIMING"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["UO_ARCH"] = arch
    reset()
    set_meta(
        operator=op.name,
        architecture=arch,
        cache_mode=cache_mode,
        profile=profile,
    )
    _wipe(op, arch, cache_mode)

    started = start_workflow(
        op,
        "uo-init",
        op_name=op.name,
        architecture=arch,
        intent=f"perf-gate {cache_mode}",
    )
    run_id = str(started.get("run_id") or "")
    ctx = {
        "op_name": op.name,
        "architecture": arch,
        "arch_dir": arch,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "confirm",
        "run_id": run_id,
    }
    stages: dict[str, Any] = {"start": {"ok": bool(started.get("ok")), "run_id": run_id}}
    t_all = time.perf_counter()
    for name, fn in (
        ("prepare", prepare),
        ("extract", extract),
        ("analyze", analyze),
        ("commit", commit),
        ("verify", verify),
    ):
        t0 = time.perf_counter()
        print(f"\n----- {name} -----", flush=True)
        out = fn(op, ctx)
        dt = time.perf_counter() - t0
        record_stage(name, dt)
        stages[name] = {
            "elapsed_s": round(dt, 3),
            "ok": bool(out.get("ok")),
            "error": out.get("error"),
        }
        print(f"{name} {dt:.3f}s ok={out.get('ok')} error={out.get('error')}", flush=True)
        if not out.get("ok"):
            stages["ok"] = False
            stages["failed_step"] = name
            break
        if out.get("run_id"):
            ctx["run_id"] = out.get("run_id")
    else:
        stages["ok"] = True
    stages["total_s"] = round(time.perf_counter() - t_all, 3)
    stages["cache_mode"] = cache_mode

    uo = op / ".ascendc-pilot" / arch / "uo"
    quality_path = uo / "checks" / "quality.yaml"
    quality = _load_yaml(quality_path)
    precision = _precision_from_quality(quality)
    product = Path(str(quality.get("uo_product") or (uo / f"{op.name}.{arch}.uo")))
    if not product.is_file():
        matches = list(uo.glob(f"*.{arch}.uo"))
        if matches:
            product = matches[0]
    precision = _enrich_from_product(precision, product)
    stages["precision"] = precision
    try:
        dump_yaml(uo / "checks" / "performance.yaml")
    except Exception:  # noqa: BLE001
        pass
    stages["performance"] = _load_yaml(uo / "checks" / "performance.yaml")
    return stages


def _write_run(out_dir: Path, stages: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rebuild.json").write_text(
        json.dumps(stages, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _dump_yaml(out_dir / "precision.yaml", dict(stages.get("precision") or {}))
    perf = dict(stages.get("performance") or {})
    if perf:
        _dump_yaml(out_dir / "performance.yaml", perf)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="uo-init FAG arch35 perf gate")
    parser.add_argument("--op", type=Path, default=DEFAULT_OP)
    parser.add_argument(
        "--arch",
        default=os.environ.get("UO_ARCH") or "",
        help="Required architecture id (or set UO_ARCH). No silent default.",
    )
    parser.add_argument(
        "--mode",
        default="true-cold",
        choices=["true-cold", "frontend-warm", "uo-update"],
    )
    parser.add_argument("--gate", default="phase1", choices=["phase0", "phase1", "phase2"])
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--ifa", type=Path, default=DEFAULT_IFA)
    parser.add_argument("--skip-ifa", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "artifacts" / "uo-init-perf" / "runs" / "latest",
    )
    args = parser.parse_args(argv)

    arch = str(args.arch or "").strip()
    if not arch:
        print("architecture required: pass --arch or set UO_ARCH", flush=True)
        return 2
    args.arch = arch

    if not args.op.is_dir():
        print(f"operator not found: {args.op}", flush=True)
        return 2

    result = run_pipeline(args.op, args.arch, cache_mode=args.mode, profile="fast")
    _write_run(args.out, result)
    gold = _load_yaml(args.gold)
    fails: list[str] = []
    if not result.get("ok"):
        fails.append(f"pipeline failed at {result.get('failed_step')}")
    if gold:
        fails.extend(compare_gold(result.get("precision") or {}, gold))
    fails.extend(_hot_file_fails(result.get("performance") or {}, args.op))
    total = float(result.get("total_s") or 0)
    analyze_s = float(((result.get("analyze") or {}).get("elapsed_s")) or 0)
    krt_s = float((result.get("precision") or {}).get("kernel_root_trace_s") or 0)
    if args.mode == "true-cold":
        if args.gate == "phase1" and total > 80:
            fails.append(f"true-cold {total:.1f}s > 80s")
        if args.gate == "phase2" and total > 60:
            fails.append(f"true-cold {total:.1f}s > 60s")
    else:
        print(
            f"cache_mode={args.mode} wall clock {total:.1f}s is informational only",
            flush=True,
        )

    ifa_result: dict[str, Any] = {}
    if (
        args.gate in {"phase1", "phase2"}
        and not args.skip_ifa
        and args.ifa.is_dir()
        and args.mode == "true-cold"
    ):
        print("\n===== IFA true-cold =====", flush=True)
        ifa_out = args.out.parent / "ifa-latest"
        ifa_result = run_pipeline(args.ifa, args.arch, cache_mode="true-cold", profile="fast")
        _write_run(ifa_out, ifa_result)
        ifa_analyze = float((ifa_result.get("analyze") or {}).get("elapsed_s") or 0)
        ifa_krt = float((ifa_result.get("precision") or {}).get("kernel_root_trace_s") or 0)
        if not ifa_result.get("ok"):
            fails.append(f"IFA pipeline failed at {ifa_result.get('failed_step')}")
        if ifa_analyze > 70:
            fails.append(f"IFA analyze {ifa_analyze:.1f}s > 70s")
        if ifa_krt and ifa_krt > 35:
            fails.append(f"IFA kernel_root_trace {ifa_krt:.1f}s > 35s")

    summary = {
        "ok": not fails,
        "fails": fails,
        "total_s": total,
        "analyze_s": analyze_s,
        "kernel_root_trace_s": krt_s,
        "cache_mode": args.mode,
        "ifa_analyze_s": float((ifa_result.get("analyze") or {}).get("elapsed_s") or 0)
        if ifa_result
        else None,
    }
    print(json.dumps(summary, indent=2), flush=True)
    (args.out / "gate.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
