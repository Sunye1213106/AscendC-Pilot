"""Host Configuration Graph builder。

ConfigurationRoot → HostValue / HostDerivedValue / HostPredicate，
经 HostFunctionSummary + 有限跨过程组合。

第一版边界：明确调用目标、实参→形参、引用/指针字段写入、this 成员、
明确 return、setter/getter summary；无指针算术、无复杂 alias merge。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.ascendc_macro_facts import _confirmed_source_files, _relative_path
from uo.scripts.host_compile_context import load_host_compile_context
from uo.scripts.host_contract_schema import (
    empty_graph_doc,
    make_edge,
    make_entity,
    make_evidence,
    make_expression_ir,
    make_guard_context,
)

BUILDER_VERSION = "1.1.0"

HOST_API_ROOT_KIND = {
    "GetInputShape": "ShapeRoot",
    "GetOptionalInputShape": "ShapeRoot",
    "GetInputDesc": "OperatorInputRoot",
    "GetOptionalInputDesc": "OptionalInputRoot",
    "GetInputDtype": "OperatorInputRoot",
    "GetOptionalInputDtype": "OptionalInputRoot",
    "GetDataType": "OperatorInputRoot",
    "GetAttr": "OperatorAttributeRoot",
    "GetAttrOptional": "OperatorAttributeRoot",
    "GetAttrPointer": "OperatorAttributeRoot",
    "GetPlatformInfo": "PlatformRoot",
    "PlatformAscendC": "PlatformRoot",
    "GetCoreNum": "PlatformRoot",
    "GetCoreNumAiv": "PlatformRoot",
    "GetCoreNumAic": "PlatformRoot",
    "GetUbSize": "PlatformRoot",
    "GetL1Size": "PlatformRoot",
}

# GE / GERT host accessors（通用，非算子特化）
HOST_ACCESSOR_METHODS = frozenset(
    {
        "GetDim",
        "GetDimNum",
        "GetShape",
        "GetStorageShape",
        "GetOriginShape",
        "GetStorageFormat",
        "GetOriginFormat",
        "GetDataType",
        "GetFormat",
        "GetOutputShape",
        "GetInputShape",
        "GetOptionalInputShape",
        "GetAttr",
        "GetInt",
        "GetBool",
        "GetFloat",
        "GetString",
        "GetListInt",
        "GetListFloat",
        "GetName",
        "GetSize",
        "GetWorkSpaceSize",
        "GetBlockDim",
        "GetTilingKey",
        "GetCompileInfo",
        "GetPlatformInfo",
        "GetRequiredAttr",
        "GetOptionalAttr",
        "GetInputDesc",
        "GetOutputDesc",
        "GetOptionalInputDesc",
        "GetAttrNum",
        "GetWorkspaceSizes",
        "GetRawShape",
    }
)

EXTERNAL_STDLIB = frozenset(
    {
        "to_string",
        "c_str",
        "strcmp",
        "strncmp",
        "strlen",
        "memcpy",
        "memset",
        "memmove",
        "printf",
        "sprintf",
        "snprintf",
        "fprintf",
        "abort",
        "exit",
        "assert",
        "static_cast",
        "reinterpret_cast",
        "const_cast",
        "dynamic_cast",
        "make_shared",
        "make_unique",
        "move",
        "forward",
        "get",
        "size",
        "empty",
        "clear",
        "push_back",
        "emplace_back",
        "resize",
        "reserve",
        "begin",
        "end",
        "find",
        "count",
        "insert",
        "erase",
        "at",
        "data",
        "max",
        "min",
        "abs",
        "ceil",
        "floor",
        "round",
        "log",
        "log2",
        "pow",
        "sqrt",
        "ToString",
        "toString",
        "StringUtils",
        "Format",
        "AppendFormat",
        "std",
        "vector",
        "string",
        "map",
        "unordered_map",
        "set",
        "pair",
        "tuple",
        "optional",
        "numeric_limits",
        "is_same",
        "enable_if",
        "declval",
        "fill",
        "copy",
        "int64_t",
        "int32_t",
        "uint64_t",
        "uint32_t",
        "size_t",
        "str",
        "second",
        "first",
        "T",
    }
)

# 框架序列化 / workspace 等非跨过程 Host 语义
EXTERNAL_FRAMEWORK = frozenset(
    {
        "DataTypeToSerialString",
        "FormatToSerialString",
        "GetShapeSize",
        "GetSizeByDataType",
        "GetPrimaryFormat",
        "SetBlockDim",
        "SetTilingKey",
        "SetDataSize",
        "GetData",
        "GetCapacity",
        "SaveToBuffer",
        "GetInputsNum",
        "GetOutputsNum",
        "GetTilingTemplates",
        "InitTilingInfo",
        "IsCapable",
        "DoOpTiling",
        "GetWorkspaceSizes",
        "SetWorkspaceSizes",
        "GetInstance",
        "GetPlatformInfoWithContext",
    }
)

CONTROL_KEYWORDS = frozenset(
    {
        "if",
        "while",
        "for",
        "switch",
        "sizeof",
        "return",
        "case",
        "default",
        "catch",
        "try",
        "throw",
        "new",
        "delete",
        "typeof",
        "decltype",
        "alignof",
        "noexcept",
        "static_assert",
    }
)

FUNC_DEF_KEYWORDS = frozenset(
    {
        "if",
        "while",
        "for",
        "switch",
        "catch",
        "else",
        "do",
        "try",
        "sizeof",
        "return",
        "case",
        "default",
        "new",
        "delete",
    }
)

API_CALL_RE = re.compile(
    r"\b(?P<api>"
    + "|".join(sorted(HOST_API_ROOT_KIND.keys(), key=len, reverse=True))
    + r")\s*(?:<[^>]*>)?\s*\(\s*(?P<arg>[^)]*)\)"
)
ASSIGN_RE = re.compile(
    r"(?P<lhs>(?:this->)?[A-Za-z_][A-Za-z0-9_]*(?:(?:->|\.)[A-Za-z_][A-Za-z0-9_]*)*)\s*=\s*(?P<rhs>[^;]+);"
)
SETTER_RE = re.compile(
    r"(?P<recv>[A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*set_(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(?P<rhs>[^;]*?)\s*\)\s*;"
)
GETTER_RE = re.compile(
    r"(?P<recv>[A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*(?P<method>Get[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(?P<arg>[^)]*)\)"
)
IF_RE = re.compile(r"\bif\s*(?:constexpr\s*)?\((?P<cond>[^)]+)\)")
RETURN_RE = re.compile(r"\breturn\s+(?P<expr>[^;]+);")
FUNC_DEF_RE = re.compile(
    r"(?P<ret>[\w:<>,\s\*&]+?)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<params>[^)]*)\)\s*(?:const\s*)?\{",
    re.MULTILINE,
)
CALL_RE = re.compile(r"\b(?P<callee>[A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _load_operator_boundary(uo_root: Path) -> dict[str, Any]:
    return read_yaml(uo_root / "ir" / "operator_boundary.yaml") or {}


def _load_cann_api_aliases() -> set[str]:
    path = Path(__file__).resolve().parents[1] / "resources" / "cann_api_catalog.yaml"
    data = read_yaml(path) or {}
    names: set[str] = set(HOST_API_ROOT_KIND.keys()) | set(HOST_ACCESSOR_METHODS)
    for item in data.get("apis") or data.get("entries") or data.get("contracts") or []:
        if isinstance(item, dict):
            name = str(
                item.get("name")
                or item.get("api")
                or item.get("symbol_or_macro")
                or ""
            )
            if name:
                names.add(name)
    # optional host_accessors list in catalog
    for name in data.get("host_accessors") or []:
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


def _is_external_macro(name: str) -> bool:
    if not name:
        return False
    if name.startswith("OP_") or name.startswith("GE_") or name.startswith("ACL_"):
        return True
    # ALL_CAPS function-like macros (at least one underscore, length>=4)
    if len(name) >= 4 and name.isupper() and "_" in name and name.replace("_", "").isalnum():
        return True
    return False


def classify_callee(
    callee: str,
    *,
    cann_aliases: set[str] | None = None,
    modeled_methods: set[str] | None = None,
) -> str:
    """返回 call 分类：external_stdlib / external_macro / modeled_local / internal_candidate。"""
    name = str(callee or "").strip()
    if not name or name in CONTROL_KEYWORDS:
        return "modeled_local"
    aliases = cann_aliases or set()
    modeled = modeled_methods or set()
    if name in EXTERNAL_STDLIB or name in EXTERNAL_FRAMEWORK:
        return "external_stdlib"
    if name in HOST_API_ROOT_KIND or name in HOST_ACCESSOR_METHODS or name in aliases:
        return "modeled_local"
    if name in modeled or name.startswith("set_"):
        return "modeled_local"
    if _is_external_macro(name):
        return "external_macro"
    return "internal_candidate"


def build_configuration_roots(
    boundary: dict[str, Any],
    *,
    compile_context_id: str,
    architecture: str,
) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    for item in boundary.get("inputs") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("registered_name") or "")
        idx = item.get("index", item.get("slot"))
        optional = bool(item.get("optional") or item.get("is_optional"))
        kind = "OptionalInputRoot" if optional else "OperatorInputRoot"
        identity = f"{kind}:{name or idx}"
        roots.append(
            make_entity(
                kind=kind,
                identity_key=identity,
                qualified_name=name or f"input_slot[{idx}]",
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={"slot_index": idx, "registered_name": name, "root_class": "ConfigurationRoot"},
            )
        )
        roots.append(
            make_entity(
                kind="ShapeRoot",
                identity_key=f"ShapeRoot:{name or idx}",
                qualified_name=f"{name or idx}.shape",
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={"input_ref": identity, "root_class": "ConfigurationRoot"},
            )
        )
    for item in boundary.get("attributes") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("registered_name") or "")
        identity = f"OperatorAttributeRoot:{name}"
        roots.append(
            make_entity(
                kind="OperatorAttributeRoot",
                identity_key=identity,
                qualified_name=name,
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={"root_class": "ConfigurationRoot"},
            )
        )
    for kind, qn in (
        ("PlatformRoot", "platform"),
        ("BuildConfigRoot", "build_config"),
        ("ArchitectureRoot", architecture or "architecture"),
        ("ConstantRoot", "constants"),
        ("RegistrationRoot", "registration"),
    ):
        roots.append(
            make_entity(
                kind=kind,
                identity_key=f"{kind}:{qn}",
                qualified_name=qn,
                binding_time="build_time" if kind != "PlatformRoot" else "host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={"root_class": "ConfigurationRoot"},
            )
        )
    return roots


def summarize_function(
    *,
    function_name: str,
    body: str,
    file_path: str,
    start_line: int,
    params: list[str],
    compile_context_id: str,
    architecture: str,
    cann_aliases: set[str] | None = None,
) -> dict[str, Any]:
    """生成 HostFunctionSummary（单函数效应摘要）。"""
    aliases = cann_aliases if cann_aliases is not None else _load_cann_api_aliases()
    parameter_reads: list[str] = []
    parameter_writes: list[dict[str, Any]] = []
    member_reads: list[str] = []
    member_writes: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    skipped_calls: list[dict[str, Any]] = []
    guarded_effects: list[dict[str, Any]] = []
    return_expression: dict[str, Any] | None = None
    values: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    modeled_on_line: set[str] = set()

    param_names = []
    for p in params:
        tok = p.strip().split()[-1].replace("&", "").replace("*", "") if p.strip() else ""
        if tok and re.match(r"^[A-Za-z_]", tok):
            param_names.append(tok)

    lines = body.splitlines()
    for offset, line in enumerate(lines):
        line_no = start_line + offset
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            continue
        line_modeled: set[str] = set()

        for m in API_CALL_RE.finditer(line):
            api = m.group("api")
            arg = (m.group("arg") or "").strip()
            root_kind = HOST_API_ROOT_KIND.get(api, "OperatorInputRoot")
            line_modeled.add(api)
            ev = make_evidence(
                file_path=file_path,
                start_line=line_no,
                extractor="host_configuration_builder",
                extractor_version=BUILDER_VERSION,
                evidence_level="structured_source_fact",
            )
            evidence.append(ev)
            expr = make_expression_ir(
                kind="call",
                op=api,
                operands=[{"literal": arg}] if arg else [],
                source_text=m.group(0),
            )
            identity = f"{function_name}:{api}:{arg}:{line_no}"
            hv = make_entity(
                kind="HostValue",
                identity_key=identity,
                qualified_name=f"{api}({arg})",
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                evidence_refs=[ev["id"]],
                extra={
                    "expression_ir": expr,
                    "definition_site": {"file_path": file_path, "start_line": line_no},
                    "input_dependencies": [],
                    "api": api,
                    "api_arg": arg,
                    "lhs_text": "",
                    "root_kind_hint": root_kind,
                    "guard_context": make_guard_context(binding_time="host_runtime"),
                    "confidence": "deterministic",
                },
            )
            values.append(hv)
            root_id_hint = f"{root_kind}:{arg.strip('\"')}" if arg else root_kind
            edges.append(
                make_edge(
                    edge_type="READS_INPUT" if "Input" in api or "Attr" in api else "READS_PLATFORM",
                    source_ids=[hv["id"]],
                    target_ids=[],
                    evidence_refs=[ev["id"]],
                    extra={"root_kind_hint": root_kind, "root_identity_hint": root_id_hint},
                )
            )

        for m in GETTER_RE.finditer(line):
            method = m.group("method")
            recv = m.group("recv")
            arg = (m.group("arg") or "").strip()
            if method not in HOST_ACCESSOR_METHODS and method not in aliases and not method.startswith("Get"):
                continue
            # Prefer known accessors; still model any Get* chain as HostDerivedValue
            if method not in HOST_ACCESSOR_METHODS and method not in aliases:
                if not method.startswith("Get"):
                    continue
            line_modeled.add(method)
            ev = make_evidence(
                file_path=file_path,
                start_line=line_no,
                extractor="host_configuration_builder",
                extractor_version=BUILDER_VERSION,
                evidence_level="structured_source_fact",
            )
            evidence.append(ev)
            expr = make_expression_ir(
                kind="call",
                op=method,
                operands=[{"symbol": recv}, {"literal": arg}] if arg else [{"symbol": recv}],
                source_text=m.group(0),
                symbols=[recv],
            )
            qn = f"{recv}->{method}({arg})" if arg else f"{recv}->{method}()"
            hv = make_entity(
                kind="HostDerivedValue",
                identity_key=f"{function_name}:{qn}:{line_no}",
                qualified_name=qn,
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                evidence_refs=[ev["id"]],
                extra={
                    "expression_ir": expr,
                    "definition_site": {"file_path": file_path, "start_line": line_no},
                    "api": method,
                    "receiver": recv,
                    "api_arg": arg,
                    "lhs_text": "",
                    "root_kind_hint": "ShapeRoot" if "Shape" in method or method == "GetDim" else "OperatorInputRoot",
                    "guard_context": make_guard_context(binding_time="host_runtime"),
                    "confidence": "deterministic",
                },
            )
            values.append(hv)
            edges.append(
                make_edge(
                    edge_type="READS_INPUT",
                    source_ids=[hv["id"]],
                    target_ids=[],
                    evidence_refs=[ev["id"]],
                    extra={
                        "root_kind_hint": hv["root_kind_hint"],
                        "root_identity_hint": hv["root_kind_hint"],
                    },
                )
            )

        for m in ASSIGN_RE.finditer(line):
            lhs = m.group("lhs").strip()
            rhs = m.group("rhs").strip()
            ev = make_evidence(
                file_path=file_path,
                start_line=line_no,
                extractor="host_configuration_builder",
                extractor_version=BUILDER_VERSION,
                evidence_level="structured_source_fact",
            )
            evidence.append(ev)
            expr = make_expression_ir(kind="assign", op="=", symbols=[lhs], source_text=stripped)
            identity = f"{function_name}:{lhs}:{line_no}"
            simple_name = lhs.split("->")[-1].split(".")[-1]
            hv = make_entity(
                kind="HostDerivedValue" if any(op in rhs for op in "+-*/%?:<>") else "HostValue",
                identity_key=identity,
                qualified_name=lhs,
                binding_time="host_runtime",
                architecture=architecture,
                compile_context_id=compile_context_id,
                evidence_refs=[ev["id"]],
                extra={
                    "expression_ir": expr,
                    "definition_site": {"file_path": file_path, "start_line": line_no},
                    "input_dependencies": [],
                    "rhs_text": rhs,
                    "lhs_text": lhs,
                    "simple_name": simple_name,
                    "guard_context": make_guard_context(binding_time="host_runtime"),
                    "confidence": "deterministic",
                },
            )
            values.append(hv)
            if lhs.startswith("this->") or lhs.startswith("this."):
                member_writes.append({"member": lhs, "rhs": rhs, "line": line_no, "value_id": hv["id"]})
            for pn in param_names:
                if pn in lhs or f"{pn}." in lhs or f"{pn}->" in lhs:
                    parameter_writes.append(
                        {"parameter": pn, "lhs": lhs, "rhs": rhs, "line": line_no, "value_id": hv["id"]}
                    )
                if re.search(rf"\b{re.escape(pn)}\b", rhs):
                    parameter_reads.append(pn)

        for m in SETTER_RE.finditer(line):
            line_modeled.add(f"set_{m.group('field')}")
            guarded_effects.append(
                {
                    "kind": "setter",
                    "receiver": m.group("recv"),
                    "field": m.group("field"),
                    "rhs": m.group("rhs"),
                    "line": line_no,
                }
            )

        for m in IF_RE.finditer(line):
            cond = m.group("cond").strip()
            binding = "kernel_compile_time" if "constexpr" in line else "host_runtime"
            pred = make_entity(
                kind="HostPredicate" if binding == "host_runtime" else "CompilePredicate",
                identity_key=f"{function_name}:pred:{line_no}:{cond[:40]}",
                qualified_name=cond,
                binding_time=binding,
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={
                    "expression_ir": make_expression_ir(kind="predicate", source_text=cond),
                    "guard_context": make_guard_context(
                        binding_time=binding,
                        selection_effect=["selects_tiling_implementation"],
                        condition_text=cond,
                    ),
                },
            )
            values.append(pred)

        for m in RETURN_RE.finditer(line):
            return_expression = make_expression_ir(
                kind="return", source_text=m.group("expr").strip()
            )

        modeled_on_line |= line_modeled
        for m in CALL_RE.finditer(line):
            callee = m.group("callee")
            cls = classify_callee(
                callee,
                cann_aliases=aliases,
                modeled_methods=line_modeled | modeled_on_line,
            )
            if cls != "internal_candidate":
                skipped_calls.append(
                    {"callee": callee, "line": line_no, "classification": cls}
                )
                continue
            calls.append(
                {
                    "callee": callee,
                    "line": line_no,
                    "classification": cls,
                    "caller_file": file_path,
                }
            )

    fn_entity = make_entity(
        kind="HostFunction",
        identity_key=f"HostFunction:{function_name}:{file_path}",
        qualified_name=function_name,
        binding_time="host_runtime",
        architecture=architecture,
        compile_context_id=compile_context_id,
        extra={"file_path": file_path, "start_line": start_line},
    )

    return {
        "function_id": fn_entity["id"],
        "function_name": function_name,
        "file_path": file_path,
        "start_line": start_line,
        "parameters": param_names,
        "parameter_reads": sorted(set(parameter_reads)),
        "parameter_writes": parameter_writes,
        "member_reads": member_reads,
        "member_writes": member_writes,
        "return_expression": return_expression,
        "calls": calls,
        "skipped_calls": skipped_calls,
        "guarded_effects": guarded_effects,
        "entity": fn_entity,
        "values": values,
        "edges": edges,
        "evidence": evidence,
        "unresolved": unresolved,
    }


def _resolve_callee(
    callee: str,
    caller_file: str,
    by_file_name: dict[tuple[str, str], dict[str, Any]],
    by_name: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str]:
    """返回 (summary_or_None, reason_if_fail)。"""
    key = (caller_file, callee)
    if key in by_file_name:
        return by_file_name[key], ""
    cands = by_name.get(callee) or []
    if len(cands) == 1:
        return cands[0], ""
    if len(cands) > 1:
        # Prefer same-directory / same stem
        same_dir = [
            c
            for c in cands
            if Path(str(c.get("file_path") or "")).parent
            == Path(caller_file or ".").parent
        ]
        if len(same_dir) == 1:
            return same_dir[0], ""
        return None, "HOST_CALL_TARGET_AMBIGUOUS"
    return None, "HOST_CALL_TARGET_NOT_FOUND"


def _compose_interprocedural(
    summaries: list[dict[str, Any]],
    roots_by_hint: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    """按调用图组合 summary 效应（有限）。返回 entities, edges, unresolved, skipped_external_count。"""
    entities: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    skipped_external = 0

    by_file_name: dict[tuple[str, str], dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for s in summaries:
        name = str(s.get("function_name") or "")
        fp = str(s.get("file_path") or "")
        if not name:
            continue
        by_file_name[(fp, name)] = s
        by_name.setdefault(name, []).append(s)
        skipped_external += len(s.get("skipped_calls") or [])

    for summary in summaries:
        entities.append(summary["entity"])
        entities.extend(summary.get("values") or [])
        for edge in summary.get("edges") or []:
            e = dict(edge)
            root_hint = str(e.get("root_identity_hint") or "")
            root_kind = str(e.get("root_kind_hint") or "")
            target = roots_by_hint.get(root_hint) or roots_by_hint.get(root_kind)
            if target:
                e["target_ids"] = [target]
            edges.append(e)

        caller_file = str(summary.get("file_path") or "")
        for call in summary.get("calls") or []:
            callee = str(call.get("callee") or "")
            cal, reason = _resolve_callee(callee, caller_file, by_file_name, by_name)
            if not cal:
                unresolved.append(
                    {
                        "reason_code": reason or "HOST_CALL_TARGET_NOT_FOUND",
                        "caller": summary.get("function_name"),
                        "callee": callee,
                        "line": call.get("line"),
                        "file_path": caller_file,
                        "message": (
                            "同名函数多个候选，未展开跨过程效应"
                            if reason == "HOST_CALL_TARGET_AMBIGUOUS"
                            else "调用目标未在 HostFunctionSummary 索引中"
                        ),
                    }
                )
                continue
            edges.append(
                make_edge(
                    edge_type="CALLS",
                    source_ids=[summary["function_id"]],
                    target_ids=[cal["function_id"]],
                    extra={"line": call.get("line")},
                )
            )
            for mw in cal.get("member_writes") or []:
                edges.append(
                    make_edge(
                        edge_type="DERIVES",
                        source_ids=[summary["function_id"]],
                        target_ids=[mw["value_id"]],
                        transform={"via": "callee_member_write", "member": mw.get("member")},
                        origin="deterministic_summary",
                    )
                )

    return entities, edges, unresolved, skipped_external


def _extract_function_spans(text: str, rel: str) -> list[dict[str, Any]]:
    """从源文件提取函数定义 spans（排除控制关键字伪匹配）。"""
    spans: list[dict[str, Any]] = []
    for m in FUNC_DEF_RE.finditer(text):
        name = m.group("name")
        if name in FUNC_DEF_KEYWORDS:
            continue
        params_raw = [p.strip() for p in (m.group("params") or "").split(",") if p.strip()]
        body_start = m.end() - 1
        start_line = text.count("\n", 0, m.start()) + 1
        depth = 0
        end = body_start
        for i in range(body_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = text[body_start + 1 : end]
        if not body.strip():
            continue
        spans.append(
            {
                "name": name,
                "params": params_raw,
                "body": body,
                "start_line": start_line,
                "file_path": rel,
            }
        )
    return spans


def build_host_configuration(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
    seed_functions: list[str] | None = None,
) -> dict[str, Any]:
    """构建并写出 ir/host_configuration_graph.yaml。"""
    t0 = time.perf_counter()
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    ctx = load_host_compile_context(root)
    compile_context_id = str(ctx.get("compile_context_id") or "")
    snapshot = str(ctx.get("source_snapshot_hash") or "")
    boundary = _load_operator_boundary(root)
    cann_aliases = _load_cann_api_aliases()

    doc = empty_graph_doc(
        graph_kind="host_configuration",
        compile_context_id=compile_context_id,
        architecture=architecture,
        source_snapshot_hash=snapshot,
    )
    roots = build_configuration_roots(
        boundary, compile_context_id=compile_context_id, architecture=architecture
    )
    roots_by_hint: dict[str, str] = {}
    for r in roots:
        roots_by_hint[str(r["identity_key"])] = str(r["id"])
        roots_by_hint[str(r["kind"])] = str(r["id"])
        qn = str(r.get("qualified_name") or "")
        if qn:
            roots_by_hint[f"{r['kind']}:{qn}"] = str(r["id"])
            roots_by_hint[f"{r['kind']}:\"{qn}\""] = str(r["id"])

    source_files = _confirmed_source_files(root, repo_root)
    host_files = [
        p
        for p in source_files
        if "op_host" in str(p).replace("\\", "/") or "tiling" in p.name.lower()
    ] or source_files

    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    ep = read_yaml(ir_dir / "entrypoint_graph.yaml") or {}
    seeds = set(seed_functions or [])
    for edge in ep.get("edges") or []:
        if edge.get("type") in {"binds_tiling", "binds_tiling_parse"}:
            seeds.add(str(edge.get("target") or ""))
    for node in ep.get("nodes") or []:
        if str(node.get("role") or "") in {"public_host_entry", "host_tiling"}:
            qn = str(node.get("qualified_name") or node.get("name") or "")
            if qn:
                seeds.add(qn.split("::")[-1])

    # Pass 1: collect all spans
    all_spans: list[dict[str, Any]] = []
    for path in host_files:
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
        for span in _extract_function_spans(text, rel):
            all_spans.append(span)

    by_name_spans: dict[str, list[dict[str, Any]]] = {}
    for span in all_spans:
        by_name_spans.setdefault(span["name"], []).append(span)

    # Pass 2: seed interesting + call-graph closure
    interesting_names: set[str] = set()
    for span in all_spans:
        name = span["name"]
        body = span["body"]
        if (
            name in seeds
            or "tiling" in name.lower()
            or "Tiling" in name
            or any(api in body for api in HOST_API_ROOT_KIND)
            or "GetTilingData" in body
            or "set_" in body
        ):
            interesting_names.add(name)

    # Expand closure: callees of interesting that exist in spans
    changed = True
    while changed:
        changed = False
        for span in all_spans:
            if span["name"] not in interesting_names:
                continue
            for m in CALL_RE.finditer(span["body"]):
                callee = m.group("callee")
                if classify_callee(callee, cann_aliases=cann_aliases) != "internal_candidate":
                    continue
                if callee in by_name_spans and callee not in interesting_names:
                    interesting_names.add(callee)
                    changed = True

    summaries: list[dict[str, Any]] = []
    summarized_keys: set[tuple[str, str, int]] = set()
    for span in all_spans:
        if span["name"] not in interesting_names:
            continue
        key = (span["file_path"], span["name"], span["start_line"])
        if key in summarized_keys:
            continue
        summarized_keys.add(key)
        summary = summarize_function(
            function_name=span["name"],
            body=span["body"],
            file_path=span["file_path"],
            start_line=span["start_line"],
            params=span["params"],
            compile_context_id=compile_context_id,
            architecture=architecture,
            cann_aliases=cann_aliases,
        )
        summaries.append(summary)
        evidence.extend(summary.get("evidence") or [])
        unresolved.extend(summary.get("unresolved") or [])

    composed_entities, composed_edges, compose_unresolved, skipped_external = (
        _compose_interprocedural(summaries, roots_by_hint)
    )
    unresolved.extend(compose_unresolved)

    for edge in composed_edges:
        if edge.get("target_ids"):
            continue
        hint = str(edge.get("root_identity_hint") or "")
        kind = str(edge.get("root_kind_hint") or "")
        target = roots_by_hint.get(hint) or roots_by_hint.get(kind)
        if target:
            edge["target_ids"] = [target]

    value_by_id = {e["id"]: e for e in composed_entities if str(e.get("kind") or "").startswith("Host")}
    for edge in composed_edges:
        if edge.get("type") != "DERIVES":
            continue
        for sid in edge.get("source_ids") or []:
            ent = value_by_id.get(sid)
            if ent and "expression_ir" not in ent and not (ent.get("extra") or {}).get("expression_ir"):
                unresolved.append(
                    {
                        "reason_code": "VALUE_SOURCE_UNRESOLVED",
                        "edge_id": edge.get("id"),
                        "entity_id": sid,
                        "message": "DERIVES 边缺少 expression_ir",
                    }
                )

    doc["entities"] = roots + composed_entities
    doc["edges"] = composed_edges
    doc["evidence"] = evidence
    doc["unresolved"] = unresolved
    doc["function_summaries"] = [
        {
            "function_id": s["function_id"],
            "function_name": s["function_name"],
            "file_path": s["file_path"],
            "parameters": s["parameters"],
            "parameter_reads": s["parameter_reads"],
            "parameter_writes": s["parameter_writes"],
            "member_writes": s["member_writes"],
            "calls": s["calls"],
            "skipped_calls": s.get("skipped_calls") or [],
            "guarded_effects": s["guarded_effects"],
            "return_expression": s["return_expression"],
        }
        for s in summaries
    ]
    doc["counts"] = {
        "entities": len(doc["entities"]),
        "edges": len(doc["edges"]),
        "roots": len(roots),
        "summaries": len(summaries),
        "unresolved": len(unresolved),
        "skipped_external_calls": skipped_external,
    }
    doc["builder_version"] = BUILDER_VERSION
    doc["timing_ms"] = int((time.perf_counter() - t0) * 1000)
    write_yaml(ir_dir / "host_configuration_graph.yaml", doc)
    return doc


def load_host_configuration(uo_root: Path) -> dict[str, Any]:
    return read_yaml(uo_root / "ir" / "host_configuration_graph.yaml") or {}


def build_host_value_symbol_index(hcg: dict[str, Any]) -> dict[str, str]:
    """qualified_name / lhs_text / simple_name → entity id。"""
    out: dict[str, str] = {}
    for e in hcg.get("entities") or []:
        if e.get("kind") not in {"HostValue", "HostDerivedValue", "HostPredicate"}:
            continue
        eid = str(e.get("id") or "")
        if not eid:
            continue
        for key in (
            str(e.get("qualified_name") or ""),
            str(e.get("lhs_text") or ""),
            str(e.get("simple_name") or ""),
        ):
            if key:
                out.setdefault(key, eid)
                leaf = key.split("->")[-1].split(".")[-1]
                if leaf:
                    out.setdefault(leaf, eid)
    return out
