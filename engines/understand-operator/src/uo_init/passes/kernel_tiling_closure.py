# -*- coding: utf-8 -*-
"""Source-sound Kernel/TilingData closure for a selected architecture.

The generic source fallback intentionally stays lightweight, but a unified
CodeMap must not keep facts from a different top-level architecture entry or
claim TilingData closure from one existential ``TILING_DATA -> KERNEL`` edge.

This finalizer runs after the broad source inventory/resolution passes.  It:

* selects only ``op_kernel/<arch>/**`` plus top-level entries that explicitly
  reference ``<arch>/``;
* removes broad fallback Kernel call/template/ABI/TilingData-read facts and
  rebuilds those facts from the selected source set;
* binds direct functions, local macros and receiver methods when their static
  source type can be determined; unresolved local calls remain explicit rather
  than being guessed;
* resolves TilingData reads to ``owner::field`` instead of spraying a short field
  name across structures;
* records Host setter/direct-write sites for qualified TilingData fields; and
* publishes coverage/ambiguity/reachability counters consumed by strict audit.

It is deliberately lexical and index based.  Files are read once and all major
lookups use dictionaries/sets, keeping cold analysis near-linear in source size.
No operator name or TilingKey value is special-cased.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.symbol_identity import normalize_symbol
from uo_init.source_layout import GLOBAL_KERNEL_RE, selected_host_files, selected_kernel_files

_CPP_SUFFIXES = {".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"}
_CONTROL = {
    "if", "while", "for", "switch", "catch", "return", "sizeof", "alignof", "decltype",
    "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast", "likely", "unlikely",
}

_GLOBAL_KERNEL_RE = GLOBAL_KERNEL_RE
_TEMPLATE_PARAM_RE = re.compile(
    r"(?:bool|u?int(?:8|16|32|64)_t|int(?:8|16|32|64)_t|size_t|int|unsigned(?:\s+int)?)\s+([A-Za-z_]\w*)"
)
_CLASS_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)[^;{]*\{", re.S)
# Body-start anchor only. The old single regex used reluctant ``[\w:<>,\s*&~]*?``
# under DOTALL and spent ~30s/MB backtracking; walking back from ``) ... {`` is
# linear and keeps the same definition surface.
_FUNC_BODY_START_RE = re.compile(
    r"\)\s*(?:const\s*)?(?:noexcept(?:\s*\([^;{}()]*\))?\s*)?(?:override\s*)?\{"
)
_FUNC_NAME_TAIL_RE = re.compile(
    r"(?P<name>(?:[A-Za-z_]\w*(?:\s*<[^;{}()]{0,200}>)?\s*::\s*)*[A-Za-z_~]\w*)\s*$"
)
_CALL_RE = re.compile(
    r"(?:(?P<receiver>[A-Za-z_]\w*)\s*(?:\.|->)\s*)?"
    r"(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*"
    r"(?:<[^;{}()]{0,1200}>)?\s*\("
)
_BRANCH_RE = re.compile(r"\b(if\s+constexpr|if|while|for|switch)\s*\(")
_ALIAS_RE = re.compile(r"\busing\s+([A-Za-z_]\w*)\s*=\s*([^;]+);", re.S)
_TILING_READ_RE = re.compile(
    r"\b(?P<base>[A-Za-z_]\w*)\s*->\s*(?P<outer>[A-Za-z_]\w*)"
    r"(?:\s*\.\s*(?P<inner>[A-Za-z_]\w*))?"
)
_SETTER_HEAD_RE = re.compile(
    r"(?P<receiver>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)\s*"
    r"(?:\.|->)\s*set_(?P<field>[A-Za-z_]\w*)\s*\("
)
_DIRECT_ASSIGN_RE = re.compile(
    r"(?P<lhs>[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)+)\s*"
    r"(?<![=!<>])=(?!=)\s*(?P<rhs>[^;]+);",
    re.S,
)
_DEFAULT_REG_RE = re.compile(r"\bREGISTER_TILING_DEFAULT\s*\(\s*([^\)]+?)\s*\)")
_KEY_REG_RE = re.compile(
    r"\bREGISTER_TILING_FOR_TILINGKEY\s*\(\s*\"[^\"]+\"\s*,\s*([A-Za-z_:][A-Za-z0-9_:<>\s,]*)\s*\)"
)
_WORD_RE = re.compile(r"\b[A-Za-z_]\w*\b")

_KEEP_REL_PROVENANCE = {
    "source_register_tiling_for_key",
    "source_tiling_registration_verified",
}
_PURGE_REL_PROVENANCE = {
    "source_call_site",
    "source_macro_invocation",
    "source_kernel_type_reference",
    "source_frontier",
    "source_tilingdata_read",
    "source_get_tiling_data",
    "source_kernel_abi_position",
    "source_kernel_template",
    "source_kernel_template_param",
    "source_tpl_name_match",
}
_PURGE_ENTITY_PROVENANCE = {"source_scope", "source_call_site", "source_frontier"}
_BOUND_CALL_PROVENANCE = {"source_kernel_call_bound", "source_kernel_macro_call_bound"}


@dataclass(frozen=True)
class _ClassScope:
    name: str
    start: int
    end: int


@dataclass
class _Scope:
    entity: Entity
    name: str
    owner: str
    file: str
    text: str
    masked: str
    body_start: int
    body_end: int
    params: str
    param_count: int
    kind: str


@dataclass(frozen=True)
class _MacroSpan:
    name: str
    start: int
    end: int
    line: int


def finalize_kernel_tiling_closure(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    kernel_texts = _selected_kernel_texts(root, architecture)
    host_texts = _host_texts(root, architecture)
    allowed_kernel_files = {_rel(root, p) for p in kernel_texts}

    removed = _purge_broad_kernel_facts(codemap, allowed_kernel_files)
    kernel_entries, template_args, abi_links = _rebuild_kernel_contract(
        codemap, root, architecture, kernel_texts
    )

    scopes, class_names = _rebuild_kernel_scopes(codemap, root, architecture, kernel_texts)
    call_stats = _rebuild_kernel_calls(codemap, scopes, class_names)

    td_index = _tiling_index(codemap)
    read_stats = _rebuild_tiling_reads(codemap, scopes, td_index)
    write_stats = _rebuild_host_tiling_writes(codemap, root, host_texts, td_index)
    selected = _rebuild_tiling_selection(codemap, root, kernel_texts, td_index)

    reachable = _entry_reachable(codemap)
    reachable_reads = _mark_reachable_reads(codemap, reachable)
    producer_stats = _consumed_field_producers(codemap, reachable_reads)
    purity = _architecture_purity(codemap, allowed_kernel_files)

    contract_stats = dict(codemap.meta.get("source_contract_stats") or {})
    contract_stats["source_kernel_entries"] = kernel_entries
    contract_stats["source_template_args_bound"] = template_args
    contract_stats["source_kernel_abi_links"] = abi_links
    codemap.meta["source_contract_stats"] = contract_stats

    codemap.meta["kernel_tiling_closure"] = {
        "schema": "uo-kernel-tiling-closure/v1",
        "architecture": architecture,
        "selected_kernel_files": sorted(allowed_kernel_files),
        "broad_facts_removed": removed,
        "kernel_entries": kernel_entries,
        "kernel_template_args": template_args,
        "kernel_abi_links": abi_links,
        "kernel_scopes": len(scopes),
        "kernel_bound_call_sites": call_stats["bound"],
        "kernel_external_call_sites": call_stats["external"],
        "kernel_unresolved_internal_call_sites": call_stats["unresolved_internal"],
        "kernel_reachable_scopes": len(reachable),
        "tiling_data_types": len(td_index["types"]),
        "tiling_data_fields": len(td_index["fields"]),
        "tiling_registered_root_types": sorted(selected["roots"]),
        "tiling_selected_type_closure": sorted(selected["closure"]),
        "tiling_read_sites": read_stats["sites"],
        "tiling_resolved_read_sites": read_stats["resolved"],
        "tiling_ambiguous_read_sites": read_stats["ambiguous"],
        "tiling_entry_reachable_read_sites": len(reachable_reads["sites"]),
        "tiling_entry_reachable_fields": len(reachable_reads["fields"]),
        "tiling_host_writer_sites": write_stats["sites"],
        "tiling_host_writer_fields": write_stats["fields"],
        "tiling_ambiguous_writer_sites": write_stats["ambiguous"],
        "tiling_consumed_fields_with_producer": producer_stats["with_producer"],
        "tiling_consumed_fields_without_producer": producer_stats["missing"],
        "architecture_foreign_entity_facts": purity["foreign_entities"],
        "architecture_foreign_relation_facts": purity["foreign_relations"],
        "architecture_pure": purity["ok"],
        "policy": "qualified-source-closure/v1",
    }
    return codemap


def _selected_kernel_texts(root: Path, architecture: str) -> dict[Path, tuple[str, str]]:
    from uo_init.passes.source_text_cache import read_text

    out: dict[Path, tuple[str, str]] = {}
    for path in selected_kernel_files(root, architecture):
        raw = read_text(path)
        out[path.resolve()] = (raw, _mask_non_code(raw))
    return out


def _host_texts(root: Path, architecture: str) -> dict[Path, tuple[str, str]]:
    from uo_init.passes.source_text_cache import read_text

    out: dict[Path, tuple[str, str]] = {}
    for path in selected_host_files(root, architecture):
        raw = read_text(path)
        out[path.resolve()] = (raw, _mask_non_code(raw))
    return out


def _purge_broad_kernel_facts(codemap: CodeMap, allowed_kernel_files: set[str]) -> int:
    remove_rel: set[str] = set()
    remove_ent: set[str] = set()

    for rid, rel in codemap.relations.items():
        provenance = str(rel.attrs.get("provenance") or "")
        file = _norm_file(str(rel.attrs.get("file") or ""))
        if provenance in _KEEP_REL_PROVENANCE:
            continue
        if provenance in _PURGE_REL_PROVENANCE:
            remove_rel.add(rid)
        elif file and "/op_kernel/" in file and file not in allowed_kernel_files and provenance.startswith("source_"):
            remove_rel.add(rid)

    for eid, ent in codemap.entities.items():
        provenance = str(ent.attrs.get("provenance") or "")
        file = _norm_file(str(ent.file or ""))
        broad = provenance in _PURGE_ENTITY_PROVENANCE or bool(ent.attrs.get("source_scope"))
        old_template = ent.kind_name() in {EntityKind.TEMPLATE.value, EntityKind.TEMPLATE_ARG.value} and provenance == "source_kernel_template"
        if provenance in _KEEP_REL_PROVENANCE:
            continue
        foreign_source = file and "/op_kernel/" in file and file not in allowed_kernel_files and provenance.startswith("source_")
        if broad or old_template or (foreign_source and ent.kind_name() != EntityKind.KERNEL.value):
            remove_ent.add(eid)

    for rid, rel in codemap.relations.items():
        if rel.src in remove_ent or rel.dst in remove_ent:
            remove_rel.add(rid)
    for rid in remove_rel:
        codemap.relations.pop(rid, None)
    for eid in remove_ent:
        codemap.entities.pop(eid, None)
    return len(remove_rel) + len(remove_ent)


def _rebuild_kernel_contract(
    codemap: CodeMap,
    root: Path,
    architecture: str,
    texts: dict[Path, tuple[str, str]],
) -> tuple[int, int, int]:
    entries = 0
    template_args = 0
    abi_links = 0
    input_entities = sorted(
        (e for e in codemap.by_kind(EntityKind.INPUT) if e.attrs.get("api_kind") == "tensor"),
        key=lambda e: int(e.attrs.get("api_index") or 0),
    )
    output_entities = sorted(
        codemap.by_kind(EntityKind.OUTPUT), key=lambda e: int(e.attrs.get("api_index") or 0)
    )

    # Existing broad ABI/template relations were purged above. Rebuild only
    # from selected architecture entries.
    for path, (raw, masked) in texts.items():
        for match in _GLOBAL_KERNEL_RE.finditer(masked):
            name = match.group("name")
            file = _rel(root, path)
            line = _line(raw, match.start())
            hits = codemap.by_name(name, kind=EntityKind.KERNEL)
            kernel = hits[0] if hits else codemap.upsert(EntityKind.KERNEL, name)
            kernel.file = file
            kernel.line_start = line
            kernel.line_end = line
            kernel.status = "confirmed"
            kernel.confidence = 1.0
            kernel.attrs.update(
                {
                    "source_signature": True,
                    "source_definition": True,
                    "architecture": architecture,
                    "provenance": "source_kernel_signature_verified",
                }
            )
            entries += 1

            template = codemap.upsert(
                EntityKind.TEMPLATE,
                f"{name}<template>",
                eid=f"SRCKTPL::{file}::{name}",
                attrs={
                    "target": name,
                    "architecture": architecture,
                    "provenance": "source_kernel_template_verified",
                },
                file=file,
                line=line,
                status="confirmed",
            )
            codemap.link(
                RelationKind.DEFINES,
                template.id,
                kernel.id,
                attrs={"provenance": "source_kernel_template_verified", "file": file, "line": line},
                status="confirmed",
            )
            args = _TEMPLATE_PARAM_RE.findall(match.group("tpl") or "")
            for order, arg_name in enumerate(args):
                arg = codemap.upsert(
                    EntityKind.TEMPLATE_ARG,
                    arg_name,
                    eid=f"SRCKTPLARG::{file}::{name}::{order}::{arg_name}",
                    attrs={
                        "owner": name,
                        "order": order,
                        "provenance": "source_kernel_template_verified",
                    },
                    file=file,
                    line=line,
                    status="confirmed",
                )
                codemap.link(
                    RelationKind.DECLARES,
                    template.id,
                    arg.id,
                    attrs={"provenance": "source_kernel_template_verified"},
                    status="confirmed",
                )
                for key in codemap.by_name(arg_name, kind=EntityKind.TILING_KEY):
                    codemap.link(
                        RelationKind.BINDS,
                        key.id,
                        arg.id,
                        attrs={"provenance": "source_tpl_name_match_verified", "file": file, "line": line},
                        status="confirmed",
                    )
                    codemap.link(
                        RelationKind.CONTROLS,
                        arg.id,
                        kernel.id,
                        attrs={"provenance": "source_kernel_template_param_verified", "file": file, "line": line},
                        status="confirmed",
                    )
                    template_args += 1

            params = [_param_name(x) for x in _split_args(match.group("params"))]
            params = [p for p in params if p]
            if len(params) >= len(input_entities) + len(output_entities):
                for idx, inp in enumerate(input_entities):
                    rel = codemap.link(
                        RelationKind.FLOWS_TO,
                        inp.id,
                        kernel.id,
                        attrs={
                            "provenance": "source_kernel_abi_position_verified",
                            "kernel_param": params[idx],
                            "api_index": idx,
                            "file": file,
                            "line": line,
                        },
                        status="confirmed",
                    )
                    rel.attrs.update({"file": file, "line": line, "kernel_param": params[idx]})
                    abi_links += 1
                base = len(input_entities)
                for idx, out in enumerate(output_entities):
                    rel = codemap.link(
                        RelationKind.FLOWS_TO,
                        kernel.id,
                        out.id,
                        attrs={
                            "provenance": "source_kernel_abi_position_verified",
                            "kernel_param": params[base + idx],
                            "api_index": idx,
                            "file": file,
                            "line": line,
                        },
                        status="confirmed",
                    )
                    rel.attrs.update({"file": file, "line": line, "kernel_param": params[base + idx]})
                    abi_links += 1
    return entries, template_args, abi_links


def _matching_paren(text: str, close_pos: int) -> int:
    """Index of the ``(`` that matches ``text[close_pos] == ')'``, or -1."""
    if close_pos < 0 or close_pos >= len(text) or text[close_pos] != ")":
        return -1
    depth = 0
    quote = ""
    escape = False
    i = close_pos
    while i >= 0:
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            i -= 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            i -= 1
            continue
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return -1


@dataclass(frozen=True)
class _FuncHit:
    start: int
    open_brace: int
    name: str
    params: str


def _iter_function_defs(masked: str) -> list[_FuncHit]:
    """Linear scan for ``name(params) ... {`` definitions.

    Same surface as the previous single regex, without catastrophic backtracking:
    anchor on ``) ... {``, walk back to the matching ``(``, then take the
    trailing qualified identifier as the name.
    """
    out: list[_FuncHit] = []
    for body in _FUNC_BODY_START_RE.finditer(masked):
        close_paren = body.start()
        open_paren = _matching_paren(masked, close_paren)
        if open_paren < 0:
            continue
        # Look behind the ``(`` for a bounded window of return-type + name.
        window_lo = max(0, open_paren - 400)
        prefix = masked[window_lo:open_paren]
        name_match = _FUNC_NAME_TAIL_RE.search(prefix)
        if name_match is None:
            continue
        name = name_match.group("name")
        start = window_lo + name_match.start("name")
        params = masked[open_paren + 1 : close_paren]
        if "{" in params or "}" in params:
            continue
        out.append(
            _FuncHit(
                start=start,
                open_brace=body.end() - 1,
                name=name,
                params=params,
            )
        )
    return out


def _rebuild_kernel_scopes(
    codemap: CodeMap,
    root: Path,
    architecture: str,
    texts: dict[Path, tuple[str, str]],
) -> tuple[list[_Scope], set[str]]:
    scopes: list[_Scope] = []
    class_names: set[str] = set()

    for path, (raw, masked) in texts.items():
        file = _rel(root, path)
        macro_spans = _macro_spans(masked)
        classes = _class_scopes(masked)
        class_names.update(c.name for c in classes)

        # Materialise macros first so normal functions can bind invocations.
        for macro in macro_spans:
            ent = codemap.upsert(
                EntityKind.MACRO,
                macro.name,
                eid=f"SRCKMACRO::{file}::{macro.line}::{macro.name}",
                attrs={
                    "layer": "kernel",
                    "source_definition": True,
                    "architecture": architecture,
                    "provenance": "source_kernel_macro_definition",
                },
                file=file,
                line=macro.line,
                status="confirmed",
            )
            scopes.append(
                _Scope(ent, macro.name, "", file, raw, masked, macro.start, macro.end, "", 0, "macro")
            )

        accepted_end = -1
        for match in _iter_function_defs(masked):
            if _inside_span(match.start, macro_spans):
                continue
            name_expr = _compact_qualified(match.name)
            short = _short_qualified(name_expr)
            if short in _CONTROL or short == "":
                continue
            open_pos = match.open_brace
            close_pos = _matching(masked, open_pos, "{", "}")
            if close_pos < 0:
                continue
            # Hits are left-to-right; anything still inside the latest accepted
            # body is a call-like false positive, not a nested definition.
            if match.start <= accepted_end:
                continue
            accepted_end = close_pos

            containing = [c for c in classes if c.start <= match.start <= c.end]
            owner = min(containing, key=lambda c: c.end - c.start).name if containing else _owner_qualified(name_expr)
            kind = EntityKind.METHOD if owner else EntityKind.FUNCTION
            line = _line(raw, match.start)

            kernel_hits = codemap.by_name(short, kind=EntityKind.KERNEL) if not owner else []
            if kernel_hits and "__global__" in masked[match.start:open_pos]:
                ent = kernel_hits[0]
            else:
                ent = codemap.upsert(
                    kind,
                    f"{owner}::{short}" if owner else short,
                    eid=f"SRCKDEF::{file}::{line}::{owner}::{short}",
                    attrs={
                        "owner": owner,
                        "source_definition": True,
                        "architecture": architecture,
                        "provenance": "source_kernel_definition",
                    },
                    file=file,
                    line=line,
                    status="confirmed",
                )
            params = match.params or ""
            scopes.append(
                _Scope(
                    ent,
                    short,
                    owner,
                    file,
                    raw,
                    masked,
                    open_pos + 1,
                    close_pos,
                    params,
                    _arg_count(params),
                    "method" if owner else "function",
                )
            )

    return scopes, class_names


def _rebuild_kernel_calls(codemap: CodeMap, scopes: list[_Scope], class_names: set[str]) -> dict[str, int]:
    macros: dict[str, list[_Scope]] = defaultdict(list)
    free_functions: dict[str, list[_Scope]] = defaultdict(list)
    methods: dict[tuple[str, str], list[_Scope]] = defaultdict(list)
    aliases_by_file: dict[str, dict[str, set[str]]] = {}
    for scope in scopes:
        if scope.kind == "macro":
            macros[scope.name].append(scope)
        elif scope.owner:
            methods[(scope.owner, scope.name)].append(scope)
        else:
            free_functions[scope.name].append(scope)

    known_types = set(class_names)
    for scope in scopes:
        if scope.file not in aliases_by_file:
            aliases_by_file[scope.file] = _aliases(scope.masked, known_types)

    bound = 0
    external = 0
    unresolved_internal = 0
    for scope in scopes:
        body = scope.masked[scope.body_start:scope.body_end]
        var_types = _variable_types(scope, known_types, aliases_by_file.get(scope.file, {}))
        for call in _CALL_RE.finditer(body):
            absolute = scope.body_start + call.start()
            receiver = str(call.group("receiver") or "")
            name = call.group("name").split("::")[-1]
            if name in _CONTROL or name == scope.name:
                continue
            close = _matching(scope.masked, scope.body_start + call.end() - 1, "(", ")")
            argc = -1
            if close >= 0:
                argc = _arg_count(scope.masked[scope.body_start + call.end():close])
            site = {"file": scope.file, "line": _line(scope.text, absolute), "receiver": receiver, "call": name}

            candidates: list[_Scope] = []
            provenance = "source_kernel_call_bound"
            internal_hint = False
            if not receiver and name in macros:
                candidates = macros[name]
                provenance = "source_kernel_macro_call_bound"
                internal_hint = True
            elif receiver:
                owner_candidates = set(var_types.get(receiver) or ())
                if receiver == "this" and scope.owner:
                    owner_candidates.add(scope.owner)
                if owner_candidates:
                    internal_hint = True
                    for owner in owner_candidates:
                        candidates.extend(methods.get((owner, name), ()))
            else:
                if scope.owner and methods.get((scope.owner, name)):
                    candidates.extend(methods[(scope.owner, name)])
                    internal_hint = True
                if free_functions.get(name):
                    candidates.extend(free_functions[name])
                    internal_hint = True

            candidates = _dedupe_scopes(candidates)
            if argc >= 0:
                exact_arity = [c for c in candidates if c.param_count == argc]
                if exact_arity:
                    candidates = exact_arity
            if len(candidates) == 1:
                _link_site(codemap, RelationKind.CALLS, scope.entity.id, candidates[0].entity.id, provenance, site)
                bound += 1
                continue
            if len(candidates) > 1:
                # Conditional/static dispatch is source-sound when receiver type
                # explicitly names multiple local classes (e.g. std::conditional).
                owner_candidates = set(var_types.get(receiver) or ()) if receiver else set()
                candidate_owners = {c.owner for c in candidates if c.owner}
                if receiver and len(owner_candidates) > 1 and candidate_owners <= owner_candidates:
                    for target in candidates:
                        _link_site(
                            codemap,
                            RelationKind.CALLS,
                            scope.entity.id,
                            target.entity.id,
                            provenance,
                            {**site, "conditional_dispatch": True},
                        )
                    bound += 1
                    continue
                _unresolved_call(codemap, scope, site, candidates)
                unresolved_internal += 1
                continue
            if internal_hint:
                _unresolved_call(codemap, scope, site, [])
                unresolved_internal += 1
            else:
                external += 1

        # Rebuild branch ownership on verified scopes.
        for branch in _BRANCH_RE.finditer(body):
            absolute = scope.body_start + branch.start()
            line = _line(scope.text, absolute)
            node = codemap.upsert(
                EntityKind.BRANCH,
                f"{scope.entity.name}:{branch.group(1).replace(' ', '_')}@{line}",
                eid=f"SRCKBRANCH::{scope.file}::{line}::{scope.entity.id}",
                attrs={
                    "branch_kind": branch.group(1).replace(" ", "_"),
                    "owner": scope.entity.name,
                    "provenance": "source_kernel_frontier_bound",
                },
                file=scope.file,
                line=line,
                status="confirmed",
            )
            codemap.link(
                RelationKind.CONTROLS,
                node.id,
                scope.entity.id,
                attrs={"provenance": "source_kernel_frontier_bound", "file": scope.file, "line": line},
                status="confirmed",
            )
    return {"bound": bound, "external": external, "unresolved_internal": unresolved_internal}


def _tiling_index(codemap: CodeMap) -> dict[str, Any]:
    types = {e.name: e for e in codemap.by_kind(EntityKind.TILING_DATA)}
    known = set(types)
    fields: dict[tuple[str, str], Entity] = {}
    by_name: dict[str, list[Entity]] = defaultdict(list)
    nested: dict[str, set[str]] = defaultdict(set)
    for field in codemap.by_kind(EntityKind.TILING_FIELD):
        owner = str(field.attrs.get("owner") or "")
        fields[(owner, field.name)] = field
        by_name[field.name].append(field)
        cpp_type = str(field.attrs.get("cpp_type") or "")
        # std::conditional / decltype spellings need token intersection, not
        # a single outer _base_type (which collapses to conditional_t).
        nested[field.name].update(
            t for t in re.findall(r"\b[A-Za-z_]\w*\b", cpp_type) if t in known
        )
        target = _base_type(cpp_type)
        if target in types:
            nested[field.name].add(target)
    return {"types": types, "fields": fields, "by_name": by_name, "nested": nested}


def _rebuild_tiling_reads(codemap: CodeMap, scopes: list[_Scope], index: dict[str, Any]) -> dict[str, int]:
    sites = resolved = ambiguous = 0
    aliases_by_file: dict[str, dict[str, set[str]]] = {}
    tdata_names = set(index["types"])
    for scope in scopes:
        if scope.file not in aliases_by_file:
            aliases_by_file[scope.file] = _aliases(scope.masked, tdata_names)
        var_types = _variable_types(scope, tdata_names, aliases_by_file[scope.file])
        body = scope.masked[scope.body_start:scope.body_end]
        for match in _TILING_READ_RE.finditer(body):
            sites += 1
            base, outer, inner = match.group("base"), match.group("outer"), match.group("inner")
            candidates = _resolve_tiling_field(index, base, outer, inner, var_types)
            absolute = scope.body_start + match.start()
            line = _line(scope.text, absolute)
            expression = scope.text[absolute: scope.body_start + match.end()].replace("\n", " ").strip()
            if len(candidates) == 1:
                field = candidates[0]
                _link_site(
                    codemap,
                    RelationKind.READS,
                    scope.entity.id,
                    field.id,
                    "source_tilingdata_read_qualified",
                    {
                        "file": scope.file,
                        "line": line,
                        "expression": expression,
                        "field_owner": field.attrs.get("owner"),
                    },
                )
                resolved += 1
            else:
                ambiguous += 1
                ref = codemap.upsert(
                    EntityKind.OTHER,
                    expression,
                    eid=f"TDREADREF::{scope.file}::{line}::{scope.entity.id}::{outer}::{inner or ''}",
                    attrs={
                        "role": "tilingdata_read_unresolved",
                        "reason": "field_owner_ambiguous" if candidates else "field_owner_unknown",
                        "outer": outer,
                        "inner": inner or "",
                        "candidate_fields": [f.attrs.get("qualified_name") for f in candidates],
                        "provenance": "source_tilingdata_read_unresolved",
                    },
                    file=scope.file,
                    line=line,
                    status="partial",
                    confidence=0.5,
                )
                codemap.link(
                    RelationKind.REFERENCES,
                    scope.entity.id,
                    ref.id,
                    attrs={"provenance": "source_tilingdata_read_unresolved", "file": scope.file, "line": line},
                    status="partial",
                    confidence=0.5,
                )
    return {"sites": sites, "resolved": resolved, "ambiguous": ambiguous}


def _rebuild_host_tiling_writes(
    codemap: CodeMap,
    root: Path,
    texts: dict[Path, tuple[str, str]],
    index: dict[str, Any],
) -> dict[str, int]:
    sites = ambiguous = 0
    written_fields: set[str] = set()
    known_types = set(index["types"])
    global_types: dict[str, set[str]] = defaultdict(set)
    for _path, (_raw, masked) in texts.items():
        aliases = _aliases(masked, known_types)
        for var, types in _declaration_types(masked, known_types, aliases).items():
            global_types[var].update(types)

    for path, (raw, masked) in texts.items():
        file = _rel(root, path)
        for match in _SETTER_HEAD_RE.finditer(masked):
            close = _matching(masked, match.end() - 1, "(", ")")
            if close < 0:
                continue
            sites += 1
            receiver = normalize_symbol(match.group("receiver"))
            field_name = match.group("field")
            expr = raw[match.end():close].strip()
            candidates = _resolve_writer_field(index, receiver, field_name, global_types)
            line = _line(raw, match.start())
            if len(candidates) == 1:
                field = candidates[0]
                _record_writer(codemap, field, file, line, receiver, expr, "setter")
                written_fields.add(field.id)
            else:
                ambiguous += 1
                _record_unresolved_writer(codemap, file, line, receiver, field_name, expr, candidates)

        for match in _DIRECT_ASSIGN_RE.finditer(masked):
            lhs = normalize_symbol(match.group("lhs"))
            parts = lhs.split(".")
            if len(parts) < 2:
                continue
            receiver = ".".join(parts[:-1])
            field_name = parts[-1]
            # Direct assignment is only treated as a TilingData write when the
            # receiver has a known TilingData type.  No unique-short-name fallback.
            if not _receiver_type_candidates(index, receiver, global_types):
                continue
            sites += 1
            expr = raw[match.start("rhs"):match.end("rhs")].strip()
            candidates = _resolve_writer_field(index, receiver, field_name, global_types, allow_unique=False)
            line = _line(raw, match.start())
            if len(candidates) == 1:
                field = candidates[0]
                _record_writer(codemap, field, file, line, receiver, expr, "assignment")
                written_fields.add(field.id)
            else:
                ambiguous += 1
                _record_unresolved_writer(codemap, file, line, receiver, field_name, expr, candidates)

    _attach_default_initializers(codemap, root, index)
    return {"sites": sites, "fields": len(written_fields), "ambiguous": ambiguous}


def _rebuild_tiling_selection(
    codemap: CodeMap,
    root: Path,
    texts: dict[Path, tuple[str, str]],
    index: dict[str, Any],
) -> dict[str, set[str]]:
    roots: set[str] = set()
    tdata_names = set(index["types"])
    for path, (raw, masked) in texts.items():
        file = _rel(root, path)
        aliases = _aliases(masked, tdata_names)
        for match in _DEFAULT_REG_RE.finditer(masked):
            roots.update(_type_candidates(match.group(1), tdata_names, aliases))
        for match in _KEY_REG_RE.finditer(masked):
            roots.update(_type_candidates(match.group(1), tdata_names, aliases))

    # Existing explicit TilingKey registrations are also source-backed.
    for rel in codemap.relations.values():
        if rel.kind_name() != RelationKind.SELECTS.value:
            continue
        if str(rel.attrs.get("provenance") or "") != "source_register_tiling_for_key":
            continue
        target = codemap.entities.get(rel.dst)
        if target is not None and target.kind_name() == EntityKind.TILING_DATA.value:
            roots.add(target.name)

    closure = set(roots)
    q = deque(roots)
    while q:
        owner = q.popleft()
        owner_ent = index["types"].get(owner)
        if owner_ent is None:
            continue
        declared_fields = [
            codemap.entities.get(rel.dst)
            for rel in codemap.relations.values()
            if rel.src == owner_ent.id and rel.kind_name() == RelationKind.DECLARES.value
        ]
        for field in declared_fields:
            if field is None or field.kind_name() != EntityKind.TILING_FIELD.value:
                continue
            nested = _base_type(str(field.attrs.get("cpp_type") or ""))
            if nested in index["types"] and nested not in closure:
                closure.add(nested)
                q.append(nested)

    kernels = codemap.by_kind(EntityKind.KERNEL)
    for type_name in roots:
        td = index["types"].get(type_name)
        if td is None:
            continue
        td.attrs["selected_by_kernel_entry"] = True
        for kernel in kernels:
            codemap.link(
                RelationKind.FLOWS_TO,
                td.id,
                kernel.id,
                attrs={"provenance": "source_tiling_registration_verified"},
                status="confirmed",
            )
    return {"roots": roots, "closure": closure}


def _entry_reachable(codemap: CodeMap) -> set[str]:
    starts = {e.id for e in codemap.by_kind(EntityKind.KERNEL) if e.attrs.get("source_definition") or e.attrs.get("source_signature")}
    adj: dict[str, set[str]] = defaultdict(set)
    for rel in codemap.relations.values():
        if rel.kind_name() == RelationKind.CALLS.value and str(rel.attrs.get("provenance") or "") in _BOUND_CALL_PROVENANCE:
            adj[rel.src].add(rel.dst)
    seen = set(starts)
    q = deque(starts)
    while q:
        cur = q.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return seen


def _mark_reachable_reads(codemap: CodeMap, reachable: set[str]) -> dict[str, set[str]]:
    sites: set[str] = set()
    fields: set[str] = set()
    for rel in codemap.relations.values():
        if rel.kind_name() != RelationKind.READS.value or str(rel.attrs.get("provenance") or "") != "source_tilingdata_read_qualified":
            continue
        is_reachable = rel.src in reachable
        rel.attrs["entry_reachable"] = is_reachable
        if is_reachable:
            fields.add(rel.dst)
            for site in rel.attrs.get("sites") or []:
                sites.add(f"{site.get('file')}:{site.get('line')}:{rel.src}:{rel.dst}")
            if not rel.attrs.get("sites"):
                sites.add(rel.id)
    return {"sites": sites, "fields": fields}


def _consumed_field_producers(codemap: CodeMap, reachable_reads: dict[str, set[str]]) -> dict[str, Any]:
    incoming: dict[str, list[Any]] = defaultdict(list)
    for rel in codemap.relations.values():
        incoming[rel.dst].append(rel)
    missing: list[str] = []
    with_producer = 0
    for field_id in sorted(reachable_reads["fields"]):
        field = codemap.entities.get(field_id)
        if field is None:
            continue
        writer = any(
            rel.kind_name() == RelationKind.WRITES.value and str(rel.attrs.get("provenance") or "") == "source_tilingdata_host_write"
            for rel in incoming.get(field_id, ())
        )
        default = bool(field.attrs.get("default_initializer"))
        if writer or default:
            with_producer += 1
        else:
            missing.append(str(field.attrs.get("qualified_name") or f"{field.attrs.get('owner')}::{field.name}"))
    return {"with_producer": with_producer, "missing": missing}


def _architecture_purity(codemap: CodeMap, allowed_kernel_files: set[str]) -> dict[str, Any]:
    foreign_entities: list[str] = []
    foreign_relations: list[str] = []
    for ent in codemap.entities.values():
        file = _norm_file(str(ent.file or ""))
        provenance = str(ent.attrs.get("provenance") or "")
        if file and "/op_kernel/" in file and file not in allowed_kernel_files and provenance.startswith("source_"):
            foreign_entities.append(ent.id)
    for rel in codemap.relations.values():
        file = _norm_file(str(rel.attrs.get("file") or ""))
        provenance = str(rel.attrs.get("provenance") or "")
        if file and "/op_kernel/" in file and file not in allowed_kernel_files and provenance.startswith("source_"):
            foreign_relations.append(rel.id)
    return {"ok": not foreign_entities and not foreign_relations, "foreign_entities": foreign_entities[:50], "foreign_relations": foreign_relations[:50]}


def _resolve_tiling_field(
    index: dict[str, Any],
    base: str,
    outer: str,
    inner: str | None,
    var_types: dict[str, set[str]],
) -> list[Entity]:
    if inner:
        nested_types = set(index["nested"].get(outer) or ())
        # Walk base owner → outer member type when the nested map is incomplete.
        if not nested_types:
            for owner in var_types.get(base) or ():
                parent = index["fields"].get((owner, outer))
                if parent is None:
                    continue
                cpp_type = str(parent.attrs.get("cpp_type") or "")
                nested_types.update(
                    t for t in re.findall(r"\b[A-Za-z_]\w*\b", cpp_type) if t in index["types"]
                )
                target = _base_type(cpp_type)
                if target in index["types"]:
                    nested_types.add(target)
        candidates = [index["fields"].get((owner, inner)) for owner in nested_types]
        return _unique_entities(candidates)
    owner_types = set(var_types.get(base) or ())
    candidates = [index["fields"].get((owner, outer)) for owner in owner_types]
    candidates = _unique_entities(candidates)
    if candidates:
        return candidates
    return list(index["by_name"].get(outer) or ()) if len(index["by_name"].get(outer) or ()) == 1 else []


def _resolve_writer_field(
    index: dict[str, Any],
    receiver: str,
    field_name: str,
    var_types: dict[str, set[str]],
    *,
    allow_unique: bool = True,
) -> list[Entity]:
    owners = _receiver_type_candidates(index, receiver, var_types)
    candidates = [index["fields"].get((owner, field_name)) for owner in owners]
    candidates = _unique_entities(candidates)
    if candidates:
        return candidates
    if allow_unique and len(index["by_name"].get(field_name) or ()) == 1:
        return list(index["by_name"][field_name])
    return []


def _nested_owner_names(index: dict[str, Any], name: str) -> set[str]:
    """Lookup nested packing types by member name, with trailing-``_`` tolerance.

    Host code often names a local ``subParams_`` that mirrors the TilingData
    member ``subParams``; both should resolve to the same nested type set.
    """
    out = set(index["nested"].get(name) or ())
    if not out and name.endswith("_"):
        out.update(index["nested"].get(name[:-1]) or ())
    return out


def _receiver_type_candidates(index: dict[str, Any], receiver: str, var_types: dict[str, set[str]]) -> set[str]:
    parts = [p for p in normalize_symbol(receiver).split(".") if p]
    if not parts:
        return set()
    known = set(index["types"])
    owners = set(var_types.get(parts[0]) or ())
    if not owners and parts[0].endswith("_"):
        owners.update(var_types.get(parts[0][:-1]) or ())
    # Bare nested packing receiver: ``subParams_.set_x`` where ``subParams`` is
    # a TilingData member whose cpp_type is a packing type (or conditional).
    if not owners:
        owners.update(_nested_owner_names(index, parts[0]))
    for segment in parts[1:]:
        next_owners: set[str] = set()
        if owners:
            for owner in owners:
                field = index["fields"].get((owner, segment))
                if field is None and segment.endswith("_"):
                    field = index["fields"].get((owner, segment[:-1]))
                if field is None:
                    continue
                cpp_type = str(field.attrs.get("cpp_type") or "")
                next_owners.update(
                    t for t in re.findall(r"\b[A-Za-z_]\w*\b", cpp_type) if t in known
                )
                nested = _base_type(cpp_type)
                if nested in known:
                    next_owners.add(nested)
        else:
            next_owners.update(_nested_owner_names(index, segment))
        owners = next_owners
    if not owners:
        owners.update(_nested_owner_names(index, parts[-1]))
    return owners


def _record_writer(codemap: CodeMap, field: Entity, file: str, line: int, receiver: str, expr: str, mode: str) -> None:
    owner = str(field.attrs.get("owner") or "")
    writer = codemap.upsert(
        EntityKind.PREDICATE,
        f"{owner}::{field.name} <- {expr[:120]}",
        eid=f"TDWRITE::{file}::{line}::{owner}::{field.name}",
        attrs={
            "predicate_role": "tilingdata_writer",
            "owner": owner,
            "field": field.name,
            "receiver": receiver,
            "expression": expr[:600],
            "write_mode": mode,
            "provenance": "source_tilingdata_host_write",
        },
        file=file,
        line=line,
        status="confirmed",
    )
    codemap.link(
        RelationKind.WRITES,
        writer.id,
        field.id,
        attrs={"provenance": "source_tilingdata_host_write", "file": file, "line": line, "mode": mode},
        status="confirmed",
    )
    sites = field.attrs.setdefault("host_writer_sites", [])
    site = {"file": file, "line": line, "receiver": receiver, "expression": expr[:300], "mode": mode}
    if site not in sites:
        sites.append(site)
    field.attrs["host_writer_site_count"] = len(sites)


def _record_unresolved_writer(
    codemap: CodeMap,
    file: str,
    line: int,
    receiver: str,
    field_name: str,
    expr: str,
    candidates: list[Entity],
) -> None:
    codemap.upsert(
        EntityKind.OTHER,
        f"{receiver}.set_{field_name}",
        eid=f"TDWRITEREF::{file}::{line}::{field_name}",
        attrs={
            "role": "tilingdata_writer_unresolved",
            "reason": "field_owner_ambiguous" if candidates else "field_owner_unknown",
            "receiver": receiver,
            "field": field_name,
            "expression": expr[:600],
            "candidate_fields": [f.attrs.get("qualified_name") for f in candidates],
            "provenance": "source_tilingdata_writer_unresolved",
        },
        file=file,
        line=line,
        status="partial",
        confidence=0.5,
    )


def _attach_default_initializers(codemap: CodeMap, root: Path, index: dict[str, Any]) -> None:
    cache: dict[str, list[str]] = {}
    for field in index["fields"].values():
        if not field.file or not field.line_start:
            continue
        if field.file not in cache:
            path = _resolve_file(root, field.file)
            if path is None:
                cache[field.file] = []
            else:
                cache[field.file] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = cache[field.file]
        if not (1 <= int(field.line_start) <= len(lines)):
            continue
        source = lines[int(field.line_start) - 1]
        match = re.search(rf"\b{re.escape(field.name)}\b\s*=\s*([^;]+);", source)
        if not match:
            continue
        field.attrs["default_initializer"] = match.group(1).strip()
        field.attrs["default_initializer_site"] = {"file": field.file, "line": int(field.line_start)}


def _unresolved_call(codemap: CodeMap, scope: _Scope, site: dict[str, Any], candidates: list[_Scope]) -> None:
    line = int(site["line"])
    name = f"{site.get('receiver') + '.' if site.get('receiver') else ''}{site.get('call')}"
    ref = codemap.upsert(
        EntityKind.METHOD,
        name,
        eid=f"SRCKCALLREF::{scope.file}::{line}::{scope.entity.id}::{name}",
        attrs={
            "call_target": site.get("call"),
            "receiver": site.get("receiver"),
            "candidate_definitions": [c.entity.id for c in candidates],
            "internal_unresolved": True,
            "provenance": "source_kernel_call_unresolved",
        },
        file=scope.file,
        line=line,
        status="partial",
        confidence=0.5,
    )
    codemap.link(
        RelationKind.CALLS,
        scope.entity.id,
        ref.id,
        attrs={"provenance": "source_kernel_call_unresolved", "file": scope.file, "line": line},
        status="partial",
        confidence=0.5,
    )


def _link_site(codemap: CodeMap, kind: RelationKind, src: str, dst: str, provenance: str, site: dict[str, Any]) -> None:
    rel = codemap.link(kind, src, dst, attrs={"provenance": provenance, **site}, status="confirmed")
    rel.attrs["provenance"] = provenance
    sites = rel.attrs.setdefault("sites", [])
    clean = dict(site)
    if clean not in sites:
        sites.append(clean)


def _class_scopes(masked: str) -> list[_ClassScope]:
    out: list[_ClassScope] = []
    for match in _CLASS_RE.finditer(masked):
        open_pos = masked.find("{", match.start(), match.end())
        close_pos = _matching(masked, open_pos, "{", "}")
        if close_pos >= 0:
            out.append(_ClassScope(match.group(1), open_pos + 1, close_pos))
    return out


def _macro_spans(masked: str) -> list[_MacroSpan]:
    lines = masked.splitlines(keepends=True)
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    out: list[_MacroSpan] = []
    i = 0
    while i < len(lines):
        match = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)", lines[i])
        if not match:
            i += 1
            continue
        start_i = i
        while i < len(lines) - 1 and lines[i].rstrip("\n\r").rstrip().endswith("\\"):
            i += 1
        end_i = i
        out.append(_MacroSpan(match.group(1), offsets[start_i], offsets[end_i] + len(lines[end_i]), start_i + 1))
        i += 1
    return out


def _inside_span(offset: int, spans: Iterable[_MacroSpan]) -> bool:
    return any(span.start <= offset < span.end for span in spans)


def _aliases(text: str, known_types: set[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    # Two passes allow aliases to reference earlier aliases.
    raw: dict[str, str] = {m.group(1): m.group(2) for m in _ALIAS_RE.finditer(text)}
    for _ in range(2):
        for name, rhs in raw.items():
            types = set(_WORD_RE.findall(rhs)) & known_types
            for token in _WORD_RE.findall(rhs):
                types.update(out.get(token) or ())
            if types:
                out[name] = types
    return out


def _variable_types(scope: _Scope, known_types: set[str], aliases: dict[str, set[str]]) -> dict[str, set[str]]:
    out = _declaration_types(scope.params + ";" + scope.masked[scope.body_start:scope.body_end], known_types, aliases)
    if scope.owner:
        out.setdefault("this", set()).add(scope.owner)
    return out


def _declaration_types(text: str, known_types: set[str], aliases: dict[str, set[str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    # Parameters/statements are intentionally split coarsely; candidate types
    # are accepted only when they appear before the final declarator token.
    fragments = list(_split_args(text.split(";", 1)[0])) if ";" not in text else []
    fragments.extend(x for x in text.split(";") if x.strip())
    for fragment in fragments:
        stripped = fragment.strip()
        if not stripped or stripped.startswith(("using ", "return ", "if ", "for ", "while ", "switch ")):
            continue
        match = re.search(r"\b([A-Za-z_]\w*)\s*(?:\([^;]*\))?\s*$", stripped)
        if not match:
            continue
        var = match.group(1)
        prefix = stripped[:match.start(1)]
        types = _type_candidates(prefix, known_types, aliases)
        if types and var not in known_types and var not in aliases:
            out[var].update(types)
    return out


def _type_candidates(fragment: str, known_types: set[str], aliases: dict[str, set[str]]) -> set[str]:
    tokens = set(_WORD_RE.findall(fragment))
    out = tokens & known_types
    for token in tokens:
        out.update(aliases.get(token) or ())
    return out


def _dedupe_scopes(scopes: Iterable[_Scope]) -> list[_Scope]:
    out: list[_Scope] = []
    seen: set[str] = set()
    for scope in scopes:
        if scope.entity.id in seen:
            continue
        seen.add(scope.entity.id)
        out.append(scope)
    return out


def _unique_entities(items: Iterable[Entity | None]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for item in items:
        if item is None or item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return out


def _compact_qualified(name: str) -> str:
    return re.sub(r"\s+", "", name or "")


def _short_qualified(name: str) -> str:
    return name.split("::")[-1].split("<", 1)[0].strip()


def _owner_qualified(name: str) -> str:
    parts = name.split("::")
    if len(parts) < 2:
        return ""
    return parts[-2].split("<", 1)[0].strip()


def _base_type(raw: str) -> str:
    text = re.sub(r"\b(?:const|volatile|typename|class|struct)\b", " ", raw or "")
    text = text.replace("*", " ").replace("&", " ").strip()
    # Strip template arguments while retaining the outer type.
    text = re.sub(r"<.*>", "", text).strip()
    return text.split("::")[-1].strip().split()[-1] if text else ""


def _param_name(raw: str) -> str:
    raw = raw.split("=", 1)[0].strip()
    match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", raw)
    return match.group(1) if match else ""


def _arg_count(text: str) -> int:
    stripped = text.strip()
    if not stripped or stripped == "void":
        return 0
    return len(_split_args(stripped))


def _split_args(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch in "(<[{":
            depth += 1
            buf.append(ch)
        elif ch in ")>]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out


def _matching(text: str, open_pos: int, opener: str, closer: str) -> int:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != opener:
        return -1
    depth = 0
    for idx in range(open_pos, len(text)):
        ch = text[idx]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return idx
    return -1


def _mask_non_code(text: str) -> str:
    out = list(text)
    i = 0
    state = "code"
    quote = ""
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "line"
                continue
            if ch == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                i += 2
                state = "block"
                continue
            if ch in {'\"', "'"}:
                quote = ch
                out[i] = " "
                i += 1
                state = "string"
                continue
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = "code"
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "code"
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
            continue
        if state == "string":
            if ch == "\\" and i + 1 < len(text):
                out[i] = " "
                if text[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == quote:
                out[i] = " "
                i += 1
                state = "code"
            else:
                if ch != "\n":
                    out[i] = " "
                i += 1
    return "".join(out)


def _resolve_file(root: Path, raw: str) -> Path | None:
    rel = raw.replace("\\", "/").lstrip("./")
    candidates = [root.parent / rel, root / rel]
    if rel.startswith(root.name + "/"):
        candidates.append(root / rel[len(root.name) + 1:])
    for path in candidates:
        if path.is_file():
            return path
    return None


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _norm_file(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1
