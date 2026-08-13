# -*- coding: utf-8 -*-
"""Cold-start uo-init across ops-transformer families (~30 ops).

Collects verify + unknown/partial/OTHER plus cannbot locate quality
(source_span / packing / SourceLocator hits). Never wipes
``flash_attention_score_grad/.ascendc-pilot/arch22``.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OPS_ROOT = Path(r"D:\PR-review\TEST\ops-transformer")
OUT = Path(os.environ.get("UO_GEN_OUT") or (REPO / "artifacts" / "uo-init-generalization"))
DOCS_TEST = REPO / "docs" / "test"

# One arch per operator. Cover every family folder that has real op_host/op_kernel.
# FAG arch22 is audit-only (no wipe).
CASES: list[dict[str, Any]] = [
    # attention
    {"rel": "attention/flash_attention_score_grad", "arch": "arch35", "wipe": True},
    {"rel": "attention/flash_attention_score", "arch": "arch35", "wipe": True},
    {"rel": "attention/incre_flash_attention", "arch": "arch22", "wipe": True},
    {"rel": "attention/prompt_flash_attention", "arch": "arch22", "wipe": True},
    {"rel": "attention/fused_infer_attention_score", "arch": "arch35", "wipe": True},
    {"rel": "attention/sparse_flash_attention", "arch": "arch35", "wipe": True},
    {"rel": "attention/lightning_indexer", "arch": "arch22", "wipe": True},
    {"rel": "attention/mla_prolog", "arch": "arch35", "wipe": True},
    {"rel": "attention/compressor", "arch": "arch22", "wipe": True},
    {"rel": "attention/fused_causal_conv1d", "arch": "arch35", "wipe": True},
    # ffn (only ffn_worker_batching has an arch* dir)
    {"rel": "ffn/ffn_worker_batching", "arch": "arch35", "wipe": True},
    # gmm
    {"rel": "gmm/grouped_matmul", "arch": "arch35", "wipe": True},
    {"rel": "gmm/grouped_matmul_add", "arch": "arch35", "wipe": True},
    {"rel": "gmm/grouped_matmul_swiglu_quant_v2", "arch": "arch35", "wipe": True},
    {"rel": "gmm/grouped_matmul_finalize_routing", "arch": "arch35", "wipe": True},
    # mamba
    {"rel": "mamba/causal_conv1d", "arch": "arch35", "wipe": True},
    # mc2
    {"rel": "mc2/matmul_all_reduce", "arch": "arch22", "wipe": True},
    {"rel": "mc2/moe_distribute_dispatch", "arch": "arch22", "wipe": True},
    {"rel": "mc2/all_gather_matmul_v2", "arch": "arch35", "wipe": True},
    {"rel": "mc2/moe_distribute_combine", "arch": "arch35", "wipe": True},
    {"rel": "mc2/matmul_reduce_scatter_v2", "arch": "arch22", "wipe": True},
    # mhc
    {"rel": "mhc/mhc_pre", "arch": "arch35", "wipe": True},
    {"rel": "mhc/mhc_post", "arch": "arch22", "wipe": True},
    {"rel": "mhc/mhc_sinkhorn", "arch": "arch35", "wipe": True},
    # moe
    {"rel": "moe/moe_init_routing_v2", "arch": "arch35", "wipe": True},
    {"rel": "moe/moe_init_routing", "arch": "arch35", "wipe": True},
    {"rel": "moe/moe_gating_top_k", "arch": "arch35", "wipe": True},
    {"rel": "moe/moe_finalize_routing_v2", "arch": "arch35", "wipe": True},
    {"rel": "moe/moe_gating_top_k_softmax", "arch": "arch35", "wipe": True},
    # posembedding
    {"rel": "posembedding/rotary_position_embedding", "arch": "arch35", "wipe": True},
    {"rel": "posembedding/apply_rotary_pos_emb", "arch": "arch35", "wipe": True},
    {"rel": "posembedding/rope_with_sin_cos_cache", "arch": "arch35", "wipe": True},
    {"rel": "posembedding/rotary_position_embedding_grad", "arch": "arch35", "wipe": True},
    # Extra: existing FAG arch22 product — inspect only, never wipe.
    {"rel": "attention/flash_attention_score_grad", "arch": "arch22", "wipe": False, "audit_only": True},
]

sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]


def _forbidden_wipe(rel: str, arch: str) -> bool:
    return rel.endswith("flash_attention_score_grad") and arch == "arch22"


def _trim_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    kinds = summary.get("entities_by_kind") or {}
    return {
        "entity_count": summary.get("entity_count"),
        "relation_count": summary.get("relation_count"),
        "other": kinds.get("OTHER", 0),
        "operation": kinds.get("OPERATION", 0),
        "tiling_key": kinds.get("TILING_KEY", 0),
        "kernel": kinds.get("KERNEL", 0),
        "has_host_kernel_path": summary.get("has_host_kernel_path"),
        "has_tilingdata_kernel_path": summary.get("has_tilingdata_kernel_path"),
        "tiling_key_declaration_coverage": summary.get("tiling_key_declaration_coverage"),
        "tiling_key_host_packing_coverage": summary.get("tiling_key_host_packing_coverage"),
        "tiling_key_host_producer_coverage": summary.get("tiling_key_host_producer_coverage"),
        "tiling_key_root_coverage": summary.get("tiling_key_root_coverage"),
        "tiling_key_dependency_coverage": summary.get("tiling_key_dependency_coverage"),
    }


def _brief(out: dict) -> dict[str, Any]:
    keys = (
        "ok",
        "engine",
        "error",
        "failed_step",
        "blocking",
        "verdict",
        "gap_count",
        "semantic_completeness",
        "run_id",
        "phase",
        "clang_scope",
        "closure_mode",
    )
    brief = {k: out.get(k) for k in keys if k in out}
    if "summary" in out:
        brief["summary"] = _trim_summary(out.get("summary"))
    blocking = out.get("blocking")
    if isinstance(blocking, list):
        brief["blocking_codes"] = [b.get("code") for b in blocking if isinstance(b, dict)]
    return brief


def inspect_product(op: Path, arch: str, op_name: str) -> dict[str, Any]:
    from uo_init.diagnostics.audit import audit_codemap
    from uo_init.store.reader import find_uo_product, read_codemap

    product = find_uo_product(op, op_name=op_name, architecture=arch)
    if product is None:
        return {"ok": False, "error": "missing_uo_product"}

    cm = read_codemap(product)
    audit = audit_codemap(cm)
    ent_status: Counter[str] = Counter()
    rel_status: Counter[str] = Counter()
    partial_by_kind: Counter[str] = Counter()
    unknown_by_kind: Counter[str] = Counter()
    unknown_samples: list[dict[str, Any]] = []
    other_samples: list[dict[str, Any]] = []
    other_status: Counter[str] = Counter()
    for e in cm.entities.values():
        s = str(e.status).lower()
        k = e.kind_name()
        ent_status[s] += 1
        if s == "partial":
            partial_by_kind[k] += 1
        if s == "unknown":
            unknown_by_kind[k] += 1
            if len(unknown_samples) < 12:
                unknown_samples.append({"kind": k, "name": e.name, "file": e.file, "status": s})
        if k == "OTHER":
            other_status[s] += 1
            if len(other_samples) < 12:
                other_samples.append({"name": e.name, "status": s, "file": e.file})
    for r in cm.relations.values():
        rel_status[str(r.status).lower()] += 1

    n_ent = len(cm.entities) or 1
    n_rel = len(cm.relations) or 1
    noisy_ent = (
        ent_status.get("unknown", 0)
        + ent_status.get("partial", 0)
        + ent_status.get("unresolved", 0)
    )
    other_n = sum(1 for e in cm.entities.values() if e.kind_name() == "OTHER")

    locate = _locate_quality(cm, product)

    unresolved_path = op / ".ascendc-pilot" / arch / "uo" / "ir" / "unresolved.yaml"
    gap_codes: Counter[str] = Counter()
    gap_status: Counter[str] = Counter()
    blocker_count = 0
    if unresolved_path.is_file():
        from uo_init import pilot_engines as pe

        payload = pe._load(unresolved_path) or {}
        blockers = payload.get("blockers") or []
        blocker_count = int(payload.get("blocker_count") or len(blockers) or 0)
        for b in blockers:
            if not isinstance(b, dict):
                continue
            gap_codes[str(b.get("code") or "unknown")] += 1
            gap_status[str(b.get("status") or "")] += 1

    krt = audit.get("kernel_root_trace_quality") or {}
    warnings = audit.get("warnings") or []
    blocking = audit.get("blocking") or []
    return {
        "ok": bool(audit.get("ok")),
        "product": str(product),
        "size_bytes": product.stat().st_size,
        "entity_count": len(cm.entities),
        "relation_count": len(cm.relations),
        "entity_status": dict(ent_status),
        "relation_status": dict(rel_status),
        "unknown_entities": ent_status.get("unknown", 0),
        "partial_entities": ent_status.get("partial", 0),
        "unresolved_entities": ent_status.get("unresolved", 0),
        "unknown_relations": rel_status.get("unknown", 0),
        "partial_relations": rel_status.get("partial", 0),
        "noisy_entity_ratio": round(noisy_ent / n_ent, 4),
        "unknown_entity_ratio": round(ent_status.get("unknown", 0) / n_ent, 4),
        "other_count": other_n,
        "other_ratio": round(other_n / n_ent, 4),
        "other_status": dict(other_status),
        "partial_by_kind": dict(partial_by_kind.most_common(12)),
        "unknown_by_kind": dict(unknown_by_kind.most_common(12)),
        "unknown_samples": unknown_samples,
        "other_samples": other_samples,
        "blocker_count": blocker_count,
        "gap_codes": dict(gap_codes.most_common(12)),
        "gap_status": dict(gap_status),
        "blocking_codes": [b.get("code") for b in blocking if isinstance(b, dict)],
        "warning_codes": [w.get("code") for w in warnings if isinstance(w, dict)],
        "unresolved_facts": next(
            (
                w.get("detail")
                for w in warnings
                if isinstance(w, dict) and w.get("code") == "UNRESOLVED_FACTS"
            ),
            None,
        ),
        "tiling": {
            "declaration": (audit.get("summary") or {}).get("tiling_key_declaration_coverage"),
            "packing": (audit.get("summary") or {}).get("tiling_key_host_packing_coverage"),
            "producer": (audit.get("summary") or {}).get("tiling_key_host_producer_coverage"),
            "root": (audit.get("summary") or {}).get("tiling_key_root_coverage"),
            "dependency": (audit.get("summary") or {}).get("tiling_key_dependency_coverage"),
            "has_tilingdata_kernel_path": audit.get("evidence_backed_tilingdata_kernel_path"),
            "has_host_kernel_path": audit.get("evidence_backed_host_kernel_path"),
        },
        "kernel_root_trace": {
            "ops": krt.get("ops") or krt.get("operations"),
            "gap_count": krt.get("gap_count"),
            "reached_operations": krt.get("reached_operations"),
            "other_not_in_krt": None,
        },
        "counts": audit.get("counts") or {},
        "locate": locate,
    }


_LOCATE_KINDS = (
    "INPUT",
    "OUTPUT",
    "TILING_KEY",
    "TILING_DATA",
    "TILING_FIELD",
    "KERNEL",
    "FUNCTION",
    "BRANCH",
    "BUFFER",
    "OPERATION",
)


def _has_span(entity: Any) -> bool:
    return bool(str(getattr(entity, "file", "") or "").strip()) and int(
        getattr(entity, "line_start", 0) or 0
    ) > 0


def _sites_with_span(attrs: dict[str, Any], *keys: str) -> int:
    n = 0
    for key in keys:
        for site in attrs.get(key) or []:
            if not isinstance(site, dict):
                continue
            if str(site.get("file") or "").strip() and int(
                site.get("line") or site.get("line_start") or 0
            ) > 0:
                n += 1
                break
    return n


def _locate_quality(cm: Any, product: Path) -> dict[str, Any]:
    """Can cannbot pin Issue anchors (locate / tiling_key / field) without grep?"""
    span: dict[str, Any] = {}
    by_kind: dict[str, list[Any]] = {k: [] for k in _LOCATE_KINDS}
    for entity in cm.entities.values():
        kind = entity.kind_name()
        if kind in by_kind:
            by_kind[kind].append(entity)
    for kind, ents in by_kind.items():
        n = len(ents)
        with_span = sum(1 for e in ents if _has_span(e))
        span[kind] = {
            "n": n,
            "with_span": with_span,
            "ratio": round(with_span / n, 3) if n else None,
        }

    keys = by_kind["TILING_KEY"]
    fields = by_kind["TILING_FIELD"]
    pack_n = sum(
        _sites_with_span(e.attrs or {}, "packing_value_sites", "producer_sites")
        for e in keys
    )
    writer_n = sum(
        _sites_with_span(
            e.attrs or {},
            "host_writer_sites",
            "value_defining_sites",
            "check_sites",
        )
        for e in fields
    )

    dtype_n = 0
    for entity in by_kind["INPUT"]:
        attrs = entity.attrs or {}
        facts = attrs.get("facts") if isinstance(attrs.get("facts"), dict) else {}
        if attrs.get("dtype") or facts.get("dtype"):
            dtype_n += 1
    input_n = span["INPUT"]["n"]
    kernel_api: dict[str, dict[str, int]] = {}
    for needle in ("EnQue", "InitBuffer", "DataCopy", "SetFlag", "WaitFlag"):
        n = 0
        spanned = 0
        for entity in by_kind["OPERATION"]:
            attrs = entity.attrs or {}
            blob = " ".join(
                str(x or "")
                for x in (entity.name, attrs.get("callee"), attrs.get("api"))
            )
            if needle.lower() not in blob.lower():
                continue
            n += 1
            if _has_span(entity):
                spanned += 1
        kernel_api[needle] = {"n": n, "with_span": spanned}

    probes: list[dict[str, Any]] = []
    samples: list[tuple[str, str]] = []
    for kind in ("TILING_KEY", "TILING_FIELD", "KERNEL", "INPUT", "BRANCH"):
        seen: set[str] = set()
        ents = list(by_kind.get(kind) or [])
        if kind == "BRANCH":
            ents = [
                e
                for e in ents
                if str((e.attrs or {}).get("branch_kind") or "") == "host_check"
            ] or ents
        for entity in ents:
            name = str(entity.name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            samples.append((kind, name))
            if len(seen) >= 3:
                break
    function_probes: list[dict[str, Any]] = []
    fn_samples: list[str] = []
    seen_fn: set[str] = set()
    fn_names = {
        str(e.name or "").strip()
        for e in (by_kind.get("FUNCTION") or [])
        if str(e.name or "").strip()
    }
    for name in (
        "CheckShapeValid",
        "CheckSoftmaxMaxShape",
        "CheckSoftmaxSumShape",
    ):
        if name in fn_names and name not in seen_fn:
            seen_fn.add(name)
            fn_samples.append(name)
    for entity in by_kind.get("FUNCTION") or []:
        name = str(entity.name or "").strip()
        if not name or name in seen_fn:
            continue
        seen_fn.add(name)
        fn_samples.append(name)
        if len(fn_samples) >= 3:
            break
    try:
        from uo_init.source_locator import SourceLocator

        locator = SourceLocator(product)
        for kind, name in samples:
            if kind == "TILING_KEY":
                hits = locator.locate_dim(name, limit=5)
            elif kind == "TILING_FIELD":
                hits = locator.locate_field(name, limit=5)
            else:
                hits = locator.locate(name, kinds=(kind,), limit=5)
            spanned = [h for h in hits if h.file and int(h.line_start or 0) > 0]
            probes.append(
                {
                    "kind": kind,
                    "name": name[:80],
                    "hits": len(hits),
                    "hits_with_span": len(spanned),
                    "sample": (
                        f"{spanned[0].file}:{spanned[0].line_start}" if spanned else None
                    ),
                }
            )
        for name in fn_samples:
            hits = locator.locate(name, kinds=("FUNCTION",), limit=5)
            spanned = [h for h in hits if h.file and int(h.line_start or 0) > 0]
            function_probes.append(
                {
                    "kind": "FUNCTION",
                    "name": name[:80],
                    "hits": len(hits),
                    "hits_with_span": len(spanned),
                    "sample": (
                        f"{spanned[0].file}:{spanned[0].line_start}" if spanned else None
                    ),
                }
            )
    except Exception as exc:  # noqa: BLE001
        probes.append({"error": f"{type(exc).__name__}: {exc}"[:240]})

    tried = [p for p in probes if "hits_with_span" in p]
    hit_n = sum(1 for p in tried if int(p.get("hits_with_span") or 0) > 0)
    fn_tried = [p for p in function_probes if "hits_with_span" in p]
    fn_hit_n = sum(1 for p in fn_tried if int(p.get("hits_with_span") or 0) > 0)
    key_span = span["TILING_KEY"]
    kernel_span = span["KERNEL"]
    input_span = span["INPUT"]
    buffer_span = span["BUFFER"]
    host_checks = [
        e
        for e in by_kind["BRANCH"]
        if str((e.attrs or {}).get("branch_kind") or "") == "host_check"
    ]
    host_check_n = len(host_checks)
    host_check_span_n = sum(1 for e in host_checks if _has_span(e))
    keys_ok = key_span["n"] == 0 or (key_span["ratio"] or 0) >= 0.5
    kernel_ok = kernel_span["with_span"] >= 1
    input_ok = input_span["with_span"] >= 1
    locate_ok = (not tried) or hit_n >= max(1, len(tried) // 2)
    buffer_ok = buffer_span["n"] == 0 or buffer_span["with_span"] >= 1
    api_ok = any(int(v.get("with_span") or 0) > 0 for v in kernel_api.values()) or not any(
        int(v.get("n") or 0) > 0 for v in kernel_api.values()
    )
    host_check_ok = host_check_n == 0 or host_check_span_n >= 1
    ready = bool(
        kernel_ok and input_ok and keys_ok and locate_ok and buffer_ok and api_ok and host_check_ok
    )
    gaps = []
    if kernel_span["n"] == 0 or not kernel_ok:
        gaps.append("no_kernel_span")
    if input_span["n"] == 0 or not input_ok:
        gaps.append("no_input_span")
    if key_span["n"] > 0 and not keys_ok:
        gaps.append("weak_tiling_key_span")
    if keys and pack_n == 0:
        gaps.append("no_tiling_key_packing_site")
    if fields and writer_n == 0:
        gaps.append("no_tiling_field_writer")
    if buffer_span["n"] > 0 and not buffer_ok:
        gaps.append("no_buffer_span")
    if not api_ok:
        gaps.append("no_kernel_api_span")
    if not host_check_ok:
        gaps.append("no_host_check_span")
    if not locate_ok:
        gaps.append("locate_miss")
    return {
        "span": span,
        "tiling_key_packing_sites": f"{pack_n}/{len(keys)}",
        "tiling_field_writer_sites": f"{writer_n}/{len(fields)}",
        "input_dtype": f"{dtype_n}/{input_n}",
        "kernel_api": kernel_api,
        "host_check_span": f"{host_check_span_n}/{host_check_n}",
        "locate_probes": probes,
        "function_probes": function_probes,
        "locate_hit_rate": round(hit_n / len(tried), 3) if tried else None,
        "function_locate_hit_rate": round(fn_hit_n / len(fn_tried), 3) if fn_tried else None,
        "cannbot_locate_ready": ready,
        "gaps": gaps,
    }


def _probe_snapshot(op: Path, arch: str) -> dict[str, Any]:
    runs = op / ".ascendc-pilot" / arch / "uo" / "runs"
    if not runs.is_dir():
        return {}
    cands = sorted(runs.rglob("candidates.yaml"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        return {}
    from uo_init import pilot_engines as pe

    data = pe._load(cands[0]) or {}
    dirty = []
    for p in data.get("probes") or []:
        if not isinstance(p, dict):
            continue
        if int(p.get("errors") or 0) <= 0 and not p.get("fatal") and not p.get("error"):
            continue
        dirty.append(
            {
                "file": Path(str(p.get("file") or "")).name,
                "side": p.get("side"),
                "errors": p.get("errors"),
                "fatal": p.get("fatal"),
                "operator_error_count": p.get("operator_error_count"),
                "samples": list(p.get("samples") or [])[:3],
            }
        )
    extras_path = op / ".ascendc-pilot" / arch / "uo" / "summary" / "build_context_extras.yaml"
    extras = pe._load(extras_path) if extras_path.is_file() else {}
    heal = data.get("include_heal") or extras or {}
    return {
        "probe_clean": data.get("probe_clean"),
        "clang_scope_status": data.get("clang_scope_status"),
        "host_probe_errors": data.get("host_probe_errors"),
        "kernel_probe_errors": data.get("kernel_probe_errors"),
        "include_heal": {
            "rounds": heal.get("rounds"),
            "added_host": list(heal.get("added_host") or [])[:12],
            "added_kernel": list(heal.get("added_kernel") or [])[:12],
            "healed": [
                {
                    "include": h.get("include"),
                    "side": h.get("side"),
                    "source": h.get("source"),
                }
                for h in (heal.get("healed") or [])[:12]
                if isinstance(h, dict)
            ],
            "unresolved": list(heal.get("unresolved") or [])[:8],
        },
        "dirty": dirty[:8],
    }


def _save(doc: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _write_summary(doc: dict[str, Any]) -> None:
    """Compact per-family rollup for cannbot locate + prepare/verify."""
    families: dict[str, dict[str, Any]] = {}
    rows = []
    for case in doc.get("cases") or []:
        if not isinstance(case, dict):
            continue
        fam = str(case.get("family") or (str(case.get("rel") or "").split("/")[0]))
        noise = case.get("noise") or {}
        locate = noise.get("locate") or {}
        probe = case.get("probe") or {}
        rec = {
            "rel": case.get("rel"),
            "arch": case.get("architecture"),
            "ok": case.get("ok"),
            "failed_step": case.get("failed_step"),
            "elapsed_s": case.get("elapsed_s"),
            "verify": case.get("verdict"),
            "unknown": noise.get("unknown_entities"),
            "partial": noise.get("partial_entities"),
            "other": noise.get("other_count"),
            "host_probe_errors": probe.get("host_probe_errors"),
            "kernel_probe_errors": probe.get("kernel_probe_errors"),
            "cannbot_locate_ready": locate.get("cannbot_locate_ready"),
            "locate_hit_rate": locate.get("locate_hit_rate"),
            "locate_gaps": locate.get("gaps"),
            "tiling_key_packing_sites": locate.get("tiling_key_packing_sites"),
            "tiling_field_writer_sites": locate.get("tiling_field_writer_sites"),
            "host_check_span": locate.get("host_check_span"),
            "function_locate_hit_rate": locate.get("function_locate_hit_rate"),
            "input_dtype": locate.get("input_dtype"),
            "kernel_api": locate.get("kernel_api"),
            "audit_only": case.get("audit_only"),
        }
        rows.append(rec)
        bucket = families.setdefault(
            fam,
            {"n": 0, "ok": 0, "product": 0, "locate_ready": 0, "unknown_nonzero": 0},
        )
        if not case.get("audit_only"):
            bucket["n"] += 1
            if case.get("ok"):
                bucket["ok"] += 1
        if noise.get("entity_count"):
            bucket["product"] += 1
        if locate.get("cannbot_locate_ready"):
            bucket["locate_ready"] += 1
        if int(noise.get("unknown_entities") or 0) > 0:
            bucket["unknown_nonzero"] += 1
    payload = {
        "schema": "uo-init-generalization-summary/v2",
        "date": doc.get("date"),
        "elapsed_s": doc.get("elapsed_s"),
        "n_cases": len(rows),
        "families": families,
        "rows": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def run_one(case: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.state import start_workflow
    from uo_init.codemap_engines import analyze, commit, extract, prepare, verify

    rel = str(case["rel"])
    arch = str(case["arch"])
    op = OPS_ROOT / rel
    op_name = Path(rel).name
    row: dict[str, Any] = {
        "rel": rel,
        "family": rel.split("/")[0] if "/" in rel else "",
        "op_name": op_name,
        "architecture": arch,
        "wipe": bool(case.get("wipe")),
        "audit_only": bool(case.get("audit_only")),
    }
    if not op.is_dir():
        row["ok"] = False
        row["error"] = "missing_op_dir"
        return row

    if case.get("audit_only"):
        t0 = time.perf_counter()
        try:
            row["noise"] = inspect_product(op, arch, op_name)
            row["ok"] = bool(row["noise"].get("ok"))
        except Exception as exc:  # noqa: BLE001
            row["ok"] = False
            row["error"] = f"{type(exc).__name__}: {exc}"[:800]
        row["elapsed_s"] = round(time.perf_counter() - t0, 3)
        row["mode"] = "audit_existing"
        return row

    if _forbidden_wipe(rel, arch):
        row["ok"] = False
        row["error"] = "refused_wipe_fag_arch22"
        return row

    arch_dir = op / ".ascendc-pilot" / arch
    if case.get("wipe") and arch_dir.exists():
        shutil.rmtree(arch_dir)
        row["wiped"] = str(arch_dir)
    else:
        row["wiped"] = None

    t_all = time.perf_counter()
    started = start_workflow(
        op,
        "uo-init",
        op_name=op_name,
        architecture=arch,
        intent=f"generalization {rel} {arch}",
    )
    run_id = str(started.get("run_id") or "")
    row["run_id"] = run_id
    if not started.get("ok") or not run_id:
        row["ok"] = False
        row["error"] = "start_failed"
        row["start"] = _brief(started if isinstance(started, dict) else {})
        return row

    ctx = {
        "op_name": op_name,
        "architecture": arch,
        "arch_dir": arch,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "confirm",
        "run_id": run_id,
    }
    stages: dict[str, Any] = {}
    for name, fn in (
        ("prepare", prepare),
        ("extract", extract),
        ("analyze", analyze),
        ("commit", commit),
        ("verify", verify),
    ):
        t0 = time.perf_counter()
        print(f"\n===== {rel} {arch} :: {name} =====", flush=True)
        try:
            out = fn(op, ctx)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            out = {"ok": False, "engine": name, "error": f"{type(exc).__name__}: {exc}"[:800]}
        elapsed = round(time.perf_counter() - t0, 3)
        brief = _brief(out if isinstance(out, dict) else {"ok": True})
        brief["elapsed_s"] = elapsed
        stages[name] = brief
        print(json.dumps(brief, ensure_ascii=False, default=str)[:2500], flush=True)
        if isinstance(out, dict):
            for key in ("op_name", "architecture", "arch_dir", "run_id"):
                if out.get(key):
                    ctx[key] = out[key]
        if not (out.get("ok") if isinstance(out, dict) else True):
            row["ok"] = False
            row["failed_step"] = name
            row["stages"] = stages
            row["elapsed_s"] = round(time.perf_counter() - t_all, 3)
            if name == "prepare":
                row["probe"] = _probe_snapshot(op, arch)
            try:
                row["noise"] = inspect_product(op, arch, str(ctx.get("op_name") or op_name))
            except Exception:
                row["noise"] = {"ok": False, "error": "inspect_after_fail"}
            return row

    row["ok"] = True
    row["stages"] = stages
    row["elapsed_s"] = round(time.perf_counter() - t_all, 3)
    row["verify_ok"] = bool((stages.get("verify") or {}).get("ok"))
    row["verdict"] = (stages.get("verify") or {}).get("verdict")
    try:
        row["noise"] = inspect_product(op, arch, str(ctx.get("op_name") or op_name))
    except Exception as exc:  # noqa: BLE001
        row["noise"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:800]}
    return row


def main() -> int:
    os.environ["UO_TIMING"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ.pop("UO_INIT_PROFILE", None)
    os.environ.pop("UO_CACHE_ROOT", None)
    os.environ.pop("UO_COLD_BUDGET_S", None)
    os.environ.pop("UO_TEST_ALLOW_UNVERIFIED_SCOPE", None)

    OUT.mkdir(parents=True, exist_ok=True)
    DOCS_TEST.mkdir(parents=True, exist_ok=True)

    doc: dict[str, Any] = {
        "schema": "uo-init-generalization/v1",
        "date": time.strftime("%Y-%m-%d"),
        "profile": {
            "UO_INIT_PROFILE": os.environ.get("UO_INIT_PROFILE", "fast(default)"),
            "cpu_count": os.cpu_count(),
            "ops_root": str(OPS_ROOT),
            "allow_unverified_scope": os.environ.get("UO_TEST_ALLOW_UNVERIFIED_SCOPE", ""),
            "out": str(OUT),
        },
        "cases": [],
    }
    seed = OUT / "results_partial.json"
    if seed.is_file() and str(os.environ.get("UO_GEN_RESUME") or "").strip() in {"1", "true", "yes"}:
        try:
            prior = json.loads(seed.read_text(encoding="utf-8"))
            if isinstance(prior, dict) and isinstance(prior.get("cases"), list):
                doc["cases"] = list(prior["cases"])
                print(f"RESUME {len(doc['cases'])} prior cases from {seed}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"RESUME_SKIP {exc}", flush=True)
    skip = {
        item.strip()
        for item in str(os.environ.get("UO_GEN_SKIP") or "").split(",")
        if item.strip()
    }
    only = {
        item.strip()
        for item in str(os.environ.get("UO_GEN_ONLY") or "").split(",")
        if item.strip()
    }
    for prior in doc.get("cases") or []:
        if isinstance(prior, dict) and prior.get("rel") and prior.get("architecture"):
            skip.add(f"{prior['rel']}:{prior['architecture']}")
    t_all = time.perf_counter()
    for case in CASES:
        key = f"{case['rel']}:{case['arch']}"
        if only and key not in only and str(case["rel"]) not in only:
            continue
        if key in skip or str(case["rel"]) in skip:
            print(f"\n########## SKIP {key} ##########", flush=True)
            continue
        print(
            f"\n########## {case['rel']} {case['arch']} "
            f"wipe={case.get('wipe')} audit_only={case.get('audit_only')} ##########",
            flush=True,
        )
        row = run_one(case)
        doc["cases"].append(row)
        doc["elapsed_s"] = round(time.perf_counter() - t_all, 3)
        _save(doc)
        noise = row.get("noise") or {}
        locate = noise.get("locate") or {}
        print(
            json.dumps(
                {
                    "rel": row.get("rel"),
                    "family": row.get("family"),
                    "arch": row.get("architecture"),
                    "ok": row.get("ok"),
                    "elapsed_s": row.get("elapsed_s"),
                    "verify": row.get("verdict"),
                    "unknown": noise.get("unknown_entities"),
                    "partial": noise.get("partial_entities"),
                    "other": noise.get("other_count"),
                    "blockers": noise.get("blocker_count"),
                    "blocking": noise.get("blocking_codes"),
                    "cannbot_locate_ready": locate.get("cannbot_locate_ready"),
                    "locate_hit_rate": locate.get("locate_hit_rate"),
                    "locate_gaps": locate.get("gaps"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        _write_summary(doc)

    doc["elapsed_s"] = round(time.perf_counter() - t_all, 3)
    doc["ok"] = all(bool(c.get("ok")) for c in doc["cases"] if not c.get("audit_only"))
    _save(doc)
    _write_summary(doc)
    print("ALL_DONE", json.dumps({"ok": doc["ok"], "elapsed_s": doc["elapsed_s"]}), flush=True)
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
