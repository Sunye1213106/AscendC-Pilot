"""从 macro_facts 提取 DeclaredKeySpace（不再独立扫源码）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts.ascendc_macro_facts import load_macro_facts
from uo.scripts.host_compile_context import load_host_compile_context
from uo.scripts.host_contract_schema import make_entity, make_evidence

DECL_VERSION = "1.1.0"


def extract_declared_key_space(
    facts: dict[str, Any],
    *,
    compile_context_id: str,
    architecture: str,
) -> dict[str, Any]:
    """解析 ASCENDC_TPL_ARGS_DECL 嵌套的 BOOL/UINT 声明。

    按 ARGS_DECL 作用域分组 dimensions，避免全局 flatten 导致 arity 误判。
    """
    dimensions: list[dict[str, Any]] = []
    dimension_groups: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    invocations = list(facts.get("invocations") or [])
    args_decl = [inv for inv in invocations if inv.get("macro") == "ASCENDC_TPL_ARGS_DECL"]
    bool_uint = [
        inv
        for inv in invocations
        if inv.get("macro") in {"ASCENDC_TPL_BOOL_DECL", "ASCENDC_TPL_UINT_DECL"}
    ]

    # Group BOOL/UINT by nearest preceding ARGS_DECL in same file (by line)
    decl_scopes: list[dict[str, Any]] = []
    for inv in args_decl:
        decl_scopes.append(
            {
                "fact_id": inv.get("fact_id"),
                "file_path": str(inv.get("file_path") or ""),
                "start_line": int(inv.get("start_line") or 0),
                "operator_hint": list(
                    (inv.get("normalized_args") or {}).get("positional") or inv.get("raw_args") or []
                )[:1],
                "dimensions": [],
            }
        )

    def _pick_scope(inv: dict[str, Any]) -> dict[str, Any] | None:
        fp = str(inv.get("file_path") or "")
        line = int(inv.get("start_line") or 0)
        best = None
        best_line = -1
        for scope in decl_scopes:
            if scope["file_path"] != fp:
                continue
            if scope["start_line"] <= line and scope["start_line"] >= best_line:
                best = scope
                best_line = scope["start_line"]
        if best is None and decl_scopes:
            # fallback: single global scope if only one ARGS_DECL
            if len(decl_scopes) == 1:
                return decl_scopes[0]
        return best

    for inv in bool_uint:
        args = list((inv.get("normalized_args") or {}).get("positional") or inv.get("raw_args") or [])
        macro = str(inv.get("macro") or "")
        ev = make_evidence(
            file_path=str(inv.get("file_path") or ""),
            start_line=int(inv.get("start_line") or 0),
            end_line=int(inv.get("end_line") or 0),
            extractor="tiling_key_declaration",
            extractor_version=DECL_VERSION,
            evidence_level="macro_contract_fact",
        )
        evidence.append(ev)
        if macro == "ASCENDC_TPL_BOOL_DECL" and len(args) >= 1:
            name = args[0].strip()
            domain = [a.strip() for a in args[1:]] or ["0", "1"]
            kind = "bool"
            bit_width = 1
            selection_mode = "bool"
        elif macro == "ASCENDC_TPL_UINT_DECL" and len(args) >= 1:
            name = args[0].strip()
            bw_token = args[1].strip() if len(args) > 1 else ""
            selection_mode = args[2].strip() if len(args) > 2 else ""
            domain = [a.strip() for a in args[3:]]
            kind = "uint"
            digits = "".join(ch for ch in bw_token if ch.isdigit())
            bit_width = int(digits) if digits else 0
        else:
            unresolved.append(
                {
                    "reason_code": "TILING_KEY_DECL_ARGS_INCOMPLETE",
                    "macro": macro,
                    "message": "DECL 实参不足，跳过该维度声明",
                    "fact_id": inv.get("fact_id"),
                }
            )
            continue

        scope = _pick_scope(inv)
        ordinal_in_scope = len(scope["dimensions"]) if scope else len(dimensions)
        dim = {
            "ordinal": len(dimensions),  # flat list 全局连续，供 IR/smoke
            "scope_ordinal": ordinal_in_scope,
            "global_ordinal": len(dimensions),
            "dimension_name": name,
            "kind": kind,
            "bit_width": bit_width,
            "legal_domain": domain,
            "selection_mode": selection_mode,
            "active_condition": None,
            "compile_context_id": compile_context_id,
            "declaration_evidence": ev["id"],
            "macro_fact_id": inv.get("fact_id"),
            "args_decl_fact_id": (scope or {}).get("fact_id"),
            "file_path": str(inv.get("file_path") or ""),
        }
        dimensions.append(dim)
        if scope is not None:
            scope["dimensions"].append(dim)
        entities.append(
            make_entity(
                kind="KeyDimension",
                identity_key=f"KeyDimension:{dim['ordinal']}:{name}:{compile_context_id}",
                qualified_name=name,
                binding_time="kernel_compile_time",
                architecture=architecture,
                compile_context_id=compile_context_id,
                evidence_refs=[ev["id"]],
                extra=dim,
            )
        )

    for scope in decl_scopes:
        scope_ords = [d["scope_ordinal"] for d in scope["dimensions"]]
        if scope_ords and scope_ords != list(range(len(scope_ords))):
            unresolved.append(
                {
                    "reason_code": "TILING_KEY_ARITY_MISMATCH",
                    "message": "同一 ARGS_DECL 作用域内 dimension ordinal 非唯一连续",
                    "args_decl_fact_id": scope.get("fact_id"),
                }
            )
        dimension_groups.append(
            {
                "args_decl_fact_id": scope.get("fact_id"),
                "file_path": scope.get("file_path"),
                "operator_hint": scope.get("operator_hint"),
                "dimensions": list(scope["dimensions"]),
                "dimension_count": len(scope["dimensions"]),
            }
        )

    # If no ARGS_DECL but have BOOL/UINT, treat as one implicit group
    if not dimension_groups and dimensions:
        dimension_groups.append(
            {
                "args_decl_fact_id": None,
                "file_path": "",
                "operator_hint": [],
                "dimensions": list(dimensions),
                "dimension_count": len(dimensions),
            }
        )

    space_ent = make_entity(
        kind="DeclaredKeySpace",
        identity_key=f"DeclaredKeySpace:{compile_context_id}:{len(dimensions)}",
        qualified_name="declared_key_space",
        binding_time="build_time",
        architecture=architecture,
        compile_context_id=compile_context_id,
        extra={
            "dimension_count": len(dimensions),
            "args_decl_count": len(args_decl),
            "dimension_group_count": len(dimension_groups),
            "operator_hint": (
                list(dimension_groups[0].get("operator_hint") or []) if dimension_groups else []
            ),
        },
    )
    entities.insert(0, space_ent)

    return {
        "version": DECL_VERSION,
        "compile_context_id": compile_context_id,
        "architecture": architecture,
        "dimensions": dimensions,
        "dimension_groups": dimension_groups,
        "entities": entities,
        "evidence": evidence,
        "unresolved": unresolved,
    }


def build_tiling_key_declaration(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
) -> dict[str, Any]:
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ctx = load_host_compile_context(root)
    facts = load_macro_facts(root)
    return extract_declared_key_space(
        facts,
        compile_context_id=str(ctx.get("compile_context_id") or ""),
        architecture=architecture,
    )
