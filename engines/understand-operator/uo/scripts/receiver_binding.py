"""Shared receiver → TilingData binding extraction and canonical owner identity.

Used by propose_extract_plan, extract_host_subgraph, and reconcile_bridge.
Canonical Bridge identity prefers root_tiling_type + nested_path (+ leaf),
not member_type alone.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

# recv = &root->nested 形态（用于识别源码中自定义 binding 宏，不作 AscendC 合同登记）
RECV_ADDR_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*&\s*"
    r"\(?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?\s*->\s*([A-Za-z_][A-Za-z0-9_]*)\s*;"
)
# recv_ = tilingData->GetX() / GetMember()
RECV_GETTER_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*->\s*(Get[A-Za-z0-9_]*)\s*\(\s*\)\s*;"
)
GET_TILING_DATA_RE = re.compile(
    r"(?:GetTilingData|context_->GetTilingData)\s*<\s*([A-Za-z_][A-Za-z0-9_:]*)\s*>"
)
# Type *recv_ = nullptr;  /  Type* recv_;
MEMBER_PTR_DECL_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_:]*)\s*\*+\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|;)"
)
# 任意 function-like #define（算子仓自定义宏从源码发现，不进 ascendc_macro_contracts）
_FUNC_MACRO_DEFINE_RE = re.compile(
    r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)[ \t]*(.*?)$",
    re.MULTILINE,
)
_FUNC_MACRO_DEFINE_CONT_RE = re.compile(
    r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*\\\s*\n(?P<body>(?:.*\\\s*\n)*.*)$",
    re.MULTILINE,
)


def normalize_type_name(name: str) -> str:
    t = str(name or "").strip()
    if not t:
        return ""
    t = t.replace("::", ".")
    if "." in t:
        t = t.split(".")[-1]
    return t


def canonical_owner_key(
    *,
    root_type: str = "",
    nested_path: str = "",
    member_type: str = "",
) -> dict[str, str]:
    root = normalize_type_name(root_type)
    nested = str(nested_path or "").strip().strip(".")
    member = normalize_type_name(member_type)
    return {
        "root_type": root,
        "nested_path": nested,
        "member_type": member,
    }


def owner_identity_string(key: dict[str, Any] | None) -> str:
    """Stable normalized owner identity for Bridge obligation keys."""
    if not isinstance(key, dict):
        return ""
    root = normalize_type_name(str(key.get("root_type") or ""))
    nested = str(key.get("nested_path") or "").strip().strip(".")
    member = normalize_type_name(str(key.get("member_type") or ""))
    if root and nested:
        return f"{root}::{nested}".casefold()
    if member:
        return member.casefold()
    if root:
        return root.casefold()
    return ""


def field_identity_parts(
    *,
    owner_key: dict[str, Any] | None,
    field_leaf: str,
) -> tuple[str, str]:
    """Return (normalized_owner_identity, normalized_field_path)."""
    leaf = str(field_leaf or "").strip()
    key = owner_key if isinstance(owner_key, dict) else {}
    nested = str(key.get("nested_path") or "").strip().strip(".")
    owner = owner_identity_string(key)
    if nested and leaf and not leaf.startswith(nested + "."):
        field_path = f"{nested}.{leaf}"
    else:
        field_path = leaf
    return owner, field_path.casefold()


def extract_root_tiling_types(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in GET_TILING_DATA_RE.finditer(text or ""):
        typ = normalize_type_name(m.group(1))
        if typ and typ.casefold() not in seen:
            seen.add(typ.casefold())
            out.append(typ)
    return out


def extract_member_ptr_types(text: str) -> dict[str, str]:
    """Map receiver name → declared member pointer type."""
    out: dict[str, str] = {}
    for typ, recv in MEMBER_PTR_DECL_RE.findall(text or ""):
        ntyp = normalize_type_name(typ)
        if not ntyp or ntyp in {"auto", "const", "static", "constexpr", "return"}:
            continue
        if "tiling" not in ntyp.casefold() and "param" not in ntyp.casefold() and not ntyp.endswith("Params"):
            # Keep broad but skip obvious non-tiling primitives.
            if ntyp.casefold() in {"int", "uint32_t", "int64_t", "bool", "float", "double", "size_t", "void"}:
                continue
        out[str(recv)] = ntyp
    return out


def extract_receiver_bindings(
    text: str,
    *,
    file_path: str = "",
    extraction_unit: str = "",
    class_or_namespace: str = "",
    start_line: int = 0,
    member_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Public alias for extract_receiver_bindings_from_text (shared module API)."""
    return extract_receiver_bindings_from_text(
        text,
        file_path=file_path,
        extraction_unit=extraction_unit,
        class_or_namespace=class_or_namespace,
        start_line=start_line,
        member_types=member_types,
    )


def extract_get_tiling_data_bindings(text: str) -> list[dict[str, Any]]:
    """Map root variable declarations to GetTilingData<SchemaVariant>."""
    # Patterns:
    #   auto *normal = context->GetTilingData<NormalTiling>();
    #   NormalTiling *tnd = GetTilingData<TndTiling>();
    #   Foo *x = this->context_->GetTilingData<ns::Foo>();
    decl_re = re.compile(
        r"(?:auto\s*\*+\s*|((?:[A-Za-z_][A-Za-z0-9_]*::)*[A-Za-z_][A-Za-z0-9_]*)\s*\*+\s*)"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"(?:[A-Za-z_][A-Za-z0-9_]*\s*(?:->|\.)\s*)*"
        r"(?:GetTilingData)\s*<\s*((?:[A-Za-z_][A-Za-z0-9_]*::)*[A-Za-z_][A-Za-z0-9_]*)\s*>\s*\([^;]*\)\s*;"
    )
    out: list[dict[str, Any]] = []
    for m in decl_re.finditer(text or ""):
        var = m.group(2)
        schema = normalize_type_name(m.group(3))
        out.append(
            {
                "root_variable": var,
                "root_schema_variant": schema,
                "decl_type": normalize_type_name(m.group(1) or ""),
            }
        )
    bare = re.compile(
        r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
        r"(?:[A-Za-z_][A-Za-z0-9_]*\s*(?:->|\.)\s*)*"
        r"(?:GetTilingData)\s*<\s*((?:[A-Za-z_][A-Za-z0-9_]*::)*[A-Za-z_][A-Za-z0-9_]*)\s*>"
    )
    seen = {x["root_variable"] for x in out}
    for m in bare.finditer(text or ""):
        var = m.group(1)
        if var in seen:
            continue
        out.append(
            {
                "root_variable": var,
                "root_schema_variant": normalize_type_name(m.group(2)),
                "decl_type": "",
            }
        )
    return out


_BINDING_SHAPE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*&\s*"
    r"\(?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)?\s*->"
)


def _body_looks_like_receiver_binding(body: str, params: list[str]) -> bool:
    """判定宏体是否为 recv=&root->nested（允许 ## 拼接，禁止宽松 -> 误伤）。"""
    probe = body if body.rstrip().endswith(";") else body.rstrip() + ";"
    if RECV_ADDR_ASSIGN_RE.search(probe) or _BINDING_SHAPE_RE.search(probe):
        return True
    # PREFIX##Nested 等：用哑元替换形参后再判
    sub = probe
    for i, p in enumerate(params):
        sub = re.sub(rf"\b{re.escape(p)}\b", f"Arg{i}", sub)
    sub = re.sub(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*##\s*([A-Za-z_][A-Za-z0-9_]*)",
        r"\1\2",
        sub,
    )
    sub = sub.replace("##", "")
    return bool(RECV_ADDR_ASSIGN_RE.search(sub) or _BINDING_SHAPE_RE.search(sub))


def _discover_receiver_binding_macros(text: str) -> dict[str, dict[str, Any]]:
    """从源码 #define 发现「展开后为 recv=&root->nested」的自定义宏。

    不算 AscendC 合同登记：算子仓宏（如 FAG 的 TND_/BASE_TILING_DATA_COMMON_ASSIGN）
    只在源码出现时解析，禁止写入 ascendc_macro_contracts.yaml。
    """
    bodies: dict[str, dict[str, Any]] = {}
    for m in _FUNC_MACRO_DEFINE_CONT_RE.finditer(text or ""):
        name = m.group(1)
        params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        body = re.sub(r"\\\s*\n", " ", m.group("body")).strip()
        if _body_looks_like_receiver_binding(body, params):
            bodies[name] = {
                "params": params,
                "body": body,
                "definition_available": True,
                "discovered_from": "source_define",
            }
    for m in _FUNC_MACRO_DEFINE_RE.finditer(text or ""):
        name = m.group(1)
        if name in bodies:
            continue
        params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        body = (m.group(3) or "").strip()
        if not body or body.endswith("\\"):
            continue
        if _body_looks_like_receiver_binding(body, params):
            bodies[name] = {
                "params": params,
                "body": body,
                "definition_available": True,
                "discovered_from": "source_define",
            }
    return bodies


def list_discovered_binding_macro_names(text: str) -> list[str]:
    """返回当前文本中可从 #define 发现的 receiver-binding 宏名。"""
    return sorted(_discover_receiver_binding_macros(text).keys())


def build_macro_discovery_index(texts: list[str] | dict[str, str]) -> dict[str, dict[str, Any]]:
    """从多文件源码合并 binding 宏定义（include 闭包用）。"""
    merged: dict[str, dict[str, Any]] = {}
    items = texts.values() if isinstance(texts, dict) else texts
    for text in items:
        for name, info in _discover_receiver_binding_macros(text or "").items():
            merged.setdefault(name, info)
    return merged


def build_get_tiling_data_index(texts: list[str] | dict[str, str]) -> dict[str, str]:
    """root_variable → schema_variant（跨文件/闭包）。"""
    out: dict[str, str] = {}
    items = texts.values() if isinstance(texts, dict) else texts
    for text in items:
        for item in extract_get_tiling_data_bindings(text or ""):
            var = str(item.get("root_variable") or "")
            schema = str(item.get("root_schema_variant") or "")
            if var and schema:
                out.setdefault(var, schema)
    return out


def _resolve_common_assign_substitution(
    text: str,
    *,
    macro_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """解析源码发现的 binding 宏：需宏体 + 实参替换成功才产出 binding。"""
    bindings: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    bodies = dict(macro_index or {})
    bodies.update(_discover_receiver_binding_macros(text))

    # 仅对「正文里有 invocation」的宏解析；宏体可来自 index
    for macro_name, info in bodies.items():
        inv_re = re.compile(
            rf"(?m)^(?!\s*#\s*define).*?\b{re.escape(macro_name)}\s*\("
        )
        for m in inv_re.finditer(text or ""):
            open_idx = text.find("(", m.start())
            depth = 0
            i = open_idx
            while i < len(text):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            if depth != 0:
                continue
            arg_str = text[open_idx + 1 : i]
            args = [a.strip() for a in arg_str.split(",") if a.strip()]
            if len(args) < len(info["params"]):
                unresolved.append(
                    {
                        "reason_code": "MACRO_PARAM_SUBSTITUTION_UNRESOLVED",
                        "macro": macro_name,
                        "message": "实参数量不足，无法完成参数替换",
                    }
                )
                continue
            body = info["body"]
            for param, arg in zip(info["params"], args):
                body = re.sub(rf"\b{re.escape(param)}\b", arg, body)
            body = re.sub(
                r"([A-Za-z_][A-Za-z0-9_]*)\s*##\s*([A-Za-z_][A-Za-z0-9_]*)",
                r"\1\2",
                body,
            )
            body = body.replace("##", "")
            stmt = body if body.rstrip().endswith(";") else body.rstrip() + ";"
            am = RECV_ADDR_ASSIGN_RE.search(stmt)
            if not am:
                unresolved.append(
                    {
                        "reason_code": "MACRO_PARAM_SUBSTITUTION_UNRESOLVED",
                        "macro": macro_name,
                        "message": "参数替换后仍无法解析 receiver/root/nested",
                        "substituted_body": body[:200],
                    }
                )
                continue
            bindings.append(
                {
                    "receiver": am.group(1),
                    "root_variable": am.group(2),
                    "nested_path": am.group(3),
                    "parameter_substitution_resolved": True,
                    "definition_available": True,
                    "invocation_arguments_available": True,
                    "evidence": [f"macro_substituted:{macro_name}"],
                    "macro_name": macro_name,
                }
            )
    return bindings, unresolved


def extract_receiver_bindings_from_text(
    text: str,
    *,
    file_path: str = "",
    extraction_unit: str = "",
    class_or_namespace: str = "",
    start_line: int = 0,
    member_types: dict[str, str] | None = None,
    macro_index: dict[str, dict[str, Any]] | None = None,
    gtd_index: dict[str, str] | None = None,
    suppress_receiver_unresolved: bool = False,
) -> list[dict[str, Any]]:
    """Parse bindings；禁止 roots[0] 默认 root；禁止无宏体 placeholder。

    macro_index / gtd_index：来自 include 闭包的预扫结果，允许宏定义与
    GetTilingData 声明不在当前 text 内。
    """
    root_vars = {
        r["root_variable"]: r for r in extract_get_tiling_data_bindings(text)
    }
    for var, schema in (gtd_index or {}).items():
        if var not in root_vars:
            root_vars[var] = {
                "root_variable": var,
                "root_schema_variant": schema,
                "decl_type": "",
            }
    decls = dict(member_types or {})
    decls.update(extract_member_ptr_types(text))
    bindings: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []

    def _upsert(
        recv: str,
        nested: str,
        *,
        root_variable: str,
        evidence: str,
        guard_context: dict[str, Any] | None = None,
    ) -> None:
        recv_s = str(recv or "").strip()
        nested_s = str(nested or "").strip()
        root_var = str(root_variable or "").strip()
        if not recv_s or not nested_s or not root_var:
            return
        root_info = root_vars.get(root_var) or {}
        schema = str(root_info.get("root_schema_variant") or "")
        if not schema and not suppress_receiver_unresolved:
            unresolved.append(
                {
                    "reason_code": "RECEIVER_IDENTITY_AMBIGUOUS",
                    "receiver": recv_s,
                    "root_variable": root_var,
                    "file_path": str(file_path or "").replace("\\", "/"),
                    "message": "无法从 root variable 追溯到 GetTilingData<SchemaVariant>",
                }
            )
            schema = ""
        member = decls.get(recv_s, "")
        key = canonical_owner_key(
            root_type=schema,
            nested_path=nested_s,
            member_type=member,
        )
        item = {
            "receiver": recv_s,
            "root_variable": root_var,
            "root_schema_variant": schema,
            "nested_path": nested_s,
            "nested_field": nested_s,
            "member_type": member,
            "root_tiling_types": [schema] if schema else [],
            "canonical_owner_key": key,
            "type_aliases": [member] if member else [],
            "file_path": str(file_path or "").replace("\\", "/"),
            "extraction_unit": str(extraction_unit or class_or_namespace or ""),
            "class_or_namespace": str(class_or_namespace or ""),
            "start_line": int(start_line or 0),
            "evidence": [evidence],
            "guard_context": guard_context or {},
            "score": 0.95 if schema else 0.4,
            "role_suggested": "receiver_binding",
            "canonical": bool(schema),
        }
        prev = bindings.get(recv_s)
        if prev is None:
            bindings[recv_s] = item
            return
        # Multiple conditional bindings: keep list under alternatives
        alts = list(prev.get("alternatives") or [])
        # Prefer canonical as primary
        if item.get("canonical") and not prev.get("canonical"):
            alts.append(dict(prev))
            item["alternatives"] = alts
            bindings[recv_s] = item
            return
        alts.append(item)
        prev["alternatives"] = alts
        ev = list(prev.get("evidence") or [])
        if evidence not in ev:
            ev.append(evidence)
        prev["evidence"] = ev

    for recv, root_var, nested in RECV_ADDR_ASSIGN_RE.findall(text or ""):
        _upsert(recv, nested, root_variable=root_var, evidence="recv_addr_assign")
    for recv, root_var, getter in RECV_GETTER_ASSIGN_RE.findall(text or ""):
        nested = getter[3:] if getter.startswith("Get") and len(getter) > 3 else getter
        if nested:
            nested = nested[0].lower() + nested[1:] if nested[0].isupper() else nested
        _upsert(recv, nested, root_variable=root_var, evidence="recv_getter_assign")

    macro_bindings, macro_unresolved = _resolve_common_assign_substitution(
        text, macro_index=macro_index
    )
    unresolved.extend(macro_unresolved)
    for mb in macro_bindings:
        _upsert(
            mb["receiver"],
            mb["nested_path"],
            root_variable=mb["root_variable"],
            evidence=mb["evidence"][0],
        )
        if mb["receiver"] in bindings:
            bindings[mb["receiver"]]["parameter_substitution_resolved"] = True
            bindings[mb["receiver"]]["definition_available"] = True
            bindings[mb["receiver"]]["invocation_arguments_available"] = True

    result = list(bindings.values())
    if unresolved:
        # Attach unresolved on a synthetic entry for callers that only read list
        for u in unresolved:
            u["file_path"] = str(file_path or "").replace("\\", "/")
        # Store on first binding or return via module-level helper
        if result:
            result[0].setdefault("binding_unresolved", unresolved)
        else:
            result.append(
                {
                    "receiver": "",
                    "canonical": False,
                    "binding_unresolved": unresolved,
                    "score": 0.0,
                    "evidence": [],
                }
            )
    return result


def index_bindings_by_receiver(bindings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for b in bindings or []:
        if not isinstance(b, dict):
            continue
        recv = str(b.get("receiver") or b.get("name") or "").strip()
        if not recv:
            continue
        prev = out.get(recv)
        if prev is None or (b.get("canonical") and not prev.get("canonical")):
            out[recv] = b
    return out


def select_binding_for_guard(
    binding: dict[str, Any] | None,
    guard_condition: str = "true",
) -> dict[str, Any]:
    """按 guard 选择 alternatives 中的 binding；无匹配则返回 canonical 优先项。"""
    if not isinstance(binding, dict):
        return {}
    cond = str(guard_condition or "true").strip()
    cands = [binding] + list(binding.get("alternatives") or [])
    if cond and cond != "true":
        for c in cands:
            gc = c.get("guard_context") if isinstance(c.get("guard_context"), dict) else {}
            ct = str(gc.get("condition_text") or "")
            if ct and (ct in cond or cond in ct):
                return c
    for c in cands:
        if c.get("canonical"):
            return c
    return binding


def binding_candidate_id(binding: dict[str, Any]) -> str:
    raw = "|".join(
        [
            "receiver_binding",
            str(binding.get("extraction_unit") or ""),
            str(binding.get("file_path") or ""),
            str(binding.get("receiver") or ""),
            str(binding.get("nested_field") or ""),
            str(binding.get("start_line") or 0),
            str((binding.get("canonical_owner_key") or {}).get("root_type") or ""),
        ]
    )
    return "CAND_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


__all__ = [
    "GET_TILING_DATA_RE",
    "MEMBER_PTR_DECL_RE",
    "RECV_ADDR_ASSIGN_RE",
    "RECV_GETTER_ASSIGN_RE",
    "binding_candidate_id",
    "canonical_owner_key",
    "extract_get_tiling_data_bindings",
    "extract_member_ptr_types",
    "extract_receiver_bindings",
    "extract_receiver_bindings_from_text",
    "extract_root_tiling_types",
    "field_identity_parts",
    "index_bindings_by_receiver",
    "build_get_tiling_data_index",
    "build_macro_discovery_index",
    "list_discovered_binding_macro_names",
    "normalize_type_name",
    "owner_identity_string",
    "select_binding_for_guard",
]
