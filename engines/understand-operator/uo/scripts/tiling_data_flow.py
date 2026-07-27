"""TilingData FieldWrite 流：HostValue → FieldWrite → TilingField。

保留同一字段多次写入的 order / guard / reaching_definition。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo.scripts.host_contract_schema import (
    make_edge,
    make_entity,
    make_evidence,
    make_expression_ir,
    make_guard_context,
)
from uo.scripts.receiver_binding import (
    build_get_tiling_data_index,
    build_macro_discovery_index,
    extract_receiver_bindings_from_text,
    index_bindings_by_receiver,
    select_binding_for_guard,
)

FLOW_VERSION = "1.1.0"

SETTER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<root>[A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*"
    r"(?:(?P<nested>[A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*)?"
    r"set_(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(?P<rhs>[^;]*?)\s*\)\s*;"
)
DIRECT_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<recv>[A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*"
    r"(?P<field>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*=\s*(?P<rhs>[^;]+);"
)
IF_RE = re.compile(r"\bif\s*(?:constexpr\s*)?\((?P<cond>[^)]+)\)")

_NOISE_SYMBOLS = frozenset(
    {
        "true",
        "false",
        "nullptr",
        "NULL",
        "this",
        "return",
        "if",
        "else",
        "auto",
        "const",
        "static",
        "sizeof",
        "uint32_t",
        "uint64_t",
        "int32_t",
        "int64_t",
        "size_t",
        "int",
        "float",
        "double",
        "bool",
        "void",
        "std",
        "ge",
        "gert",
        "AscendC",
        "OP_LOGI",
        "OP_LOGW",
        "OP_LOGE",
        "static_cast",
        "reinterpret_cast",
    }
)


def _guards_by_line(text: str, start_line: int = 1) -> dict[int, str]:
    guards: dict[int, str] = {}
    stack: list[tuple[int, str]] = []
    lines = text.splitlines()
    for offset, line in enumerate(lines):
        line_no = start_line + offset
        for m in IF_RE.finditer(line):
            stack.append((line_no, m.group("cond").strip()))
        if "}" in line and stack:
            stack.pop()
        guards[line_no] = stack[-1][1] if stack else "true"
    return guards


def _symbols_in(rhs: str) -> list[str]:
    raw = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", rhs or "")
    out: list[str] = []
    seen: set[str] = set()
    for sym in raw:
        if sym in _NOISE_SYMBOLS or sym.startswith("OP_"):
            continue
        if sym.startswith("set_"):
            continue
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _dedupe_unresolved(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for u in items:
        if not isinstance(u, dict):
            continue
        key = "|".join(
            [
                str(u.get("reason_code") or ""),
                str(u.get("receiver") or ""),
                str(u.get("field") or u.get("field_path") or ""),
                str(u.get("symbol") or ""),
                str(u.get("file_path") or ""),
                str(u.get("line") or ""),
                str(u.get("root_variable") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def extract_field_writes_from_text(
    text: str,
    *,
    file_path: str,
    writer_function: str,
    compile_context_id: str,
    architecture: str,
    start_line: int = 1,
    schema_fields_by_path: dict[str, str] | None = None,
    macro_index: dict[str, dict[str, Any]] | None = None,
    gtd_index: dict[str, str] | None = None,
    binding_text: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 entities, edges, evidence, unresolved。

    binding_text：用于解析 receiver binding 的更大上下文（整文件 / preamble），
    默认与 text 相同。
    """
    entities: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    bind_src = binding_text if binding_text is not None else text
    bindings = extract_receiver_bindings_from_text(
        bind_src,
        file_path=file_path,
        macro_index=macro_index,
        gtd_index=gtd_index,
        suppress_receiver_unresolved=True,
    )
    real_bindings = [
        b
        for b in bindings
        if b.get("receiver")
        and (
            b.get("canonical")
            or str(b.get("nested_path") or "").lower().find("tiling") >= 0
            or str(b.get("nested_path") or "").endswith("Params")
            or str(b.get("nested_path") or "").endswith("Data")
            or str(b.get("receiver") or "").endswith("_")
        )
    ]
    # binding 阶段的 unresolved 仅保留宏替换失败等；身份歧义留到 FieldWrite
    for b in bindings:
        for u in b.get("binding_unresolved") or []:
            if u.get("reason_code") == "RECEIVER_IDENTITY_AMBIGUOUS":
                continue
            unresolved.append(u)
    by_recv = index_bindings_by_receiver(real_bindings)
    # GetTilingData 根指针本身也可作为 FieldWrite receiver（无 nested）
    for var, schema in (gtd_index or {}).items():
        if var in by_recv:
            continue
        by_recv[var] = {
            "receiver": var,
            "root_variable": var,
            "root_schema_variant": schema,
            "nested_path": "",
            "nested_field": "",
            "canonical": True,
            "evidence": ["get_tiling_data_root"],
        }
    # Also from binding text local GTD
    from uo.scripts.receiver_binding import extract_get_tiling_data_bindings

    for item in extract_get_tiling_data_bindings(bind_src):
        var = str(item.get("root_variable") or "")
        schema = str(item.get("root_schema_variant") or "")
        if var and schema and var not in by_recv:
            by_recv[var] = {
                "receiver": var,
                "root_variable": var,
                "root_schema_variant": schema,
                "nested_path": "",
                "nested_field": "",
                "canonical": True,
                "evidence": ["get_tiling_data_root"],
            }
    guards = _guards_by_line(text, start_line=start_line)
    order = 0
    writes_by_field: dict[str, list[str]] = {}

    def _emit(recv: str, field: str, rhs: str, line_no: int, kind: str) -> None:
        nonlocal order
        order += 1
        raw_binding = by_recv.get(recv) or {}
        guard_cond = guards.get(line_no, "true")
        binding = select_binding_for_guard(raw_binding, guard_cond)
        schema_variant = str(binding.get("root_schema_variant") or "")
        nested = str(binding.get("nested_path") or binding.get("nested_field") or "")
        field_path = f"{nested}.{field}" if nested and not field.startswith(nested) else field
        ev = make_evidence(
            file_path=file_path,
            start_line=line_no,
            extractor="tiling_data_flow",
            extractor_version=FLOW_VERSION,
            evidence_level="structured_source_fact",
        )
        evidence.append(ev)
        if not binding.get("canonical"):
            unresolved.append(
                {
                    "reason_code": "RECEIVER_IDENTITY_AMBIGUOUS",
                    "receiver": recv,
                    "field": field,
                    "line": line_no,
                    "file_path": file_path,
                    "message": "receiver 未绑定到具体 SchemaVariant，FieldWrite 标记 unresolved",
                }
            )
        rhs_expr = make_expression_ir(kind="rhs", source_text=rhs, symbols=_symbols_in(rhs))
        fw = make_entity(
            kind="FieldWrite",
            identity_key=f"{writer_function}:{recv}:{field_path}:{line_no}:{order}",
            qualified_name=f"{recv}.{field_path}",
            binding_time="host_runtime",
            architecture=architecture,
            compile_context_id=compile_context_id,
            evidence_refs=[ev["id"]],
            extra={
                "writer_function": writer_function,
                "receiver": recv,
                "schema_variant": schema_variant,
                "field_path": field_path,
                "rhs_expression_ir": rhs_expr,
                "rhs_dependencies": list(rhs_expr["symbols"]),
                "guard_context": make_guard_context(
                    binding_time="host_runtime",
                    condition_text=guard_cond,
                ),
                "order_in_function": order,
                "write_kind": kind,
            },
        )
        entities.append(fw)
        recv_ent = make_entity(
            kind="Receiver",
            identity_key=f"Receiver:{recv}:{file_path}",
            qualified_name=recv,
            binding_time="host_runtime",
            architecture=architecture,
            compile_context_id=compile_context_id,
            extra={
                "root_variable": binding.get("root_variable"),
                "root_schema_variant": schema_variant,
                "nested_path": nested,
            },
        )
        entities.append(recv_ent)
        field_id = None
        if schema_fields_by_path:
            field_id = schema_fields_by_path.get(field_path) or schema_fields_by_path.get(field)
            if schema_variant:
                field_id = (
                    schema_fields_by_path.get(f"{schema_variant}::{field_path}")
                    or schema_fields_by_path.get(f"{schema_variant}.{field_path}")
                    or field_id
                )
        if not field_id:
            field_ent = make_entity(
                kind="TilingField",
                identity_key=f"field:{schema_variant or 'Unknown'}:{field_path}",
                qualified_name=field_path,
                binding_time="build_time",
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={
                    "field_path": field_path,
                    "tiling_schema_variant_id": schema_variant,
                },
            )
            entities.append(field_ent)
            field_id = field_ent["id"]
            if not schema_variant:
                unresolved.append(
                    {
                        "reason_code": "TILING_SCHEMA_VARIANT_AMBIGUOUS",
                        "field_path": field_path,
                        "receiver": recv,
                        "line": line_no,
                        "file_path": file_path,
                        "message": "Field 关联的 schema variant 未知",
                    }
                )

        edges.append(
            make_edge(
                edge_type="WRITES_FIELD",
                source_ids=[fw["id"]],
                target_ids=[field_id],
                guard_context=fw.get("guard_context") or {},
                evidence_refs=[ev["id"]],
            )
        )
        for sym in rhs_expr["symbols"]:
            edges.append(
                make_edge(
                    edge_type="DERIVES",
                    source_ids=[],
                    target_ids=[fw["id"]],
                    transform={"symbol": sym, "role": "rhs_dependency"},
                    evidence_refs=[ev["id"]],
                    extra={"pending_host_value_symbol": sym},
                )
            )
        writes_by_field.setdefault(field_path, []).append(fw["id"])

    for offset, line in enumerate(text.splitlines()):
        line_no = start_line + offset
        for m in SETTER_RE.finditer(line):
            root = m.group("root")
            nested = (m.group("nested") or "").strip()
            field = m.group("field")
            rhs = m.group("rhs")
            if nested:
                # tilingData->emptyTensorTilingData.set_x → 合成 nested receiver binding
                root_bind = by_recv.get(root) or {}
                schema = str(root_bind.get("root_schema_variant") or "")
                if not schema and root in (gtd_index or {}):
                    schema = str(gtd_index.get(root) or "")
                if not schema:
                    # root 本身是 GetTilingData 变量
                    from uo.scripts.receiver_binding import extract_get_tiling_data_bindings

                    for item in extract_get_tiling_data_bindings(bind_src):
                        if item.get("root_variable") == root:
                            schema = str(item.get("root_schema_variant") or "")
                            break
                synth_recv = nested
                if synth_recv not in by_recv and schema:
                    by_recv[synth_recv] = {
                        "receiver": synth_recv,
                        "root_variable": root,
                        "root_schema_variant": schema,
                        "nested_path": nested,
                        "nested_field": nested,
                        "canonical": True,
                        "evidence": ["nested_setter_chain"],
                    }
                _emit(synth_recv, field, rhs, line_no, "setter")
            else:
                _emit(root, field, rhs, line_no, "setter")
        for m in DIRECT_ASSIGN_RE.finditer(line):
            field = m.group("field")
            recv = m.group("recv")
            if field.startswith("set_"):
                continue
            if recv not in by_recv and not str(recv).endswith("_"):
                continue
            _emit(recv, field, m.group("rhs"), line_no, "direct_assign")

    for field_path, write_ids in writes_by_field.items():
        for idx, wid in enumerate(write_ids):
            for ent in entities:
                if ent["id"] == wid:
                    ent["reaching_definition"] = idx == len(write_ids) - 1
                    ent["write_version"] = idx + 1
                    ent["field_write_chain"] = list(write_ids)

    return entities, edges, evidence, _dedupe_unresolved(unresolved)


def _lookup_host_value(sym: str, host_values: dict[str, str]) -> str | None:
    if sym in host_values:
        return host_values[sym]
    # a->b / a.b → try leaf then root
    leaf = sym.split("->")[-1].split(".")[-1]
    if leaf in host_values:
        return host_values[leaf]
    root = re.split(r"->|\.", sym, maxsplit=1)[0]
    if root in host_values:
        return host_values[root]
    return None


def build_tiling_data_flow(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
    function_bodies: list[dict[str, Any]] | None = None,
    schema_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.ascendc_macro_facts import _confirmed_source_files, _relative_path
    from uo.scripts.host_compile_context import load_host_compile_context
    from uo.scripts.host_configuration_builder import (
        build_host_value_symbol_index,
        load_host_configuration,
    )

    root = uo_root or existing_operator_root(repo_root, op_name)
    ctx = load_host_compile_context(root)
    ccid = str(ctx.get("compile_context_id") or "")
    hcg = load_host_configuration(root)

    schema_fields_by_path: dict[str, str] = {}
    for ent in schema_entities or []:
        if ent.get("kind") in {"TilingField", "NestedTilingField"}:
            fp = str(ent.get("field_path") or ent.get("qualified_name") or "")
            if fp:
                schema_fields_by_path[fp] = ent["id"]
                leaf = fp.split(".")[-1]
                schema_fields_by_path.setdefault(leaf, ent["id"])
            schema = str(
                ent.get("tiling_schema_variant_id")
                or ent.get("schema_variant")
                or ""
            )
            if schema and fp:
                schema_fields_by_path.setdefault(f"{schema}::{fp}", ent["id"])
                schema_fields_by_path.setdefault(f"{schema}.{fp}", ent["id"])

    # Include-closure texts for macro / GTD index
    closure_files = list(
        (ctx.get("include_closure") or {}).get("files")
        or ctx.get("confirmed_source_files")
        or []
    )
    texts_by_rel: dict[str, str] = {}
    for rel in closure_files:
        rel_s = str(rel).replace("\\", "/")
        path = Path(rel_s)
        if not path.is_absolute():
            path = repo_root / rel_s
        if not path.is_file():
            # try op-relative
            cand = root.parent.parent / rel_s if False else repo_root / rel_s
            if cand.is_file():
                path = cand
            else:
                continue
        try:
            texts_by_rel[rel_s] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

    # Also load all confirmed host files
    for path in _confirmed_source_files(root, repo_root):
        rel = _relative_path(path, repo_root)
        if rel not in texts_by_rel:
            try:
                texts_by_rel[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

    macro_index = build_macro_discovery_index(texts_by_rel)
    gtd_index = build_get_tiling_data_index(texts_by_rel)

    bodies = function_bodies
    if bodies is None:
        bodies = []
        for rel, text in texts_by_rel.items():
            if "op_host" not in rel.replace("\\", "/"):
                continue
            for summary in hcg.get("function_summaries") or []:
                if summary.get("file_path") != rel:
                    continue
                name = str(summary.get("function_name") or "")
                m = re.search(
                    rf"\b{re.escape(name)}\s*\([^)]*\)\s*(?:const\s*)?\{{",
                    text,
                )
                if not m:
                    continue
                start = text.find("{", m.start())
                depth = 0
                end = start
                for i in range(start, len(text)):
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                bodies.append(
                    {
                        "function": name,
                        "file_path": rel,
                        "start_line": text.count("\n", 0, m.start()) + 1,
                        "body": text[start + 1 : end],
                        "file_text": text,
                    }
                )

    entities: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    host_values = build_host_value_symbol_index(hcg)

    for body_info in bodies:
        file_text = str(body_info.get("file_text") or body_info.get("body") or "")
        ents, eds, evs, uns = extract_field_writes_from_text(
            body_info["body"],
            file_path=body_info["file_path"],
            writer_function=body_info["function"],
            compile_context_id=ccid,
            architecture=architecture,
            start_line=int(body_info.get("start_line") or 1),
            schema_fields_by_path=schema_fields_by_path,
            macro_index=macro_index,
            gtd_index=gtd_index,
            binding_text=file_text,
        )
        for edge in eds:
            sym = edge.get("pending_host_value_symbol")
            if not sym:
                continue
            hid = _lookup_host_value(str(sym), host_values)
            if hid:
                edge["source_ids"] = [hid]
                edge.pop("pending_host_value_symbol", None)
                continue
            edge.pop("pending_host_value_symbol", None)
            # 本地结构体字段 / 成员访问根：不强制 HostValue 接地
            # 仅对「看起来像独立 Host 派生量」且完全未命中的裸符号报 unresolved
            sym_s = str(sym)
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", sym_s):
                continue
            if sym_s.endswith("_") or sym_s[0].isupper():
                # receiver_/TypeName — 非 HostValue 键
                continue
            if re.search(r"(Params|Info|Data|Shape|Desc|Context)$", sym_s):
                continue
            if sym_s in {"coreNum", "b", "n", "s", "d", "g", "idx", "tmp", "ret", "status"}:
                continue
            # 若同函数已有同名 HostValue 索引失败，记一条（后续可 LLM）
            unresolved.append(
                {
                    "reason_code": "VALUE_SOURCE_UNRESOLVED",
                    "symbol": sym_s,
                    "edge_id": edge.get("id"),
                    "file_path": body_info["file_path"],
                    "message": "FieldWrite RHS 符号未追溯到 HostValue",
                }
            )
        entities.extend(ents)
        edges.extend(eds)
        evidence.extend(evs)
        unresolved.extend(uns)

    return {
        "version": FLOW_VERSION,
        "compile_context_id": ccid,
        "architecture": architecture,
        "entities": entities,
        "edges": edges,
        "evidence": evidence,
        "unresolved": _dedupe_unresolved(unresolved),
    }
