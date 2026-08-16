# -*- coding: utf-8 -*-
"""Cold-start uo-init across ops-transformer families.

Discovers AICore operators (must have ``op_kernel/``), samples by family
density (Hamilton), and records verify + cannbot locate quality.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]
from uo_init.diagnostics.source_api import (
    count_graph_kernel_api,
    count_source_kernel_apis,
    precision_gaps,
    rank_blockers,
    source_api_from_codemap,
)
from uo_init.paths import ops_root as _resolve_ops_root

OPS_ROOT = Path(
    os.environ.get("UO_OPS_ROOT")
    or os.environ.get("OPS_TRANSFORMER_ROOT")
    or os.environ.get("OPS_ROOT")
    or ""
)
if not str(OPS_ROOT):
    OPS_ROOT = Path(_resolve_ops_root() or (REPO.parent / "TEST" / "ops-transformer"))
OUT = Path(os.environ.get("UO_GEN_OUT") or (REPO / "artifacts" / "uo-init-generalization"))
DOCS_TEST = REPO / "docs" / "test"

_FAMILIES = (
    "attention",
    "ffn",
    "gmm",
    "mamba",
    "mc2",
    "mhc",
    "moe",
    "posembedding",
)
_SKIP_OP_NAMES = frozenset({"common", "include", "src", "3rd", "tests", "test", "docs", "examples"})
_ARCH_DIR_RE = re.compile(r"^arch\d+$")


def _arch_sort_key(name: str) -> int:
    return int(str(name).removeprefix("arch"))


def _list_archs(op: Path) -> list[str]:
    seen: set[str] = set()
    for parent in (op / "op_host", op / "op_kernel"):
        if not parent.is_dir():
            continue
        for child in parent.iterdir():
            if child.is_dir() and _ARCH_DIR_RE.match(child.name):
                seen.add(child.name)
    return sorted(seen, key=_arch_sort_key)


def _pick_arch(op: Path) -> str | None:
    """Prefer arch35 when discovered; else newest numeric arch*.

    Operators whose host/kernel trees have no ``archNN`` folders still run
    as the preferred architecture: the source is arch-agnostic, not missing.
    """
    archs = _list_archs(op)
    preferred = "arch35"
    if preferred in archs:
        return preferred
    if archs:
        return max(archs, key=_arch_sort_key)
    return preferred


def discover_ops(ops_root: Path | None = None) -> list[dict[str, Any]]:
    """One case per AICore operator (must have ``op_kernel/``)."""
    root = Path(ops_root or OPS_ROOT)
    cases: list[dict[str, Any]] = []
    for fam in _FAMILIES:
        fam_dir = root / fam
        if not fam_dir.is_dir():
            continue
        for op in sorted(fam_dir.iterdir()):
            if not op.is_dir() or op.name in _SKIP_OP_NAMES:
                continue
            if not (op / "op_kernel").is_dir():
                continue
            arch = _pick_arch(op)
            rel = f"{fam}/{op.name}"
            if arch is None:
                print(f"NO_ARCHITECTURE_DISCOVERED {rel}", flush=True)
                continue
            cases.append(
                {
                    "rel": rel,
                    "arch": arch,
                    "wipe": True,
                    "family": fam,
                }
            )
    return cases


def _rel_items(env_name: str) -> list[str]:
    """Comma list in ``env_name``, plus optional ``{env_name}_FILE`` (one rel per line)."""
    items: list[str] = []
    raw = str(os.environ.get(env_name) or "").strip()
    if raw:
        items.extend(part.strip() for part in raw.split(",") if part.strip())
    file_raw = str(os.environ.get(f"{env_name}_FILE") or "").strip()
    if file_raw:
        path = Path(file_raw)
        if path.is_file():
            items.extend(
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _largest_remainder(n: int, weights: list[int]) -> list[int]:
    """Hamilton quotas: seats follow ``weights``, leftover by largest remainder."""
    if n <= 0 or not weights:
        return [0] * len(weights)
    total = sum(weights) or 1
    raw = [n * w / total for w in weights]
    floors = [int(x) for x in raw]
    leftover = n - sum(floors)
    order = sorted(
        range(len(weights)),
        key=lambda i: (raw[i] - floors[i], -i),
        reverse=True,
    )
    out = list(floors)
    for i in order[:leftover]:
        out[i] += 1
    return out


def sample_cases(n: int, *, seed: int, ops_root: Path | None = None) -> list[dict[str, Any]]:
    """Sample ``n`` ops. Default quotas follow eligible family sizes (Hamilton)."""
    exclude = set(_rel_items("UO_GEN_EXCLUDE"))
    pool = [
        case
        for case in discover_ops(ops_root)
        if case["rel"] not in exclude and f"{case['rel']}:{case['arch']}" not in exclude
    ]
    by_fam: dict[str, list[dict[str, Any]]] = {}
    for case in pool:
        by_fam.setdefault(str(case.get("family") or ""), []).append(case)
    rng = random.Random(int(seed))
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take(case: dict[str, Any]) -> None:
        key = f"{case['rel']}:{case['arch']}"
        if key in seen:
            return
        seen.add(key)
        picked.append(dict(case))

    families = [f for f in _FAMILIES if by_fam.get(f)]
    remain = max(0, int(n))
    alloc = str(os.environ.get("UO_GEN_ALLOC") or "proportional").strip().lower()
    if families and remain:
        if alloc in {"equal", "uniform", "even"}:
            base = remain // len(families)
            extra = remain % len(families)
            quotas = [base + (1 if i < extra else 0) for i in range(len(families))]
        else:
            quotas = _largest_remainder(remain, [len(by_fam[f]) for f in families])
        for fam, want in zip(families, quotas):
            cand = [c for c in by_fam[fam] if f"{c['rel']}:{c['arch']}" not in seen]
            rng.shuffle(cand)
            for case in cand[:want]:
                _take(case)

    if len(picked) < n:
        rest = [c for c in pool if f"{c['rel']}:{c['arch']}" not in seen]
        rng.shuffle(rest)
        for case in rest:
            if len(picked) >= n:
                break
            _take(case)
    return picked[:n]


def dump_sample(n: int, *, seed: int, ops_root: Path | None = None) -> dict[str, Any]:
    """Freeze a proportional sample plus the eligible universe counts."""
    universe = discover_ops(ops_root)
    by_fam = Counter(c["family"] for c in universe)
    cases = sample_cases(n, seed=seed, ops_root=ops_root)
    sample_by_fam = Counter(c["family"] for c in cases)
    return {
        "schema": "uo-init-sample/v1",
        "date": time.strftime("%Y-%m-%d"),
        "ops_root": str(Path(ops_root or OPS_ROOT)),
        "n": len(cases),
        "seed": int(seed),
        "alloc": str(os.environ.get("UO_GEN_ALLOC") or "proportional"),
        "eligible_n": len(universe),
        "eligible_by_family": dict(by_fam),
        "sample_by_family": dict(sample_by_fam),
        "cases": cases,
    }


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

    locate = _locate_quality(cm, product, op, arch)
    source_api = source_api_from_codemap(cm, op, arch) or count_source_kernel_apis(op, arch)
    gaps = precision_gaps(source_api, locate.get("kernel_api") or {})
    locate["source_api"] = source_api
    locate["precision_gaps"] = gaps

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

    quality_path = op / ".ascendc-pilot" / arch / "uo" / "checks" / "quality.yaml"
    quality: dict[str, Any] = {}
    if quality_path.is_file():
        from uo_init import pilot_engines as pe

        loaded = pe._load(quality_path) or {}
        if isinstance(loaded, dict):
            quality = {
                "grade": loaded.get("grade"),
                "locate_ready": loaded.get("locate_ready"),
                "integrity": loaded.get("integrity"),
                "unresolved": loaded.get("unresolved") or {},
                "not_ready_reasons": loaded.get("not_ready_reasons") or [],
                "surfaces": {
                    key: {
                        "ok": (val or {}).get("ok") if isinstance(val, dict) else None,
                    }
                    for key, val in (loaded.get("surfaces") or {}).items()
                    if isinstance(val, dict)
                },
            }

    unresolved_names: Counter[str] = Counter()
    if unresolved_path.is_file():
        from uo_init import pilot_engines as pe

        payload = pe._load(unresolved_path) or {}
        for b in payload.get("blockers") or []:
            if not isinstance(b, dict):
                continue
            if str(b.get("bucket") or "") != "catalog_unproven":
                continue
            unresolved_names[str(b.get("name") or b.get("callee") or "")] += 1

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
        "source_api": source_api,
        "precision_gaps": gaps,
        "quality": quality,
        "catalog_unproven_names": dict(unresolved_names.most_common(16)),
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


def _locate_quality(cm: Any, product: Path, op: Path, arch: str) -> dict[str, Any]:
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
    from uo_init.diagnostics.quality import source_schema_tiling_keys

    schema_keys = source_schema_tiling_keys(keys)
    pack_n = sum(
        1
        for e in schema_keys
        if _sites_with_span(e.attrs or {}, "packing_value_sites", "producer_sites")
        or (e.attrs or {}).get("host_packing_expressions")
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
    kernel_api = count_graph_kernel_api(by_kind["OPERATION"])

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
    keys_ok = (not schema_keys) or (
        pack_n == len(schema_keys) and key_span["with_span"] >= 1
    )
    kernel_ok = kernel_span["with_span"] >= 1
    input_ok = input_span["with_span"] >= 1
    locate_ok = (not tried) or hit_n >= max(1, len(tried) // 2)
    buffer_ok = buffer_span["n"] == 0 or buffer_span["with_span"] >= 1
    source_api = source_api_from_codemap(cm, op, arch) or (
        count_source_kernel_apis(op, arch) if op.is_dir() else {}
    )
    gaps_api = precision_gaps(source_api, kernel_api)
    any_graph_api = any(int(v.get("n") or 0) > 0 for v in kernel_api.values())
    any_source_api = any(int(source_api.get(name) or 0) > 0 for name in source_api)
    api_ok = not gaps_api and (any_graph_api or not any_source_api)
    host_check_ok = host_check_n == 0 or host_check_span_n == host_check_n
    ready = bool(
        kernel_ok and input_ok and keys_ok and locate_ok and buffer_ok and api_ok and host_check_ok
    )
    gaps = []
    if kernel_span["n"] == 0 or not kernel_ok:
        gaps.append("no_kernel_span")
    if input_span["n"] == 0 or not input_ok:
        gaps.append("no_input_span")
    if schema_keys and not keys_ok:
        gaps.append("weak_tiling_key_span")
    if schema_keys and pack_n == 0:
        gaps.append("no_tiling_key_packing_site")
    if fields and writer_n == 0:
        gaps.append("no_tiling_field_writer")
    if buffer_span["n"] > 0 and not buffer_ok:
        gaps.append("no_buffer_span")
    if not api_ok:
        gaps.append("no_kernel_api_span")
    if gaps_api:
        gaps.append("precision_gap")
    if not host_check_ok:
        gaps.append("no_host_check_span")
    if not locate_ok:
        gaps.append("locate_miss")
    return {
        "span": span,
        "tiling_key_packing_sites": f"{pack_n}/{len(schema_keys)}",
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
    payload = json.dumps(doc, ensure_ascii=False, indent=2, default=str)
    (OUT / "results.json").write_text(payload, encoding="utf-8")
    (OUT / "results_partial.json").write_text(payload, encoding="utf-8")


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
            "source_api": noise.get("source_api") or locate.get("source_api"),
            "precision_gaps": noise.get("precision_gaps") or locate.get("precision_gaps") or [],
            "quality_grade": (noise.get("quality") or {}).get("grade"),
            "locate_blocking": ((noise.get("quality") or {}).get("unresolved") or {}).get(
                "locate_blocking"
            ),
            "catalog_unproven": ((noise.get("quality") or {}).get("unresolved") or {}).get(
                "catalog_unproven"
            ),
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
    blockers = rank_blockers(doc.get("cases") or [])
    payload = {
        "schema": "uo-init-generalization-summary/v3",
        "date": doc.get("date"),
        "elapsed_s": doc.get("elapsed_s"),
        "n_cases": len(rows),
        "families": families,
        "blockers": blockers,
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
            noise = row["noise"] if isinstance(row.get("noise"), dict) else {}
            grade = str((noise.get("quality") or {}).get("grade") or "")
            gaps = noise.get("precision_gaps") or []
            other_n = int(noise.get("other_count") or 0)
            row["ok"] = bool(noise.get("ok")) and grade == "ready" and not gaps and other_n == 0
            if not row["ok"]:
                row["failed_step"] = "quality"
        except Exception as exc:  # noqa: BLE001
            row["ok"] = False
            row["error"] = f"{type(exc).__name__}: {exc}"[:800]
        row["elapsed_s"] = round(time.perf_counter() - t0, 3)
        row["mode"] = "audit_existing"
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
        row["ok"] = False
        row["failed_step"] = "quality"
        return row
    noise = row["noise"] if isinstance(row.get("noise"), dict) else {}
    grade = str((noise.get("quality") or {}).get("grade") or "")
    gaps = noise.get("precision_gaps") or []
    other_n = int(noise.get("other_count") or 0)
    if grade != "ready" or gaps or other_n > 0:
        row["ok"] = False
        row["failed_step"] = "quality"
    return row


def _load_cases_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict) and c.get("rel")]
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return [c for c in payload["cases"] if isinstance(c, dict) and c.get("rel")]
    raise ValueError(f"no cases in {path}")


def main() -> int:
    os.environ["UO_TIMING"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ.pop("UO_INIT_PROFILE", None)
    os.environ.pop("UO_CACHE_ROOT", None)
    os.environ.pop("UO_COLD_BUDGET_S", None)
    os.environ.pop("UO_TEST_ALLOW_UNVERIFIED_SCOPE", None)

    OUT.mkdir(parents=True, exist_ok=True)
    DOCS_TEST.mkdir(parents=True, exist_ok=True)

    argv = set(sys.argv[1:])
    dump_only = "--dump-sample" in argv
    sample_n = str(os.environ.get("UO_GEN_SAMPLE") or "").strip()
    sample_seed = int(str(os.environ.get("UO_GEN_SEED") or "20260816").strip() or "20260816")
    cases_file = str(os.environ.get("UO_GEN_CASES_FILE") or "").strip()
    only_list = _rel_items("UO_GEN_ONLY")
    cases: list[dict[str, Any]] = []
    if only_list:
        by_rel = {c["rel"]: c for c in discover_ops(OPS_ROOT)}
        cases = [by_rel[rel] for rel in only_list if rel in by_rel]
        missing = [rel for rel in only_list if rel not in by_rel]
        print(
            f"ONLY n={len(cases)} missing={missing} families="
            f"{Counter(c.get('family') for c in cases)}",
            flush=True,
        )
    elif cases_file:
        cases = _load_cases_file(Path(cases_file))
        print(f"CASES_FILE n={len(cases)} path={cases_file}", flush=True)
    elif sample_n.isdigit() and int(sample_n) > 0:
        frozen = dump_sample(int(sample_n), seed=sample_seed, ops_root=OPS_ROOT)
        sample_path = OUT / "sample.json"
        sample_path.write_text(
            json.dumps(frozen, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        cases = list(frozen["cases"])
        print(
            f"SAMPLE n={len(cases)} seed={sample_seed} alloc="
            f"{frozen['alloc']} eligible={frozen['eligible_n']} "
            f"families={frozen['sample_by_family']} wrote={sample_path}",
            flush=True,
        )
        if dump_only:
            for c in cases:
                print(f"  {c['rel']} {c['arch']}", flush=True)
            print("DUMP_SAMPLE_OK", flush=True)
            return 0
    else:
        print("Set UO_GEN_SAMPLE, UO_GEN_CASES_FILE, or UO_GEN_ONLY", flush=True)
        return 2
    for c in cases:
        print(f"  {c['rel']} {c.get('arch')}", flush=True)

    doc: dict[str, Any] = {
        "schema": "uo-init-generalization/v1",
        "date": time.strftime("%Y-%m-%d"),
        "profile": {
            "UO_INIT_PROFILE": os.environ.get("UO_INIT_PROFILE", "fast(default)"),
            "cpu_count": os.cpu_count(),
            "ops_root": str(OPS_ROOT),
            "allow_unverified_scope": os.environ.get("UO_TEST_ALLOW_UNVERIFIED_SCOPE", ""),
            "out": str(OUT),
            "sample_n": sample_n or len(cases),
            "sample_seed": sample_seed,
            "cases_file": cases_file,
            "exclude_n": len(_rel_items("UO_GEN_EXCLUDE")),
            "exclude_file": os.environ.get("UO_GEN_EXCLUDE_FILE", ""),
        },
        "cases": [],
    }
    seed = OUT / "results_partial.json"
    if not seed.is_file():
        seed = OUT / "results.json"
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
    max_raw = str(os.environ.get("UO_GEN_MAX") or "").strip()
    max_n = int(max_raw) if max_raw.isdigit() and int(max_raw) > 0 else 0
    ran = 0
    t_all = time.perf_counter()
    for case in cases:
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
                    "source_api": noise.get("source_api"),
                    "precision_gaps": noise.get("precision_gaps"),
                    "kernel_api": locate.get("kernel_api"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        _write_summary(doc)
        ran += 1
        if max_n and ran >= max_n:
            print(json.dumps({"stop": "UO_GEN_MAX", "ran": ran}), flush=True)
            break

    doc["elapsed_s"] = round(time.perf_counter() - t_all, 3)
    doc["ok"] = all(bool(c.get("ok")) for c in doc["cases"] if not c.get("audit_only"))
    doc["blockers"] = rank_blockers(doc.get("cases") or [])
    _save(doc)
    _write_summary(doc)
    print("BLOCKERS", json.dumps(doc["blockers"], ensure_ascii=False), flush=True)
    print("ALL_DONE", json.dumps({"ok": doc["ok"], "elapsed_s": doc["elapsed_s"]}), flush=True)
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
