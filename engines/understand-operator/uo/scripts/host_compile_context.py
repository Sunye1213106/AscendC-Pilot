"""Host Compile Context：配置实例身份 + 预处理器活动区。

所有 MacroFact / Host Predicate / Tiling schema variant / 注册边
必须挂到同一个 compile_context_id。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.ascendc_macro_facts import (
    _confirmed_source_files,
    _relative_path,
    _source_snapshot_hash,
    load_macro_facts,
    macro_contracts_hash,
)
from uo.scripts.macro_regions import analyze_macros, valued_seed_defines

CONTEXT_VERSION = "1.0.0"

CONDITION_CLASSES = frozenset(
    {
        "BUILD_CONFIG",
        "ARCHITECTURE_CONFIG",
        "TILING_KEY_SYMBOL",
        "HOST_RUNTIME_VALUE",
        "UNKNOWN",
    }
)


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compute_compile_context_id(
    *,
    architecture: str,
    cann_version: str,
    include_paths_hash: str,
    defines_hash: str,
    macro_contracts_hash_value: str,
    source_snapshot_hash: str,
) -> str:
    return _hash_payload(
        {
            "architecture": architecture,
            "cann_version": cann_version,
            "include_paths_hash": include_paths_hash,
            "defines_hash": defines_hash,
            "macro_contracts_hash": macro_contracts_hash_value,
            "source_snapshot_hash": source_snapshot_hash,
        }
    )


def classify_condition(cond: str, *, architecture: str = "") -> str:
    """将 #if 条件粗分为 BUILD/ARCH/KEY/RUNTIME/UNKNOWN。"""
    text = (cond or "").strip()
    upper = text.upper()
    if not text:
        return "UNKNOWN"
    if any(tok in upper for tok in ("ASCENDC_TPL", "TILING_KEY", "TPL_BOOL", "TPL_UINT")):
        return "TILING_KEY_SYMBOL"
    if any(tok in upper for tok in ("ARCH", "DAV_", "ASCEND910", "__CCE_AICORE")):
        return "ARCHITECTURE_CONFIG"
    if architecture and architecture.upper().replace("ARCH", "") in upper:
        return "ARCHITECTURE_CONFIG"
    if any(tok in upper for tok in ("ASC_DEVKIT", "CANN", "BUILD", "VERSION", "TOOLCHAIN")):
        return "BUILD_CONFIG"
    if any(tok in text for tok in ("context", "GetAttr", "GetInput", "isTnd", "runtime")):
        return "HOST_RUNTIME_VALUE"
    # defined(X) without known class → UNKNOWN (retain both branches)
    return "UNKNOWN"


def _seed_defines_for_arch(architecture: str) -> dict[str, str | None]:
    seeds: dict[str, str | None] = {}
    arch = (architecture or "").strip()
    if arch:
        seeds[arch.upper()] = "1"
        # common patterns: arch35 → ASCEND_ARCH35-like soft flags left unset
        digits = "".join(ch for ch in arch if ch.isdigit())
        if digits:
            seeds[f"ASCEND_ARCH{digits}"] = "1"
    return seeds


def _try_clang_adapter(
    repo_root: Path,
    source_files: list[Path],
) -> dict[str, Any]:
    """可选 Clang；失败不阻塞，只记录降级原因。"""
    try:
        from uo.scripts.adapters.clang_host_adapter import try_extract_host_ast_facts

        return try_extract_host_ast_facts(repo_root, source_files)
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": False,
            "status": "degraded",
            "reason": f"clang_adapter_exception:{exc}"[:300],
            "facts": [],
        }


def extract_host_compile_context(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    cann_version: str = "",
    uo_root: Path | None = None,
    seed_defines: dict[str, str | None] | None = None,
    platform_defines: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """写出 ir/host_compile_context.yaml。"""
    t0 = time.perf_counter()
    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.source_include_closure import expand_local_include_closure

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    confirmed = _confirmed_source_files(root, repo_root)
    snapshot = _source_snapshot_hash(confirmed, repo_root)
    contracts_h = macro_contracts_hash()

    seeds = dict(seed_defines or {})
    seeds.update(_seed_defines_for_arch(architecture))
    platform = dict(platform_defines or {})
    defines_hash = _hash_payload({"seed": seeds, "platform": platform})

    include_result = expand_local_include_closure(
        repo_root, confirmed, architecture=architecture
    )
    include_doc = include_result.as_dict(repo_root)
    include_hash = _hash_payload(include_doc.get("files") or [])

    compile_context_id = compute_compile_context_id(
        architecture=architecture,
        cann_version=cann_version,
        include_paths_hash=include_hash,
        defines_hash=defines_hash,
        macro_contracts_hash_value=contracts_h,
        source_snapshot_hash=snapshot,
    )

    active_regions: list[dict[str, Any]] = []
    unknown_conditions: list[dict[str, Any]] = []
    tiling_implementations: list[dict[str, Any]] = []
    registration_edges: list[dict[str, Any]] = []

    merged_seeds = valued_seed_defines({**seeds, **platform})

    for path in confirmed:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _relative_path(path, repo_root)
        analysis = analyze_macros(text, seed_defines=merged_seeds)
        for lo, hi in analysis.active_ranges or []:
            active_regions.append(
                {
                    "file_path": rel,
                    "start_line": lo,
                    "end_line": hi,
                    "compile_context_id": compile_context_id,
                }
            )
        for directive in analysis.directives:
            if directive.kind not in {"if", "ifdef", "ifndef", "elif"}:
                continue
            cond = directive.condition or directive.name or ""
            klass = classify_condition(cond, architecture=architecture)
            if directive.eval_result is None or klass == "UNKNOWN":
                unknown_conditions.append(
                    {
                        "file_path": rel,
                        "line": directive.line,
                        "condition": cond,
                        "condition_class": klass if klass in CONDITION_CLASSES else "UNKNOWN",
                        "binding_time": "build_time",
                        "selection_effect": ["filters_source_region"],
                        "retain_both_branches": True,
                        "compile_context_id": compile_context_id,
                    }
                )

    # 从 macro_facts 收集注册与 tiling implementation（若已存在）
    facts = load_macro_facts(root)
    for inv in facts.get("invocations") or []:
        if not isinstance(inv, dict):
            continue
        macro = str(inv.get("macro") or "")
        if macro in {
            "REGISTER_TILING_TEMPLATE",
            "REGISTER_TILING_TEMPLATE_WITH_ARCH",
            "IMPL_OP_OPTILING",
            "DEVICE_IMPL_OP_OPTILING",
            "REG_OP",
        }:
            registration_edges.append(
                {
                    "macro_fact_id": inv.get("fact_id"),
                    "macro": macro,
                    "file_path": inv.get("file_path"),
                    "start_line": inv.get("start_line"),
                    "compile_context_id": compile_context_id,
                    "binding_time": "build_time",
                    "selection_effect": ["selects_tiling_implementation"]
                    if "TEMPLATE" in macro
                    else ["filters_source_region"],
                }
            )
        if macro in {"REGISTER_TILING_TEMPLATE", "REGISTER_TILING_TEMPLATE_WITH_ARCH"}:
            args = list((inv.get("normalized_args") or {}).get("positional") or [])
            if len(args) >= 2:
                tiling_implementations.append(
                    {
                        "template_class": args[1].strip(),
                        "operator_type": args[0].strip(),
                        "architecture": args[2].strip() if len(args) > 2 else architecture,
                        "macro_fact_id": inv.get("fact_id"),
                        "compile_context_id": compile_context_id,
                        "binding_time": "build_time",
                    }
                )

    clang = _try_clang_adapter(repo_root, confirmed)

    doc: dict[str, Any] = {
        "version": CONTEXT_VERSION,
        "compile_context_id": compile_context_id,
        "architecture": architecture,
        "cann_version": cann_version,
        "confirmed_source_files": [_relative_path(p, repo_root) for p in confirmed],
        "include_closure": include_doc,
        "include_paths_hash": include_hash,
        "seed_defines": seeds,
        "platform_defines": platform,
        "defines_hash": defines_hash,
        "macro_contracts_hash": contracts_h,
        "source_snapshot_hash": snapshot,
        "active_preprocessor_regions": active_regions,
        "unknown_preprocessor_conditions": unknown_conditions,
        "tiling_implementations": tiling_implementations,
        "registration_edges": registration_edges,
        "clang_adapter": {
            "enabled": bool(clang.get("enabled")),
            "status": clang.get("status"),
            "reason": clang.get("reason"),
            "fact_count": len(clang.get("facts") or []),
        },
        "degraded_reasons": []
        if clang.get("status") == "ok"
        else ([str(clang.get("reason") or "clang_disabled")]),
        "timing_ms": int((time.perf_counter() - t0) * 1000),
    }
    write_yaml(ir_dir / "host_compile_context.yaml", doc)
    return doc


def load_host_compile_context(uo_root: Path) -> dict[str, Any]:
    return read_yaml(uo_root / "ir" / "host_compile_context.yaml") or {}
