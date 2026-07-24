from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, snippet, stable_id, write_yaml
from uo.scripts.extract_plan_io import load_extract_plan, plan_aliases, plan_derived_roots
from uo.scripts.function_body import find_function_body, iter_function_defs
from uo.scripts.resolve_entrypoints import entrypoint_units, load_entrypoint_graph
from uo.scripts.semantic_identity import (
    infer_specialization_kind,
    mint_method_identity,
    mint_scoped_node_id,
    mint_symbol_identity,
    parse_template_arity,
)
from uo.scripts.macro_regions import (
    analyze_macros,
    classify_macro_condition,
    merge_defines,
    valued_seed_defines,
)
from uo.scripts.provenance import (
    classify_compile_determinant,
    is_key_symbol,
    load_key_dimension_index,
    load_tilingkey_space,
)

IF_CONSTEXPR_RE = re.compile(r"\bif\s*constexpr\s*\((.+?)\)", re.DOTALL)
IF_RUNTIME_RE = re.compile(r"\bif\s*\((.+?)\)", re.DOTALL)
# Kept for tests / callers; extraction now uses macro_regions.analyze_macros.
MACRO_IF_RE = re.compile(r"^\s*#\s*if(?:n?def)?\s+(.+)$", re.MULTILINE)
TILING_DATA_READ_RE = re.compile(
    r"tilingData(?:->|\.)([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)"
)
# Generic defaults; plan.derived_roots may extend roots at runtime.
_DEFAULT_DERIVED_ROOTS = ("constInfo", "commonConstInfo", "deterConstInfo", "runInfo")


def _derived_read_re(extra_roots: set[str] | None = None) -> re.Pattern[str]:
    roots = set(_DEFAULT_DERIVED_ROOTS) | (extra_roots or set())
    # Only accept identifier-like roots (no FAG-specific hardcoding).
    safe = sorted({r for r in roots if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", r)})
    if not safe:
        safe = list(_DEFAULT_DERIVED_ROOTS)
    alt = "|".join(re.escape(r) for r in safe)
    return re.compile(rf"(?:{alt})(?:->|\.)([A-Za-z0-9_\.]+)")


KERNEL_DERIVED_READ_RE = _derived_read_re()
# field == ENUM / field == Type::ENUM / field == static_cast<T>(Type::ENUM)
FIELD_EQ_ENUM_RE = re.compile(
    r"(?:(?:this\s*->\s*)?(?:[A-Za-z_]\w*\s*(?:\.|->)\s*)*)"
    r"([A-Za-z_]\w*)\s*==\s*"
    r"(?:static_cast\s*<[^>]+>\s*\(\s*)?"
    r"(?:([A-Za-z_]\w*)\s*::\s*)?"
    r"([A-Z][A-Z0-9_]{1,})\s*\)?"
)
FIELD_EQ_INT_RE = re.compile(
    r"(?:(?:this\s*->\s*)?(?:[A-Za-z_]\w*\s*(?:\.|->)\s*)*)"
    r"([A-Za-z_]\w*)\s*==\s*([0-9]+)\b"
)
# Keep this linear-time: no nested optional quantifiers (prior form catastrophic-backtracked
# on large kernel headers and hung build_layered_kb).
TDF_ASSIGN_RE = re.compile(
    r"(?<![.\w])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,6})\s*=\s*"
    r"tilingData(?:->|\.)([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){0,8})\s*;"
)
ENUM_CLASS_RE = re.compile(
    r"enum\s+class\s+([A-Za-z_]\w*)\s*(?::\s*[^{]+)?\{([^}]*)\}",
    re.DOTALL,
)
ENUM_MEMBER_RE = re.compile(
    r"([A-Za-z_]\w*)\s*(?:=\s*([0-9]+))?\s*(?:,|$)",
)
CONSTEXPR_INT_RE = re.compile(
    r"^\s*constexpr\s+(u?int(?:8|16|32|64)_t|int|unsigned(?:\s+int)?)\s+"
    r"([A-Z][A-Z0-9_]*)\s*=\s*([0-9]+)\s*;",
    re.MULTILINE,
)
LOOP_RE = re.compile(r"\bfor\s*\((.+?)\)", re.DOTALL)
OP_MARKERS = {
    "CopyIn": re.compile(r"\bCopyIn\b|\bDataCopy\b.*(?:GM|gm).*?(?:UB|L1|l1|ub)", re.IGNORECASE),
    "CopyOut": re.compile(r"\bCopyOut\b|\bDataCopy\b.*(?:UB|L1).*?(?:GM|gm|out)", re.IGNORECASE),
    "Compute": re.compile(r"\b(Compute|Matmul|Softmax|Muls|Adds|PipeBarrier)\b"),
    "Sync": re.compile(r"\b(PipeBarrier|SetFlag|WaitFlag)\b"),
    "Init": re.compile(r"\bInit\b"),
    "Process": re.compile(r"\bProcess\b"),
}
METHOD_MARKER_NAMES = ("Process", "Init", "Compute")
_KERNEL_UNIT_ROLES = frozenset(
    {
        "public_kernel_entry",
        "concrete_kernel_impl",
        "normal_impl",
        "varlen_impl",
        "empty_impl",
    }
)


@dataclass
class EnumEntry:
    name: str
    value: int | None = None


@dataclass
class DeclaredDomain:
    kind: str  # enum_class | constexpr_block
    type_name: str
    entries: list[EnumEntry]
    file_path: str = ""
    start_line: int = 0

    @property
    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    @property
    def name_set(self) -> set[str]:
        return {e.name for e in self.entries}


@dataclass
class FieldEnumUsage:
    field: str
    branch_literals: set[str] = field(default_factory=set)
    declared: DeclaredDomain | None = None


@dataclass
class FieldIntUsage:
    field: str
    branch_values: set[int] = field(default_factory=set)


def extract_kernel_subgraph(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    graph = load_entrypoint_graph(uo_root)
    nodes_by_id = {
        str(n.get("id")): n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")
    }
    kernel_nodes = _prefer_kernel_nodes(graph, architecture)
    primary = kernel_nodes[0] if kernel_nodes else {}
    unresolved: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []

    unit_ctxs = _kernel_unit_contexts(graph, nodes_by_id, architecture)
    if not unit_ctxs and primary:
        loc0 = primary.get("locator") if isinstance(primary.get("locator"), dict) else {}
        sym0 = primary.get("symbol_ref") if isinstance(primary.get("symbol_ref"), dict) else {}
        unit_ctxs = [
            {
                "entry_id": str(primary.get("id") or "KPATH_ENTRY"),
                "path_family": primary.get("path_family") or "unknown",
                "owning_class": str(sym0.get("class_or_namespace") or primary.get("name") or ""),
                "seed_file": str(loc0.get("file_path") or sym0.get("repo_relative_path") or ""),
                "unit_id": None,
            }
        ]

    entry_ids: list[str] = []
    for ctx in unit_ctxs:
        eid = str(ctx["entry_id"])
        if eid in entry_ids:
            continue
        entry_ids.append(eid)
        root = nodes_by_id.get(eid) or primary
        loc = root.get("locator") if isinstance(root.get("locator"), dict) else {}
        sym = root.get("symbol_ref") if isinstance(root.get("symbol_ref"), dict) else {}
        nodes.append(
            {
                "id": eid,
                "layer": "kernel",
                "node_type": "KernelEntry",
                "name": root.get("name") or "KernelEntry",
                "qualified_name": sym.get("qualified_name") or root.get("name") or "KernelEntry",
                "file_path": loc.get("file_path") or sym.get("repo_relative_path") or ctx.get("seed_file") or "",
                "start_line": int(loc.get("start_line") or 0),
                "end_line": int(loc.get("end_line") or 0),
                "entrypoint_id": root.get("id") or eid,
                "extraction_unit_id": ctx.get("unit_id"),
                "role": root.get("role"),
                "path_family": ctx.get("path_family"),
            }
        )

    default_entry_id = entry_ids[0] if entry_ids else "KPATH_ENTRY"
    if not entry_ids:
        loc = primary.get("locator") if isinstance(primary.get("locator"), dict) else {}
        sym = primary.get("symbol_ref") if isinstance(primary.get("symbol_ref"), dict) else {}
        nodes.append(
            {
                "id": default_entry_id,
                "layer": "kernel",
                "node_type": "KernelEntry",
                "name": primary.get("name") or "KernelEntry",
                "qualified_name": sym.get("qualified_name") or primary.get("name") or "KernelEntry",
                "file_path": loc.get("file_path") or sym.get("repo_relative_path") or "",
                "start_line": int(loc.get("start_line") or 0),
                "end_line": int(loc.get("end_line") or 0),
                "entrypoint_id": primary.get("id"),
                "role": primary.get("role"),
            }
        )
        entry_ids = [default_entry_id]

    tilingkey_space = load_tilingkey_space(uo_root, repo_root, op_name, architecture=architecture)
    key_index = load_key_dimension_index(tilingkey_space)

    kernel_files = _kernel_files(repo_root, op_name, architecture, primary if primary else None, kernel_nodes)
    if not kernel_files:
        unresolved.append(
            {
                "id": "UNRES_KERNEL_FILES",
                "kind": "kernel_files_missing",
                "message": "No arch35 kernel files found for extraction",
                "file_path": "",
                "snippet": "",
            }
        )


    nodes.append({"id": "KEY_TILINGKEY", "layer": "bridge", "node_type": "TilingKey", "name": "TilingKey", "qualified_name": "TilingKey", "file_path": "", "start_line": 0, "end_line": 0})
    for eid in entry_ids:
        edges.append({"id": stable_id("E_KEY_SELECTS_", eid), "type": "selects", "source": "KEY_TILINGKEY", "target": eid})

    loaded_fields: set[str] = set()
    bool_tdf_fields: set[str] = set()
    field_usage: dict[str, FieldEnumUsage] = {}
    int_usage: dict[str, FieldIntUsage] = {}
    local_to_tdf: dict[str, str] = {}
    plan = load_extract_plan(uo_root)
    if plan:
        local_to_tdf.update(plan_aliases(plan))
        for leaf in local_to_tdf.values():
            loaded_fields.add(leaf)
    derived_re = _derived_read_re(plan_derived_roots(plan) if plan else set())
    declared_domains = collect_declared_domains(
        _enum_declaration_files(repo_root, op_name, architecture) + kernel_files
    )

    # Seed only valued feature macros across kernel files for #if evaluation.
    # Do NOT seed include-guard #define FOO_H — that kills #ifndef FOO_H bodies.
    seed_defines: dict[str, str | None] = {}
    for path in kernel_files:
        try:
            seed_defines = merge_defines(
                seed_defines,
                valued_seed_defines(
                    analyze_macros(path.read_text(encoding="utf-8", errors="ignore")).defines
                ),
            )
        except OSError:
            continue
    # Tiling-key symbols are compile-injected; do not treat #ifdef KEY as dead.
    soft_undefined = {str(k) for k in (key_index or {})}

    for path in kernel_files:
        rel = path.relative_to(repo_root).as_posix()
        file_entry_id = _pick_entry_for_file(rel, unit_ctxs, default_entry_id)
        file_ctx = _ctx_for_entry(unit_ctxs, file_entry_id)
        file_class = str(file_ctx.get("owning_class") or "")
        text = path.read_text(encoding="utf-8", errors="ignore")
        macro_info = analyze_macros(text, seed_defines=seed_defines, soft_undefined=soft_undefined)

        def _active(line: int) -> bool:
            return macro_info.is_active_line(line)

        for match in TDF_ASSIGN_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if not _active(line):
                continue
            lhs = re.sub(r"\s+", "", match.group(1))
            local = lhs.split(".")[-1]
            tdf_path = match.group(2)
            tdf_leaf = tdf_path.split(".")[-1]
            local_to_tdf[local] = tdf_leaf
            loaded_fields.add(tdf_leaf)
        for match in TILING_DATA_READ_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if not _active(line):
                continue
            loaded_fields.add(match.group(1).split(".")[-1])

        # compile-time macros (#if/#ifdef/#elif) with KEY provenance when possible
        for directive in macro_info.directives:
            if directive.kind not in {"if", "ifdef", "ifndef", "elif"}:
                continue
            cond = directive.condition or directive.name or ""
            source, ref, domain = classify_macro_condition(cond, key_index=key_index)
            owning_key = _owning_function_identity_key(
                repo_root, rel, text, directive.line, file_class, architecture
            )
            branch = _make_branch(
                name=f"macro_{directive.line}",
                rel=rel,
                line=directive.line,
                condition=cond,
                binding_time="compile_time",
                determinant_source=source,
                determinant_ref=ref,
                domain=domain,
                owning_identity_key=owning_key,
            )
            if directive.eval_result is not None:
                branch["node"]["macro_eval"] = bool(directive.eval_result)
            branches.append(branch)
            nodes.append(branch["node"])
            edges.append(
                {
                    "id": stable_id("E_", file_entry_id, branch["node"]["id"]),
                    "type": "contains",
                    "source": file_entry_id,
                    "target": branch["node"]["id"],
                }
            )

        # if constexpr — provenance: bind to TilingKey or leave unbound
        for idx, match in enumerate(IF_CONSTEXPR_RE.finditer(text)):
            line = text.count("\n", 0, match.start()) + 1
            if not _active(line):
                continue
            cond = " ".join(match.group(1).split())
            source, ref, domain = classify_compile_determinant(cond, key_index)
            owning_key = _owning_function_identity_key(
                repo_root, rel, text, line, file_class, architecture
            )
            branch = _make_branch(
                name=f"constexpr_{idx}",
                rel=rel,
                line=line,
                condition=cond,
                binding_time="compile_time",
                determinant_source=source,
                determinant_ref=ref,
                domain=domain,
                owning_identity_key=owning_key,
            )
            branches.append(branch)
            nodes.append(branch["node"])
            edges.append({"id": stable_id("E_", file_entry_id, branch["node"]["id"]), "type": "contains", "source": file_entry_id, "target": branch["node"]["id"]})

        # runtime if (exclude constexpr; skip preprocessor-dead regions)
        for idx, match in enumerate(IF_RUNTIME_RE.finditer(text)):
            window_start = max(0, match.start() - 12)
            if "constexpr" in text[window_start:match.start()]:
                continue
            line = text.count("\n", 0, match.start()) + 1
            if not _active(line):
                continue
            cond = " ".join(match.group(1).split())
            if len(cond) > 240:
                continue
            tiling_hits = list(TILING_DATA_READ_RE.findall(cond))
            derived_hits = list(derived_re.findall(cond))
            eq_hits = extract_field_enum_comparisons(cond, key_index=key_index)
            int_hits = extract_field_int_comparisons(cond, key_index=key_index)
            branch_literals = sorted({lit for _, lit in eq_hits})
            for fld, lit in eq_hits:
                canon = local_to_tdf.get(fld, fld)
                usage = field_usage.setdefault(canon, FieldEnumUsage(field=canon))
                usage.branch_literals.add(lit)
            for fld, val in int_hits:
                canon = local_to_tdf.get(fld, fld)
                usage_i = int_usage.setdefault(canon, FieldIntUsage(field=canon))
                usage_i.branch_values.add(val)

            domain: list[Any] | None = branch_literals or None
            if tiling_hits:
                source = "TilingDataField"
                ref = tiling_hits[0]
                leaf = tiling_hits[0].split(".")[-1]
                leaf = local_to_tdf.get(leaf, leaf)
                loaded_fields.add(leaf)
                if domain is None and _looks_like_bool_truth_cond(cond, leaf):
                    domain = [0, 1]
                    bool_tdf_fields.add(leaf)
                if domain is None and int_hits:
                    domain = sorted({v for f, v in int_hits if local_to_tdf.get(f, f) == leaf})
                _append_tdf_kvar_stub(nodes, edges, leaf, tiling_hits[0], rel, line, domain)
            elif derived_hits:
                source = "KernelDerivedField"
                ref = derived_hits[0]
                leaf = derived_hits[0].split(".")[-1]
                # Local / constInfo field assigned from tilingData (alias / plan)
                if leaf in local_to_tdf:
                    source = "TilingDataField"
                    tdf_leaf = local_to_tdf[leaf]
                    ref = tdf_leaf
                    loaded_fields.add(tdf_leaf)
                    if domain is None and _looks_like_bool_truth_cond(cond, leaf):
                        domain = [0, 1]
                        bool_tdf_fields.add(tdf_leaf)
                    if domain is None and eq_hits:
                        domain = branch_literals or None
                    if domain is None and int_hits:
                        domain = sorted({v for f, v in int_hits if local_to_tdf.get(f, f) == tdf_leaf})
                    _append_tdf_kvar_stub(nodes, edges, tdf_leaf, tdf_leaf, rel, line, domain)
            else:
                source = "KernelVariable"
                ref = cond
                # Bare local that aliases a TDF member
                bare = _bare_bool_local(cond)
                if bare and bare in local_to_tdf:
                    source = "TilingDataField"
                    tdf_leaf = local_to_tdf[bare]
                    ref = tdf_leaf
                    loaded_fields.add(tdf_leaf)
                    domain = [0, 1]
                    bool_tdf_fields.add(tdf_leaf)
                    _append_tdf_kvar_stub(nodes, edges, tdf_leaf, tdf_leaf, rel, line, domain)

            # Prefer field name as determinant when enum/int compare is present.
            # Always normalize through local_to_tdf (plan aliases + assign scan).
            if eq_hits and source == "KernelVariable":
                raw = eq_hits[0][0]
                canon = local_to_tdf.get(raw, raw)
                source = "TilingDataField" if (raw in local_to_tdf or canon in loaded_fields) else (
                    "KernelDerivedField" if derived_hits else "TilingDataField"
                )
                ref = canon
                if source == "TilingDataField":
                    loaded_fields.add(ref)
            elif eq_hits and source == "KernelDerivedField":
                raw = eq_hits[0][0]
                canon = local_to_tdf.get(raw, raw)
                if raw in local_to_tdf:
                    source = "TilingDataField"
                    loaded_fields.add(canon)
                ref = canon
            elif eq_hits and source == "TilingDataField":
                raw = eq_hits[0][0]
                ref = local_to_tdf.get(raw, local_to_tdf.get(str(ref).split(".")[-1], ref))
                if isinstance(ref, str):
                    loaded_fields.add(ref.split(".")[-1])
            elif int_hits and source in {"KernelVariable", "KernelDerivedField"}:
                fld = int_hits[0][0]
                canon = local_to_tdf.get(fld, fld)
                if (
                    fld in local_to_tdf
                    or canon in loaded_fields
                    or any(h.endswith(fld) or h.split(".")[-1] == fld for h in tiling_hits)
                ):
                    source = "TilingDataField"
                    ref = canon
                    loaded_fields.add(canon)
                    domain = sorted({v for f, v in int_hits if local_to_tdf.get(f, f) == canon})
                    _append_tdf_kvar_stub(nodes, edges, canon, canon, rel, line, domain)
                elif source == "KernelVariable":
                    # Keep as derived/local; do not invent TDF without evidence.
                    source = "KernelDerivedField"
                    ref = canon

            if domain is None and int_hits and source == "TilingDataField":
                leaf = local_to_tdf.get(str(ref).split(".")[-1], str(ref).split(".")[-1])
                domain = sorted({v for f, v in int_hits if local_to_tdf.get(f, f) == leaf})

            owning_key = _owning_function_identity_key(
                repo_root, rel, text, line, file_class, architecture
            )
            branch = _make_branch(
                name=f"runtime_{idx}",
                rel=rel,
                line=line,
                condition=cond,
                binding_time="runtime",
                determinant_source=source,
                determinant_ref=ref,
                domain=domain,
                owning_identity_key=owning_key,
            )
            if _looks_like_enum_field_compare(cond) and not eq_hits and not int_hits:
                unresolved.append(
                    {
                        "id": stable_id("UNRES_ENUM_", str(line), rel),
                        "kind": "enum_domain_unknown",
                        "message": "enum-like field compare missing concrete SCREAMING_SNAKE literals",
                        "file_path": rel,
                        "start_line": line,
                        "snippet": snippet(cond),
                        "target_node": branch["node"]["id"],
                    }
                )
            branches.append(branch)
            nodes.append(branch["node"])
            edges.append({"id": stable_id("E_", file_entry_id, branch["node"]["id"]), "type": "contains", "source": file_entry_id, "target": branch["node"]["id"]})

        _append_method_marker_nodes(
            repo_root,
            rel,
            text,
            file_entry_id,
            file_class,
            architecture,
            nodes,
            edges,
        )

        for idx, match in enumerate(LOOP_RE.finditer(text)):
            header = " ".join(match.group(1).split())
            if len(header) > 160:
                continue
            line = text.count("\n", 0, match.start()) + 1
            loop_kind = "tail" if "tail" in header.lower() else "main"
            owning_key = _owning_function_identity_key(
                repo_root, rel, text, line, file_class, architecture
            )
            node_id = mint_scoped_node_id("KLOOP", owning_key, rel, line, loop_kind)
            nodes.append(
                {
                    "id": node_id,
                    "layer": "kernel",
                    "node_type": "Loop",
                    "name": f"{loop_kind}_loop",
                    "qualified_name": f"{rel}::loop@{line}",
                    "file_path": rel,
                    "start_line": line,
                    "end_line": line,
                    "loop_kind": loop_kind,
                    "condition": header,
                }
            )
            edges.append({"id": stable_id("E_", file_entry_id, node_id), "type": "contains", "source": file_entry_id, "target": node_id})

    # Resolve full declared domains against kernel branch hits; emit/merge KVAR nodes.
    # Only promote to runtime_variables when provenance is TilingDataField.
    enum_fields_resolved: set[str] = set()
    for fld, usage in sorted(field_usage.items()):
        declared = resolve_declared_domain(usage.branch_literals, declared_domains)
        usage.declared = declared
        payload = build_field_domain_payload(usage)
        if not payload["domain"]:
            continue
        if fld not in loaded_fields:
            # Pure KernelDerivedField / local enum compares are not CSV-controllable vars.
            continue
        enum_fields_resolved.add(fld)
        kvar_id = stable_id("KVAR_", fld)
        nodes.append(
            {
                "id": kvar_id,
                "layer": "kernel",
                "node_type": "KernelVariable",
                "name": fld,
                "qualified_name": fld,
                "file_path": (declared.file_path if declared else ""),
                "start_line": (declared.start_line if declared else 0),
                "end_line": (declared.start_line if declared else 0),
                "binding_time": "runtime",
                "determinant_source": "TilingDataField",
                **payload,
            }
        )
        tdf_id = stable_id("TDF_", fld)
        nodes.append(
            {
                "id": tdf_id,
                "layer": "bridge",
                "node_type": "TilingDataField",
                "name": fld,
                "qualified_name": fld,
                "file_path": "",
                "start_line": 0,
                "end_line": 0,
            }
        )
        edges.append(
            {
                "id": stable_id("E_", tdf_id, kvar_id),
                "type": "loads_into",
                "source": tdf_id,
                "target": kvar_id,
            }
        )

    # Bool / int TDF fields with domains (enablePreSfmg, sinkOptional, pseType, ...)
    for fld in sorted(bool_tdf_fields):
        if fld in enum_fields_resolved:
            continue
        kvar_id = stable_id("KVAR_", fld)
        nodes.append(
            {
                "id": kvar_id,
                "layer": "kernel",
                "node_type": "KernelVariable",
                "name": fld,
                "qualified_name": fld,
                "file_path": "",
                "start_line": 0,
                "end_line": 0,
                "binding_time": "runtime",
                "determinant_source": "TilingDataField",
                "domain": [0, 1],
                "domain_with_kernel_branch": [0, 1],
                "domain_without_kernel_branch": [],
                "domain_entries": [
                    {"name": "0", "value": 0, "has_kernel_branch": True},
                    {"name": "1", "value": 1, "has_kernel_branch": True},
                ],
                "domain_source": "bool_truth_cond",
                "domain_type_name": None,
            }
        )
        tdf_id = stable_id("TDF_", fld)
        nodes.append(
            {
                "id": tdf_id,
                "layer": "bridge",
                "node_type": "TilingDataField",
                "name": fld,
                "qualified_name": fld,
                "file_path": "",
                "start_line": 0,
                "end_line": 0,
            }
        )
        edges.append({"id": stable_id("E_", tdf_id, kvar_id), "type": "loads_into", "source": tdf_id, "target": kvar_id})

    for fld, usage in sorted(int_usage.items()):
        if fld in enum_fields_resolved or fld in bool_tdf_fields:
            continue
        if fld not in loaded_fields:
            # Only promote int domains with TilingData evidence.
            continue
        values = sorted(usage.branch_values)
        if not values:
            continue
        kvar_id = stable_id("KVAR_", fld)
        nodes.append(
            {
                "id": kvar_id,
                "layer": "kernel",
                "node_type": "KernelVariable",
                "name": fld,
                "qualified_name": fld,
                "file_path": "",
                "start_line": 0,
                "end_line": 0,
                "binding_time": "runtime",
                "determinant_source": "TilingDataField",
                "domain": values,
                "domain_with_kernel_branch": values,
                "domain_without_kernel_branch": [],
                "domain_entries": [{"name": str(v), "value": v, "has_kernel_branch": True} for v in values],
                "domain_source": "branch_int_literals",
                "domain_type_name": None,
            }
        )
        tdf_id = stable_id("TDF_", fld)
        nodes.append(
            {
                "id": tdf_id,
                "layer": "bridge",
                "node_type": "TilingDataField",
                "name": fld,
                "qualified_name": fld,
                "file_path": "",
                "start_line": 0,
                "end_line": 0,
            }
        )
        edges.append({"id": stable_id("E_", tdf_id, kvar_id), "type": "loads_into", "source": tdf_id, "target": kvar_id})

    # Enrich earlier per-line KVAR stubs that share the same field id.
    enriched = {stable_id("KVAR_", f): f for f in enum_fields_resolved}
    for node in nodes:
        fld = enriched.get(str(node.get("id")))
        if not fld:
            continue
        usage = field_usage[fld]
        node.update(build_field_domain_payload(usage))
        if fld in loaded_fields:
            node["determinant_source"] = "TilingDataField"

    nodes.append({"id": "KOUT_OUTPUT", "layer": "kernel", "node_type": "Output", "name": "Output", "qualified_name": "Output", "file_path": "", "start_line": 0, "end_line": 0})
    for eid in entry_ids:
        edges.append({"id": stable_id("E_ENTRY_TO_OUTPUT_", eid), "type": "writes_output", "source": eid, "target": "KOUT_OUTPUT"})

    return {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "layer": "kernel",
        "nodes": _dedupe_nodes(nodes),
        "edges": _dedupe_edges(edges),
        "branches": [
            {
                "id": b["node"]["id"],
                "binding_time": b["node"].get("binding_time"),
                "determinant_source": b["node"].get("determinant_source"),
                "determinant_ref": b["node"].get("determinant_ref"),
                "condition": b["node"].get("condition"),
                "domain": b["node"].get("domain"),
                "file_path": b["node"].get("file_path"),
                "start_line": b["node"].get("start_line"),
            }
            for b in branches
        ],
        "declared_enum_domains": [
            {
                "kind": d.kind,
                "type_name": d.type_name,
                "names": d.names,
                "entries": [{"name": e.name, "value": e.value} for e in d.entries],
                "file_path": d.file_path,
                "start_line": d.start_line,
            }
            for d in declared_domains
        ],
        "loaded_tiling_fields": sorted(loaded_fields | enum_fields_resolved),
        "unresolved": unresolved,
    }


def collect_declared_domains(files: list[Path]) -> list[DeclaredDomain]:
    domains: list[DeclaredDomain] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.as_posix()
        for domain in parse_enum_class_domains(text, rel) + parse_constexpr_block_domains(text, rel):
            key = (domain.type_name, tuple(domain.names))
            if key in seen:
                continue
            seen.add(key)
            domains.append(domain)
    return domains


def parse_enum_class_domains(text: str, file_path: str = "") -> list[DeclaredDomain]:
    out: list[DeclaredDomain] = []
    for match in ENUM_CLASS_RE.finditer(text):
        type_name = match.group(1)
        body = match.group(2)
        entries: list[EnumEntry] = []
        next_value = 0
        for mem in ENUM_MEMBER_RE.finditer(body):
            name = mem.group(1)
            if name in {"class", "struct", "enum"}:
                continue
            if mem.group(2) is not None:
                next_value = int(mem.group(2))
            entries.append(EnumEntry(name=name, value=next_value))
            next_value += 1
        if len(entries) < 2:
            continue
        line = text.count("\n", 0, match.start()) + 1
        out.append(
            DeclaredDomain(
                kind="enum_class",
                type_name=type_name,
                entries=entries,
                file_path=file_path,
                start_line=line,
            )
        )
    return out


def parse_constexpr_block_domains(text: str, file_path: str = "") -> list[DeclaredDomain]:
    """Group consecutive same-type constexpr NAME = N into enum-like domains."""
    matches = list(CONSTEXPR_INT_RE.finditer(text))
    if not matches:
        return []
    out: list[DeclaredDomain] = []
    i = 0
    while i < len(matches):
        ctype = matches[i].group(1)
        run = [matches[i]]
        j = i + 1
        while j < len(matches):
            prev_end = matches[j - 1].end()
            cur_start = matches[j].start()
            between = text[prev_end:cur_start]
            # Allow blank lines / comments; break on other code.
            if re.search(r"[^\s/#*]", between):
                break
            if matches[j].group(1) != ctype:
                break
            run.append(matches[j])
            j += 1
        entries = [EnumEntry(name=m.group(2), value=int(m.group(3))) for m in run]
        if _is_enum_like_constexpr_block(entries):
            line = text.count("\n", 0, run[0].start()) + 1
            # Synthetic type name from shared prefix or first/last token.
            type_name = _infer_block_type_name(entries)
            out.append(
                DeclaredDomain(
                    kind="constexpr_block",
                    type_name=type_name,
                    entries=entries,
                    file_path=file_path,
                    start_line=line,
                )
            )
        i = j if j > i else i + 1
    return out


def extract_field_enum_comparisons(
    cond: str,
    *,
    key_index: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for match in FIELD_EQ_ENUM_RE.finditer(cond):
        fld = match.group(1)
        lit = match.group(3)
        if not _is_screaming_snake(lit):
            continue
        # Skip symbols that are known TilingKey dimensions (not enum fields).
        if key_index is not None and is_key_symbol(fld, key_index):
            continue
        hits.append((fld, lit))
    return hits


def extract_field_int_comparisons(
    cond: str,
    *,
    key_index: dict[str, Any] | None = None,
) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for match in FIELD_EQ_INT_RE.finditer(cond):
        fld = match.group(1)
        if key_index is not None and is_key_symbol(fld, key_index):
            continue
        if _is_screaming_snake(fld):
            # Likely enum/template token, not a field.
            continue
        hits.append((fld, int(match.group(2))))
    return hits


def resolve_declared_domain(hit_literals: set[str], catalogs: list[DeclaredDomain]) -> DeclaredDomain | None:
    if not hit_literals:
        return None
    best: DeclaredDomain | None = None
    best_key: tuple[int, int] = (-1, -1)
    for cat in catalogs:
        overlap = len(hit_literals & cat.name_set)
        if overlap == 0:
            continue
        # Prefer more overlap, then larger declared domain (fuller enum).
        key = (overlap, len(cat.entries))
        if key > best_key:
            best_key = key
            best = cat
    return best


def build_field_domain_payload(usage: FieldEnumUsage) -> dict[str, Any]:
    declared = usage.declared
    if declared is not None:
        full_names = declared.names
        entries = declared.entries
        source = declared.kind
        type_name = declared.type_name
    else:
        full_names = sorted(usage.branch_literals)
        entries = [EnumEntry(name=n) for n in full_names]
        source = "branch_literals_only"
        type_name = ""

    with_branch = sorted(n for n in full_names if n in usage.branch_literals)
    without_branch = sorted(n for n in full_names if n not in usage.branch_literals)
    return {
        "domain": full_names,
        "domain_with_kernel_branch": with_branch,
        "domain_without_kernel_branch": without_branch,
        "domain_entries": [{"name": e.name, "value": e.value, "has_kernel_branch": e.name in usage.branch_literals} for e in entries],
        "domain_source": source,
        "domain_type_name": type_name or None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract kernel subgraph with compile/runtime branch classification")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = extract_kernel_subgraph(repo_root, op_name, architecture=args.architecture)
    if args.write:
        write_yaml(existing_operator_root(repo_root, op_name) / "ir" / "kernel_subgraph.yaml", payload)
    print(f"kernel nodes={len(payload['nodes'])} branches={len(payload['branches'])} unresolved={len(payload['unresolved'])}")
    return 0


def _kernel_unit_contexts(
    graph: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    architecture: str,
) -> list[dict[str, Any]]:
    ctxs: list[dict[str, Any]] = []
    for unit in entrypoint_units(graph):
        root_id = str(unit.get("entry_root") or "")
        root = nodes_by_id.get(root_id) or {}
        role = str(root.get("role") or "")
        loc = root.get("locator") if isinstance(root.get("locator"), dict) else {}
        sym = root.get("symbol_ref") if isinstance(root.get("symbol_ref"), dict) else {}
        seed = str(loc.get("file_path") or sym.get("repo_relative_path") or "").replace("\\", "/")
        if role not in _KERNEL_UNIT_ROLES and "op_kernel" not in seed:
            continue
        arch = str(root.get("architecture") or unit.get("architecture") or architecture)
        if arch not in {architecture, "neutral"}:
            continue
        cls = str(sym.get("class_or_namespace") or "")
        if not cls:
            cls = str(root.get("name") or "")
        ctxs.append(
            {
                "entry_id": root_id or str(unit.get("id") or ""),
                "path_family": unit.get("path_family") or root.get("path_family") or "unknown",
                "owning_class": cls,
                "seed_file": seed,
                "unit_id": unit.get("id"),
            }
        )
    return ctxs


def _ctx_for_entry(ctxs: list[dict[str, Any]], entry_id: str) -> dict[str, Any]:
    for ctx in ctxs:
        if str(ctx.get("entry_id")) == entry_id:
            return ctx
    return ctxs[0] if ctxs else {}


def _pick_entry_for_file(rel: str, ctxs: list[dict[str, Any]], default_entry_id: str) -> str:
    if not ctxs:
        return default_entry_id
    rel_l = rel.replace("\\", "/").lower()
    for ctx in ctxs:
        pf = str(ctx.get("path_family") or "").lower()
        if pf and pf not in {"unknown", "shared", "neutral"} and pf in rel_l:
            return str(ctx["entry_id"])
    for ctx in ctxs:
        seed = str(ctx.get("seed_file") or "").replace("\\", "/").lower()
        if seed and (rel_l == seed or rel_l.endswith("/" + seed.split("/")[-1])):
            return str(ctx["entry_id"])
    if len(ctxs) == 1:
        return str(ctxs[0]["entry_id"])
    return default_entry_id


def _owning_function_identity_key(
    repo_root: Path,
    rel: str,
    text: str,
    line: int,
    default_class: str,
    architecture: str,
) -> str:
    inner_name = ""
    inner_start = -1
    for name, start, end, _body, _r in iter_function_defs(repo_root, rel):
        if start <= line <= end and start > inner_start:
            inner_start = start
            inner_name = name
    if not inner_name:
        ident = mint_symbol_identity(
            kind="method",
            name="file_scope",
            file_path=rel,
            class_or_namespace=default_class or "Unknown",
            architecture=architecture,
        )
        return ident.identity_key
    lines = text.splitlines()
    header = lines[inner_start - 1] if 0 < inner_start <= len(lines) else inner_name
    preceding = "\n".join(lines[max(0, inner_start - 80) : inner_start])
    cls = default_class
    matches = re.findall(r"\b(?:class|struct)\s+([A-Za-z_]\w*)", preceding)
    if matches:
        cls = matches[-1]
    tpl = parse_template_arity(header + " " + preceding[-200:])
    sk = infer_specialization_kind(preceding[-400:] + header)
    ident = mint_method_identity(
        name=inner_name,
        file_path=rel,
        class_or_namespace=cls or "Unknown",
        template_arity_or_signature=tpl,
        specialization_kind=sk,
        architecture=architecture,
    )
    return ident.identity_key


def _append_method_marker_nodes(
    repo_root: Path,
    rel: str,
    text: str,
    entry_id: str,
    owning_class: str,
    architecture: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    seen_ids: set[str] = set()
    for method_name in METHOD_MARKER_NAMES:
        hit = find_function_body(repo_root, rel, method_name, owning_class=owning_class or "")
        if hit is None:
            continue
        start, end, _body, resolved_rel = hit
        lines = text.splitlines()
        header = lines[start - 1] if 0 < start <= len(lines) else method_name
        preceding = "\n".join(lines[max(0, start - 40) : start])
        cls = owning_class
        m = re.findall(r"\b(?:class|struct)\s+([A-Za-z_]\w*)", preceding)
        if m:
            cls = m[-1]
        tpl = parse_template_arity(header)
        sk = infer_specialization_kind(preceding + header)
        ident = mint_method_identity(
            name=method_name,
            file_path=resolved_rel or rel,
            class_or_namespace=cls or "Unknown",
            template_arity_or_signature=tpl,
            specialization_kind=sk,
            architecture=architecture,
        )
        node_id = ident.stable_id
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "layer": "kernel",
                "node_type": method_name,
                "name": method_name,
                "qualified_name": ident.qualified_name,
                "file_path": resolved_rel or rel,
                "start_line": start,
                "end_line": end,
                "identity_key": ident.identity_key,
                "symbol_ref": ident.as_dict(),
            }
        )
        edges.append(
            {
                "id": stable_id("E_", entry_id, node_id),
                "type": "contains",
                "source": entry_id,
                "target": node_id,
            }
        )


def _make_branch(
    *,
    name: str,
    rel: str,
    line: int,
    condition: str,
    binding_time: str,
    determinant_source: str,
    determinant_ref: str,
    domain: list[Any] | None = None,
    owning_identity_key: str = "",
) -> dict[str, Any]:
    node_id = mint_scoped_node_id("KBR", owning_identity_key or rel, rel, line, name)
    return {
        "node": {
            "id": node_id,
            "layer": "kernel",
            "node_type": "KernelBranch",
            "name": name,
            "qualified_name": f"{rel}::{name}",
            "file_path": rel,
            "start_line": line,
            "end_line": line,
            "condition": condition,
            "binding_time": binding_time,
            "determinant_source": determinant_source,
            "determinant_ref": determinant_ref,
            "domain": domain,
            "owning_identity_key": owning_identity_key or None,
        }
    }


def _append_tdf_kvar_stub(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    leaf: str,
    qualified: str,
    rel: str,
    line: int,
    domain: list[Any] | None,
) -> None:
    kvar_id = stable_id("KVAR_", leaf)
    nodes.append(
        {
            "id": kvar_id,
            "layer": "kernel",
            "node_type": "KernelVariable",
            "name": leaf,
            "qualified_name": qualified,
            "file_path": rel,
            "start_line": line,
            "end_line": line,
            "domain": domain,
            "binding_time": "runtime",
            "determinant_source": "TilingDataField",
        }
    )
    tdf_id = stable_id("TDF_", leaf)
    nodes.append(
        {
            "id": tdf_id,
            "layer": "bridge",
            "node_type": "TilingDataField",
            "name": leaf,
            "qualified_name": qualified,
            "file_path": rel,
            "start_line": line,
            "end_line": line,
        }
    )
    edges.append({"id": stable_id("E_", tdf_id, kvar_id), "type": "loads_into", "source": tdf_id, "target": kvar_id})


def _looks_like_bool_truth_cond(cond: str, field: str) -> bool:
    """True when condition is a truthiness test on field (no == / !=)."""
    if not field or field not in cond:
        return False
    if re.search(rf"\b{re.escape(field)}\s*(==|!=)", cond):
        return False
    # Strip wrappers like unlikely(...), !field, field alone.
    stripped = re.sub(r"\bunlikely\s*\(|\blikely\s*\(", "", cond)
    stripped = stripped.replace(")", " ").replace("!", " ")
    tokens = re.findall(r"[A-Za-z_]\w*", stripped)
    return field in tokens


def _bare_bool_local(cond: str) -> str | None:
    """Return single identifier if cond is a simple truthiness test on one local."""
    stripped = re.sub(r"\bunlikely\s*\(|\blikely\s*\(", "", cond)
    stripped = stripped.replace(")", "").replace("!", "").strip()
    if re.fullmatch(r"[A-Za-z_]\w*", stripped):
        return stripped
    return None


def _is_screaming_snake(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", name)) and ("_" in name or len(name) >= 3)


def _looks_like_enum_field_compare(cond: str) -> bool:
    # Heuristic: camelCase/snake field compared with something that is not a number/bool.
    return bool(re.search(r"\b[A-Za-z_]\w*(?:Mode|Type|Kind|Flag|Layout)\b\s*==", cond))


def _is_enum_like_constexpr_block(entries: list[EnumEntry]) -> bool:
    if len(entries) < 2:
        return False
    values = [e.value for e in entries if e.value is not None]
    if len(values) != len(entries):
        return False
    if len(set(values)) != len(values):
        return False
    vmin, vmax = min(values), max(values)
    # Enum-like: starts near 0 and stays in a small dense range.
    if vmin > 1:
        return False
    if vmax > max(32, len(entries) * 3):
        return False
    # Reject sparse bitmasks / sizes (large average gap).
    span = vmax - vmin
    if span > len(entries) * 2:
        return False
    return True


def _infer_block_type_name(entries: list[EnumEntry]) -> str:
    names = [e.name for e in entries]
    if not names:
        return "ConstexprEnum"
    # Longest common prefix ending with underscore, else first token family.
    prefix = names[0]
    for name in names[1:]:
        while prefix and not name.startswith(prefix):
            prefix = prefix[:-1]
    prefix = prefix.rstrip("_")
    if len(prefix) >= 3:
        return prefix
    return f"Constexpr_{names[0]}"


def _enum_declaration_files(repo_root: Path, op_name: str, architecture: str) -> list[Path]:
    patterns = [
        f"op_kernel/{architecture}/**/*.h",
        f"op_kernel/{architecture}/**/*.hpp",
        f"op_host/{architecture}/**/*.h",
        f"op_host/{architecture}/**/*.hpp",
        f"{op_name}/op_kernel/{architecture}/**/*.h",
        f"{op_name}/op_kernel/{architecture}/**/*.hpp",
        f"{op_name}/op_host/{architecture}/**/*.h",
        f"{op_name}/op_host/{architecture}/**/*.hpp",
    ]
    uniq: dict[str, Path] = {}
    for pattern in patterns:
        for path in repo_root.glob(pattern):
            if path.is_file():
                uniq[path.resolve().as_posix()] = path
    return sorted(uniq.values(), key=lambda p: p.as_posix())[:120]


def _prefer_kernel_nodes(graph: dict[str, Any], architecture: str) -> list[dict[str, Any]]:
    """Prefer arch-compatible then neutral public_kernel_entry / concrete_kernel_impl."""
    from uo.scripts.arch_path import arch_compatible, architecture_of_path
    from uo.scripts.resolve_entrypoints import nodes_for_role

    raw = list(nodes_for_role(graph, "public_kernel_entry")) + list(
        nodes_for_role(graph, "concrete_kernel_impl")
    )
    scored: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for node in raw:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or "")
        if nid and nid in seen:
            continue
        if nid:
            seen.add(nid)
        loc = node.get("locator") if isinstance(node.get("locator"), dict) else {}
        sym = node.get("symbol_ref") if isinstance(node.get("symbol_ref"), dict) else {}
        fp = str(loc.get("file_path") or sym.get("repo_relative_path") or "")
        arch = str(node.get("architecture") or architecture_of_path(fp) or "neutral")
        if fp and not arch_compatible(fp, architecture):
            continue
        if arch == architecture:
            rank = 0
        elif arch == "neutral":
            rank = 1
        else:
            rank = 2
        scored.append((rank, node))
    scored.sort(key=lambda x: (x[0], str(x[1].get("id") or "")))
    return [n for _, n in scored]


def _kernel_files(
    repo_root: Path,
    op_name: str,
    architecture: str,
    primary: dict[str, Any] | None,
    kernel_nodes: list[dict[str, Any]] | None = None,
) -> list[Path]:
    files: list[Path] = []
    seed_paths: list[str] = []
    for node in kernel_nodes or []:
        if not isinstance(node, dict):
            continue
        loc = node.get("locator") if isinstance(node.get("locator"), dict) else {}
        sym = node.get("symbol_ref") if isinstance(node.get("symbol_ref"), dict) else {}
        fp = str(loc.get("file_path") or sym.get("repo_relative_path") or "").replace("\\", "/")
        if fp:
            seed_paths.append(fp)
    if primary:
        loc = primary.get("locator") if isinstance(primary.get("locator"), dict) else {}
        sym = primary.get("symbol_ref") if isinstance(primary.get("symbol_ref"), dict) else {}
        fp = str(
            loc.get("file_path")
            or sym.get("repo_relative_path")
            or primary.get("file_path")
            or ""
        ).replace("\\", "/")
        if fp:
            seed_paths.insert(0, fp)
    for rel in seed_paths:
        rel = rel.lstrip("./")
        for cand in (repo_root / rel, repo_root / op_name / rel):
            if cand.is_file():
                files.append(cand)
                break
    # Support both layouts:
    # - repo_root == operator package  -> op_kernel/arch35/...
    # - repo_root == workspace parent  -> <op>/op_kernel/arch35/...
    patterns = [
        f"op_kernel/{architecture}/**/*kernel*.h",
        f"op_kernel/{architecture}/**/*kernel*.cpp",
        f"op_kernel/{architecture}/**/*entry*.h",
        f"op_kernel/{architecture}/**/*common*.h",
        f"op_kernel/{architecture}/**/*block*.h",
        f"op_kernel/{architecture}/**/*block*.cpp",
        f"op_kernel/{architecture}/**/vector_api/**/*.h",
        f"op_kernel/{architecture}/**/vector_api/**/*.cpp",
        f"op_kernel/{architecture}/*.h",
        f"{op_name}/op_kernel/{architecture}/**/*kernel*.h",
        f"{op_name}/op_kernel/{architecture}/**/*kernel*.cpp",
        f"{op_name}/op_kernel/{architecture}/**/*entry*.h",
        f"{op_name}/op_kernel/{architecture}/**/*common*.h",
        f"{op_name}/op_kernel/{architecture}/**/*block*.h",
        f"{op_name}/op_kernel/{architecture}/**/*block*.cpp",
        f"{op_name}/op_kernel/{architecture}/**/vector_api/**/*.h",
        f"{op_name}/op_kernel/{architecture}/**/vector_api/**/*.cpp",
        f"{op_name}/op_kernel/{architecture}/*.h",
    ]
    for pattern in patterns:
        files.extend(repo_root.glob(pattern))
    # unique; prefer entry/kernel_base/kernel headers, then block/vector_api
    uniq: dict[str, Path] = {}
    for path in files:
        if not path.is_file():
            continue
        uniq[path.resolve().as_posix()] = path

    def rank(p: Path) -> tuple[int, int, str]:
        name = p.name.lower()
        posix = p.as_posix().replace("\\", "/").lower()
        if "entry" in name:
            return (0, 0, p.as_posix())
        if name.endswith("kernel.h") or name.endswith("kernel_base.h"):
            return (0, 1, p.as_posix())
        if "kernel" in name:
            return (1, 0, p.as_posix())
        if "common" in name:
            return (2, 0, p.as_posix())
        if "block" in name:
            return (3, 0, p.as_posix())
        if "/vector_api/" in posix:
            return (4, 0, p.as_posix())
        return (5, 0, p.as_posix())

    ranked = sorted(uniq.values(), key=rank)
    # Enough headers for branch extraction including vector_api layout/pse paths.
    return ranked[:120]


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        nid = str(node.get("id"))
        prev = out.get(nid)
        if prev is None:
            out[nid] = node
            continue
        # Prefer node with richer domain payload.
        if node.get("domain_entries") and not prev.get("domain_entries"):
            out[nid] = {**prev, **node}
        elif node.get("domain") and not prev.get("domain"):
            out[nid] = {**prev, **node}
        else:
            # Keep first; merge missing keys from later.
            for key, value in node.items():
                if key not in prev or prev.get(key) in (None, "", [], {}):
                    prev[key] = value
    return list(out.values())


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for edge in edges:
        out[str(edge.get("id"))] = edge
    return list(out.values())


if __name__ == "__main__":
    raise SystemExit(main())
