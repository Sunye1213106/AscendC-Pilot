"""扫描 confirmed scope，一次性输出 ir/macro_facts.yaml。

宏合同是 AscendC 框架语义权威；源码 invocation 是项目事实权威。
第一版 expansion_status 固定为 invocation_only。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.host_contract_schema import make_evidence, stable_id
from uo.scripts.macro_token_scanner import (
    extract_balanced_paren,
    line_of,
    parse_chained_methods,
    scan_invocations,
)

FACTS_VERSION = "1.0.0"
_CONTRACTS_PATH = (
    Path(__file__).resolve().parents[1] / "resources" / "ascendc_macro_contracts.yaml"
)

# 仅投影到 entrypoint 的宏（其余留在 macro_facts）
ENTRYPOINT_PROJECTION_MACROS = frozenset(
    {
        "REG_OP",
        "IMPL_OP_OPTILING",
        "DEVICE_IMPL_OP_OPTILING",
        "REGISTER_TILING_TEMPLATE",
        "REGISTER_TILING_TEMPLATE_WITH_ARCH",
    }
)


def contracts_path() -> Path:
    return _CONTRACTS_PATH


def load_macro_contracts(path: Path | None = None) -> dict[str, Any]:
    data = read_yaml(path or _CONTRACTS_PATH) or {}
    return data if isinstance(data, dict) else {}


def list_contracts(path: Path | None = None) -> list[dict[str, Any]]:
    data = load_macro_contracts(path)
    contracts = data.get("contracts") or []
    return [c for c in contracts if isinstance(c, dict) and c.get("name")]


def macro_contracts_hash(path: Path | None = None) -> str:
    p = path or _CONTRACTS_PATH
    raw = p.read_bytes() if p.is_file() else b""
    return hashlib.sha256(raw).hexdigest()[:16]


def _normalize_args(
    raw_args: list[str],
    argument_roles: dict[str, Any] | None,
) -> dict[str, Any]:
    roles = argument_roles or {}
    out: dict[str, Any] = {"positional": list(raw_args), "by_role": {}}
    for idx, arg in enumerate(raw_args):
        role = roles.get(idx) or roles.get(str(idx))
        if role:
            out["by_role"][str(role)] = arg
    return out


def _confirmed_source_files(uo_root: Path, repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    # 优先 ir/scope_confirmed.yaml（测试与显式覆盖），再查 runs/*/scope
    candidates: list[Path] = [
        uo_root / "ir" / "scope_confirmed.yaml",
        uo_root / "scope" / "scope_confirmed.yaml",
    ]
    runs = uo_root / "runs"
    if runs.is_dir():
        found = sorted(
            runs.glob("*/scope/scope_confirmed.yaml"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(found)
    for cand in candidates:
        if not cand.is_file():
            continue
        data = read_yaml(cand) or {}
        files = data.get("confirmed_source_files") or data.get("confirmed_file_list") or []
        for item in files:
            if isinstance(item, dict):
                rel = str(item.get("path") or item.get("file_path") or "")
            else:
                rel = str(item or "")
            if not rel:
                continue
            path = Path(rel)
            if not path.is_absolute():
                path = repo_root / rel
            if path.is_file():
                paths.append(path)
        if paths:
            break
    if not paths:
        for sub in ("op_host", "op_kernel", "op_graph"):
            directory = repo_root / sub
            if directory.is_dir():
                paths.extend(sorted(directory.rglob("*.cpp")))
                paths.extend(sorted(directory.rglob("*.h")))
                paths.extend(sorted(directory.rglob("*.hpp")))
    unique: dict[str, Path] = {}
    for path in paths:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        unique.setdefault(key, path)
    return sorted(unique.values(), key=lambda p: str(p).replace("\\", "/"))


def _relative_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return path.as_posix().replace("\\", "/")


def _source_snapshot_hash(source_files: list[Path], repo_root: Path) -> str:
    rows: list[dict[str, Any]] = []
    for path in source_files:
        try:
            stat = path.stat()
            rows.append(
                {
                    "path": _relative_path(path, repo_root),
                    "size": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns),
                }
            )
        except OSError:
            rows.append({"path": _relative_path(path, repo_root), "missing": True})
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def extract_macro_facts(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
    compile_context_id: str = "",
    source_files: list[Path] | None = None,
) -> dict[str, Any]:
    """扫描源码，写出 ir/macro_facts.yaml。"""
    t0 = time.perf_counter()
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    contracts = list_contracts()
    by_name = {str(c["name"]): c for c in contracts}
    names = list(by_name.keys())
    contracts_h = macro_contracts_hash()

    files = source_files or _confirmed_source_files(root, repo_root)
    snapshot = _source_snapshot_hash(files, repo_root)

    invocations: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unresolved.append(
                {
                    "reason_code": "SOURCE_READ_FAILED",
                    "file_path": _relative_path(path, repo_root),
                    "message": str(exc)[:200],
                }
            )
            continue
        rel = _relative_path(path, repo_root)
        scanned = scan_invocations(text, names)
        # 展开 ARGS_DECL 内部嵌套的 BOOL/UINT DECL（外层占用会遮蔽）
        nested_extra: list[dict[str, Any]] = []
        for inv in scanned:
            if inv.get("macro") != "ASCENDC_TPL_ARGS_DECL":
                continue
            open_idx = text.find("(", int(inv["start_index"]))
            span = extract_balanced_paren(text, open_idx) if open_idx >= 0 else None
            if not span:
                continue
            inner = scan_invocations(
                span.inside,
                ["ASCENDC_TPL_BOOL_DECL", "ASCENDC_TPL_UINT_DECL"],
            )
            base_line = int(inv["start_line"])
            for nin in inner:
                # remap lines relative to outer file
                abs_idx = open_idx + 1 + int(nin["start_index"])
                nin["start_line"] = line_of(text, abs_idx)
                nin["end_line"] = line_of(text, abs_idx)
                nin["start_index"] = abs_idx
                nested_extra.append(nin)
        scanned.extend(nested_extra)
        for inv in scanned:
            macro = str(inv["macro"])
            contract = by_name[macro]
            raw_args = list(inv.get("raw_args") or [])
            normalized = _normalize_args(raw_args, contract.get("argument_roles"))
            chained: list[dict[str, Any]] = []
            if contract.get("invocation_style") == "chained_dsl":
                chained = parse_chained_methods(text, int(inv["end_index"]))
            ev = make_evidence(
                file_path=rel,
                start_line=int(inv["start_line"]),
                end_line=int(inv.get("end_line") or inv["start_line"]),
                extractor="ascendc_macro_facts",
                extractor_version=FACTS_VERSION,
                evidence_level="macro_contract_fact",
                source_snapshot_hash=snapshot,
            )
            evidence.append(ev)
            fact_id = stable_id(
                macro, rel, inv["start_line"], raw_args, prefix="MF:"
            )
            fact: dict[str, Any] = {
                "fact_id": fact_id,
                "macro": macro,
                "semantic_kind": contract.get("semantic_kind"),
                "contract_class": contract.get("contract_class"),
                "version_scope": contract.get("version_scope"),
                "composition_strategy": contract.get("composition_strategy"),
                "file_path": rel,
                "start_line": int(inv["start_line"]),
                "end_line": int(inv.get("end_line") or inv["start_line"]),
                "raw_args": raw_args,
                "normalized_args": normalized,
                "chained_methods": chained,
                "active_condition": None,
                "contract_ref": macro,
                "evidence_ref": ev["id"],
                "expansion_status": "invocation_only",
                "fact_kind": "macro_invocation",
                "compile_context_id": compile_context_id,
                "architecture": architecture,
                "materializer_handler": (contract.get("materializer") or {}).get("handler"),
                "emitted_fact_types": list(contract.get("emitted_fact_types") or []),
            }
            invocations.append(fact)

    invocations.sort(key=lambda x: (x["file_path"], x["start_line"], x["macro"]))
    # 去重：同一宏同一位置只保留一条（嵌套展开可能重复）
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for inv in invocations:
        key = (inv.get("macro"), inv.get("file_path"), inv.get("start_line"), tuple(inv.get("raw_args") or []))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(inv)
    invocations = deduped
    doc: dict[str, Any] = {
        "version": FACTS_VERSION,
        "source_snapshot_hash": snapshot,
        "architecture": architecture,
        "compile_context_id": compile_context_id,
        "macro_contracts_hash": contracts_h,
        "op_name": op_name,
        "invocations": invocations,
        "evidence": evidence,
        "unresolved": unresolved,
        "counts": {
            "invocations": len(invocations),
            "source_files": len(files),
            "by_macro": _count_by_macro(invocations),
        },
        "timing_ms": int((time.perf_counter() - t0) * 1000),
    }
    write_yaml(ir_dir / "macro_facts.yaml", doc)
    return doc


def _count_by_macro(invocations: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for inv in invocations:
        name = str(inv.get("macro") or "")
        out[name] = out.get(name, 0) + 1
    return out


def load_macro_facts(uo_root: Path) -> dict[str, Any]:
    return read_yaml(uo_root / "ir" / "macro_facts.yaml") or {}
