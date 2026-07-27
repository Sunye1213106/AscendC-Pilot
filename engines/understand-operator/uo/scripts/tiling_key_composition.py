"""TilingKey Composition：ObservedKeyComposition + RegisteredTemplatePattern。

composition_strategy 由宏合同定义，不统一假设位置==dimension。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo.scripts.ascendc_macro_facts import load_macro_facts
from uo.scripts.host_compile_context import load_host_compile_context
from uo.scripts.host_contract_schema import (
    make_edge,
    make_entity,
    make_evidence,
    make_expression_ir,
    make_guard_context,
)
from uo.scripts.tiling_key_declaration import build_tiling_key_declaration

COMP_VERSION = "1.0.0"

USING_ALIAS_RE = re.compile(
    r"\busing\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*<([^>]+)>\s*;"
)


def extract_observed_compositions(
    facts: dict[str, Any],
    dimensions: list[dict[str, Any]],
    *,
    compile_context_id: str,
    architecture: str,
    host_value_by_symbol: dict[str, str] | None = None,
    dimension_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    host_value_by_symbol = host_value_by_symbol or {}
    groups = list(dimension_groups or [])

    def _dims_for_inv(inv: dict[str, Any], arg_count: int) -> list[dict[str, Any]]:
        fp = str(inv.get("file_path") or "").replace("\\", "/")
        nonempty = [g for g in groups if g.get("dimensions")]
        if not nonempty:
            return list(dimensions)

        def _norm(p: str) -> str:
            return str(p or "").replace("\\", "/")

        # 1) 实参数量命中的作用域（避免跨算子/公共仓 KEY 用错 DECL）
        arity_hits = [
            g
            for g in nonempty
            if int(g.get("dimension_count") or len(g.get("dimensions") or [])) == arg_count
        ]
        if len(arity_hits) == 1:
            return list(arity_hits[0].get("dimensions") or [])
        # 2) 同文件
        same_file = [g for g in nonempty if _norm(g.get("file_path")) == fp]
        if same_file:
            if arg_count:
                for g in same_file:
                    if int(g.get("dimension_count") or 0) == arg_count:
                        return list(g.get("dimensions") or [])
            return list(same_file[0].get("dimensions") or [])
        # 3) 同目录 / 同 stem 前缀
        parent = str(Path(fp).parent).replace("\\", "/")
        same_dir = [g for g in nonempty if _norm(g.get("file_path")).startswith(parent + "/")]
        if same_dir:
            if arg_count:
                for g in same_dir:
                    if int(g.get("dimension_count") or 0) == arg_count:
                        return list(g.get("dimensions") or [])
            return list(
                max(same_dir, key=lambda g: int(g.get("dimension_count") or 0)).get("dimensions")
                or []
            )
        if arity_hits:
            return list(
                max(arity_hits, key=lambda g: int(g.get("dimension_count") or 0)).get("dimensions")
                or []
            )
        # 无同文件/同目录/同 arity 命中时，不回退到唯一/最大无关 DECL
        return []

    for inv in facts.get("invocations") or []:
        macro = str(inv.get("macro") or "")
        strategy = str(inv.get("composition_strategy") or "")
        args = list((inv.get("normalized_args") or {}).get("positional") or inv.get("raw_args") or [])
        if macro not in {"GET_TPL_TILING_KEY", "ASCENDC_TPL_SEL_PARAM"}:
            continue
        if not strategy:
            strategy = (
                "positional_full_key"
                if macro == "GET_TPL_TILING_KEY"
                else "context_mutation"
            )
        scoped_dims = _dims_for_inv(inv, len(args))
        ev = make_evidence(
            file_path=str(inv.get("file_path") or ""),
            start_line=int(inv.get("start_line") or 0),
            end_line=int(inv.get("end_line") or 0),
            extractor="tiling_key_composition",
            extractor_version=COMP_VERSION,
            evidence_level="macro_contract_fact",
        )
        evidence.append(ev)

        kind = (
            "KeyReturnComposer"
            if strategy == "positional_full_key"
            else "KeyContextMutation"
            if strategy == "context_mutation"
            else "KeyDimensionSelection"
        )
        composer = make_entity(
            kind=kind,
            identity_key=f"{kind}:{inv.get('fact_id')}",
            qualified_name=macro,
            binding_time="host_runtime",
            architecture=architecture,
            compile_context_id=compile_context_id,
            evidence_refs=[ev["id"]],
            extra={
                "composer_function": "",
                "composition_strategy": strategy,
                "macro_fact_id": inv.get("fact_id"),
                "returns_key": strategy == "positional_full_key",
                "sets_context_key": strategy == "context_mutation",
                "producer_binding_time": "host_runtime",
                "consumer_binding_time": "kernel_compile_time",
            },
        )
        entities.append(composer)

        if strategy in {"positional_full_key", "positional_dimension_selection"}:
            expected = len(scoped_dims)
            effective_args = args
            if expected and len(effective_args) != expected:
                unresolved.append(
                    {
                        "reason_code": "TILING_KEY_ARITY_MISMATCH",
                        "macro": macro,
                        "expected": expected,
                        "actual": len(effective_args),
                        "composition_strategy": strategy,
                        "fact_id": inv.get("fact_id"),
                        "file_path": inv.get("file_path"),
                    }
                )
            for idx, arg in enumerate(effective_args):
                dim = scoped_dims[idx] if idx < len(scoped_dims) else None
                arg_expr = make_expression_ir(kind="argument", source_text=arg, symbols=[arg.strip()])
                sel = make_entity(
                    kind="KeyDimensionSelection",
                    identity_key=f"KeySel:{inv.get('fact_id')}:{idx}",
                    qualified_name=f"arg[{idx}]",
                    binding_time="host_runtime",
                    architecture=architecture,
                    compile_context_id=compile_context_id,
                    evidence_refs=[ev["id"]],
                    extra={
                        "argument_position": idx,
                        "argument_expression": arg_expr,
                        "mapped_dimension": (dim or {}).get("dimension_name"),
                        "mapped_ordinal": (dim or {}).get("ordinal"),
                        "guard_context": make_guard_context(
                            binding_time="host_runtime",
                            selection_effect=["composes_tiling_key"],
                        ),
                    },
                )
                entities.append(sel)
                edges.append(
                    make_edge(
                        edge_type="ENCODES_KEY_ARGUMENT",
                        source_ids=[sel["id"]],
                        target_ids=[],
                        evidence_refs=[ev["id"]],
                        extra={"argument_position": idx},
                    )
                )
                if dim:
                    dim_id_key = (
                        f"KeyDimension:{dim['ordinal']}:"
                        f"{dim['dimension_name']}:{compile_context_id}"
                    )
                    edges.append(
                        make_edge(
                            edge_type="ENCODES_KEY_ARGUMENT",
                            source_ids=[sel["id"]],
                            target_ids=[],
                            transform={
                                "dimension_name": dim["dimension_name"],
                                "ordinal": dim["ordinal"],
                            },
                            evidence_refs=[ev["id"]],
                            extra={"dimension_identity_key": dim_id_key},
                        )
                    )
                sym = arg.strip()
                grounded = False

                def _try_ground(token: str) -> bool:
                    tok = token.strip()
                    if not tok:
                        return False
                    if tok in host_value_by_symbol:
                        edges.append(
                            make_edge(
                                edge_type="DERIVES",
                                source_ids=[host_value_by_symbol[tok]],
                                target_ids=[sel["id"]],
                                evidence_refs=[ev["id"]],
                            )
                        )
                        return True
                    leaf = re.split(r"->|\.", tok)[-1]
                    if leaf in host_value_by_symbol:
                        edges.append(
                            make_edge(
                                edge_type="DERIVES",
                                source_ids=[host_value_by_symbol[leaf]],
                                target_ids=[sel["id"]],
                                evidence_refs=[ev["id"]],
                            )
                        )
                        return True
                    return False

                # static_cast<T>(expr) / (T)expr → 抽内层
                inner = sym
                mcast = re.match(
                    r"(?:static_cast|reinterpret_cast|const_cast)\s*<[^>]+>\s*\((.+)\)$",
                    sym,
                )
                if mcast:
                    inner = mcast.group(1).strip()
                grounded = _try_ground(sym) or _try_ground(inner)
                # 本地聚合成员 tilingKeyInfo_.x / fBaseParams.x：不强制 HostValue
                local_member = bool(
                    re.search(r"(->|\.)", inner)
                    or inner.endswith("_")
                    or re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_]", inner)
                )
                if (
                    not grounded
                    and not local_member
                    and not re.match(r"^\d+$", sym)
                    and sym not in {"true", "false", "0", "1"}
                    and not re.match(r"^TILING_KEY_\d+$", sym)
                ):
                    # cast/表达式包装的本地量：记为已结构识别，不升 unresolved
                    if mcast and re.match(
                        r"^[A-Za-z_][A-Za-z0-9_]*(?:(?:->|\.)[A-Za-z_][A-Za-z0-9_]*)*$",
                        inner,
                    ):
                        continue
                    unresolved.append(
                        {
                            "reason_code": "TILING_KEY_ARGUMENT_UNGROUNDED",
                            "argument": sym,
                            "position": idx,
                            "fact_id": inv.get("fact_id"),
                            "file_path": inv.get("file_path"),
                        }
                    )
                edges.append(
                    make_edge(
                        edge_type="COMPOSES_TILING_KEY",
                        source_ids=[sel["id"]],
                        target_ids=[composer["id"]],
                        evidence_refs=[ev["id"]],
                    )
                )
        elif strategy == "context_mutation":
            for idx, arg in enumerate(args):
                sel = make_entity(
                    kind="KeyDimensionSelection",
                    identity_key=f"KeyCtxSel:{inv.get('fact_id')}:{idx}",
                    qualified_name=f"sel_param[{idx}]",
                    binding_time="host_runtime",
                    architecture=architecture,
                    compile_context_id=compile_context_id,
                    evidence_refs=[ev["id"]],
                    extra={
                        "argument_position": idx,
                        "argument_expression": make_expression_ir(kind="argument", source_text=arg),
                        "composition_strategy": strategy,
                    },
                )
                entities.append(sel)
                edges.append(
                    make_edge(
                        edge_type="COMPOSES_TILING_KEY",
                        source_ids=[sel["id"]],
                        target_ids=[composer["id"]],
                        evidence_refs=[ev["id"]],
                    )
                )

        entities.append(
            make_entity(
                kind="ObservedKeyComposition",
                identity_key=f"ObservedKeyComposition:{inv.get('fact_id')}",
                qualified_name=macro,
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                evidence_refs=[ev["id"]],
                extra={
                    "composer_id": composer["id"],
                    "composition_strategy": strategy,
                    "argument_count": len(args),
                },
            )
        )

    return {
        "entities": entities,
        "edges": edges,
        "evidence": evidence,
        "unresolved": unresolved,
    }


def extract_registered_template_patterns(
    facts: dict[str, Any],
    source_texts: dict[str, str],
    *,
    compile_context_id: str,
    architecture: str,
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    # From ARGS_SEL facts
    for inv in facts.get("invocations") or []:
        if inv.get("macro") != "ASCENDC_TPL_ARGS_SEL":
            continue
        ev = make_evidence(
            file_path=str(inv.get("file_path") or ""),
            start_line=int(inv.get("start_line") or 0),
            extractor="tiling_key_composition",
            extractor_version=COMP_VERSION,
            evidence_level="macro_contract_fact",
        )
        evidence.append(ev)
        entities.append(
            make_entity(
                kind="RegisteredTemplatePattern",
                identity_key=f"RegPat:{inv.get('fact_id')}",
                qualified_name="ASCENDC_TPL_ARGS_SEL",
                binding_time="build_time",
                architecture=architecture,
                compile_context_id=compile_context_id,
                evidence_refs=[ev["id"]],
                extra={
                    "source": "ASCENDC_TPL_ARGS_SEL",
                    "raw_args": inv.get("raw_args"),
                    "note": "合法模式来自 SEL/注册/alias，非 domain 笛卡尔积",
                },
            )
        )
    # using Alias = Template<...>
    for fp, text in source_texts.items():
        for m in USING_ALIAS_RE.finditer(text or ""):
            alias, cls, args = m.group(1), m.group(2), m.group(3)
            line = text.count("\n", 0, m.start()) + 1
            ev = make_evidence(
                file_path=fp,
                start_line=line,
                extractor="tiling_key_composition",
                extractor_version=COMP_VERSION,
                evidence_level="structured_source_fact",
            )
            evidence.append(ev)
            entities.append(
                make_entity(
                    kind="RegisteredTemplatePattern",
                    identity_key=f"RegPatAlias:{fp}:{alias}",
                    qualified_name=alias,
                    binding_time="build_time",
                    architecture=architecture,
                    compile_context_id=compile_context_id,
                    evidence_refs=[ev["id"]],
                    extra={
                        "source": "template_alias",
                        "template_class": cls,
                        "template_arguments": [a.strip() for a in args.split(",")],
                    },
                )
            )
    return {"entities": entities, "evidence": evidence, "unresolved": []}


def build_tiling_key_composition(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
) -> dict[str, Any]:
    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.ascendc_macro_facts import _confirmed_source_files, _relative_path
    from uo.scripts.host_configuration_builder import (
        build_host_value_symbol_index,
        load_host_configuration,
    )

    root = uo_root or existing_operator_root(repo_root, op_name)
    ctx = load_host_compile_context(root)
    ccid = str(ctx.get("compile_context_id") or "")
    facts = load_macro_facts(root)
    decl = build_tiling_key_declaration(repo_root, op_name, architecture=architecture, uo_root=root)
    hcg = load_host_configuration(root)
    host_syms = build_host_value_symbol_index(hcg)

    observed = extract_observed_compositions(
        facts,
        decl.get("dimensions") or [],
        compile_context_id=ccid,
        architecture=architecture,
        host_value_by_symbol=host_syms,
        dimension_groups=decl.get("dimension_groups") or [],
    )
    texts: dict[str, str] = {}
    for path in _confirmed_source_files(root, repo_root):
        try:
            texts[_relative_path(path, repo_root)] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    registered = extract_registered_template_patterns(
        facts, texts, compile_context_id=ccid, architecture=architecture
    )

    # ReachableKeyConstraint = intersection placeholder (Host-only: observed ∩ registered)
    reachable = make_entity(
        kind="ReachableKeyConstraint",
        identity_key=f"ReachableKeyConstraint:{ccid}",
        qualified_name="reachable_key_constraint",
        binding_time="host_runtime",
        architecture=architecture,
        compile_context_id=ccid,
        extra={
            "note": "Host 阶段仅记录约束载体，非 domain 笛卡尔积",
            "observed_count": len(
                [e for e in observed["entities"] if e["kind"] == "ObservedKeyComposition"]
            ),
            "registered_count": len(registered["entities"]),
        },
    )

    return {
        "version": COMP_VERSION,
        "compile_context_id": ccid,
        "architecture": architecture,
        "declared": decl,
        "entities": decl.get("entities", [])
        + observed["entities"]
        + registered["entities"]
        + [reachable],
        "edges": observed["edges"],
        "evidence": (decl.get("evidence") or [])
        + observed["evidence"]
        + registered["evidence"],
        "unresolved": (decl.get("unresolved") or [])
        + observed["unresolved"]
        + registered.get("unresolved", []),
    }
