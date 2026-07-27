"""Build input-rooted relation graph from observations + obligations."""
from __future__ import annotations

import hashlib
from typing import Any

from uo.scripts.relation_evidence import validate_relation_evidence
from uo.scripts.semantic_relations import (
    empty_relation_graph,
    index_entities,
    is_input_root_entity,
    make_entity,
    make_relation,
)


def _rid(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return "rel_" + hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _eid(kind: str, symbol: str) -> str:
    sym = str(symbol or "").strip() or "anon"
    return f"{kind}:{sym}"


def _ensure_entity(
    graph: dict[str, Any],
    *,
    kind: str,
    symbol: str,
    extra: dict[str, Any] | None = None,
) -> str:
    eid = _eid(kind, symbol)
    ents = graph.setdefault("entities", [])
    if any(isinstance(e, dict) and e.get("id") == eid for e in ents):
        return eid
    ents.append(make_entity(entity_id=eid, kind=kind, symbol=symbol, extra=extra))
    return eid


def _add_relation(graph: dict[str, Any], rel: dict[str, Any]) -> None:
    rels = graph.setdefault("relations", [])
    rid = str(rel.get("id") or "")
    if rid and any(isinstance(r, dict) and r.get("id") == rid for r in rels):
        return
    rels.append(rel)


def build_input_roots_from_operator_boundary(
    boundary: dict[str, Any] | None,
    *,
    host_inputs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """仅从真实算子边界构建 input_roots；不得补通用 layout/dtype/B/N/S/D。"""
    roots: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(rid: str, kind: str, symbol: str, extra: dict[str, Any] | None = None) -> None:
        if rid in seen:
            return
        seen.add(rid)
        row = {"id": rid, "kind": kind, "symbol": symbol}
        if extra:
            row.update(extra)
        roots.append(row)

    boundary = boundary if isinstance(boundary, dict) else {}
    for inp in list(boundary.get("inputs") or []) + list(host_inputs or []):
        if not isinstance(inp, dict):
            continue
        name = str(inp.get("name") or inp.get("id") or "").strip()
        if not name:
            continue
        optional = bool(inp.get("optional") or inp.get("is_optional"))
        kind = "optional_input" if optional else "tensor_input"
        prefix = "optional" if optional else "input"
        _add(f"{prefix}:{name}", kind, name)
        dims = inp.get("shape_dims") or inp.get("dims") or inp.get("shape") or []
        if isinstance(dims, list):
            for d in dims:
                dname = str(d.get("name") if isinstance(d, dict) else d).strip()
                if dname:
                    _add(f"input:{name}.shape.{dname}", "shape_dim", dname, {"parent": name})
        dtype = str(inp.get("dtype") or "").strip()
        if dtype:
            _add(f"input:{name}.dtype", "dtype", dtype, {"parent": name})
        layout = str(inp.get("layout") or inp.get("format") or "").strip()
        if layout:
            _add(f"input:{name}.layout", "layout", layout, {"parent": name})

    for attr in boundary.get("attrs") or boundary.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        aname = str(attr.get("name") or attr.get("id") or "").strip()
        if aname:
            _add(f"attr:{aname}", "attribute", aname)

    return roots


def _apply_input_roots(graph: dict[str, Any], roots: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for r in roots:
        if not isinstance(r, dict):
            continue
        symbol = str(r.get("symbol") or r.get("id") or "").strip()
        kind = str(r.get("kind") or "other_input")
        eid = str(r.get("id") or "") or _eid("input_root", symbol)
        ents = graph.setdefault("entities", [])
        if not any(isinstance(e, dict) and e.get("id") == eid for e in ents):
            ents.append(
                make_entity(
                    entity_id=eid,
                    kind="input_root",
                    symbol=symbol,
                    extra={"input_kind": kind, **{k: v for k, v in r.items() if k not in {"id", "kind", "symbol"}}},
                )
            )
        ids.append(eid)
    graph["input_roots"] = ids
    return ids


def _obs_evidence_text(obs_items: list[dict[str, Any]]) -> str:
    """只使用真实 source window / snippet，禁止合成代码字符串。"""
    bits: list[str] = []
    for o in obs_items:
        snip = str(o.get("evidence_snippet") or o.get("text") or "").strip()
        if snip:
            bits.append(snip)
            continue
        sw = o.get("source_window") if isinstance(o.get("source_window"), dict) else {}
        text = str(sw.get("text") or "").strip()
        if text:
            bits.append(text)
    return "\n".join(bits)


def _unresolved(
    graph: dict[str, Any],
    *,
    obligation_id: Any,
    relation: str,
    reason_code: str,
    affected_entity_ids: list[str] | None = None,
    affected_relation_ids: list[str] | None = None,
) -> None:
    graph.setdefault("unresolved", []).append(
        {
            "obligation_id": obligation_id,
            "relation": relation,
            "reason_code": reason_code,
            "status": "unresolved",
            "affected_entity_ids": list(affected_entity_ids or []),
            "affected_relation_ids": list(affected_relation_ids or []),
        }
    )


def _ground(
    graph: dict[str, Any],
    subject: str,
    input_root_id: str,
    *,
    evidence_refs: list[str] | None = None,
) -> bool:
    """仅当 input_root_id 已在 graph.input_roots / entities 中存在时建立 GROUNDED_IN。"""
    roots = set(graph.get("input_roots") or [])
    by = index_entities(graph)
    if input_root_id not in roots and input_root_id not in by:
        # 允许 input:xxx / attr:xxx 形式已注册实体
        if not (input_root_id.startswith("input:") or input_root_id.startswith("attr:") or input_root_id.startswith("optional:")):
            return False
        if input_root_id not in by:
            return False
    if input_root_id not in by:
        return False
    _add_relation(
        graph,
        make_relation(
            relation_id=_rid("ground", subject, input_root_id),
            relation_type="GROUNDED_IN",
            subject=subject,
            object=input_root_id,
            evidence_refs=evidence_refs or [],
            origin="deterministic",
        ),
    )
    return True


def _find_root_id(graph: dict[str, Any], symbol: str) -> str:
    """在已注册 roots 中按 symbol / 后缀匹配；找不到返回空。"""
    sym = str(symbol or "").strip()
    if not sym:
        return ""
    by = index_entities(graph)
    for rid in graph.get("input_roots") or []:
        ent = by.get(str(rid))
        if not ent:
            continue
        if str(ent.get("symbol") or "") == sym or str(ent.get("id") or "").endswith(":" + sym):
            return str(ent.get("id"))
        if str(ent.get("id") or "") == sym:
            return str(ent.get("id"))
    # 直接 id
    if sym in by and is_input_root_entity(by[sym]):
        return sym
    return ""


def close_deterministic_relations(
    observations: dict[str, Any],
    obligations: dict[str, Any],
    *,
    operator_boundary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从确定性义务闭合生成 Relation Graph（仅完整结构证据）。"""
    graph = empty_relation_graph()
    roots = build_input_roots_from_operator_boundary(operator_boundary)
    _apply_input_roots(graph, roots)
    obs_by_id = {
        str(o.get("id") or ""): o
        for o in (observations.get("observations") or [])
        if isinstance(o, dict) and o.get("id")
    }

    for obl in obligations.get("deterministic") or []:
        if not isinstance(obl, dict):
            continue
        close_as = [str(x).upper() for x in (obl.get("close_as") or [])]
        entity_name = str((obl.get("entities") or ["anon"])[0])
        erefs = list(obl.get("evidence_refs") or [])
        obs_ids = [str(x) for x in (obl.get("observations") or []) if x]
        obs_items = [obs_by_id[i] for i in obs_ids if i in obs_by_id]

        for rtype in close_as:
            text = _obs_evidence_text(obs_items)
            # 宏仅见 invocation、无真实窗口 → 不得 deterministic close
            if any(
                str(o.get("type") or "") == "common_assign_macro"
                and not _obs_evidence_text([o])
                for o in obs_items
            ):
                _unresolved(
                    graph,
                    obligation_id=obl.get("obligation_id"),
                    relation=rtype,
                    reason_code="MACRO_BODY_UNRESOLVED",
                    affected_entity_ids=[entity_name],
                )
                continue
            check = validate_relation_evidence(rtype, text=text, authentic=bool(text.strip()))
            sufficient = bool(check.get("sufficient", check.get("supported")))
            authentic = bool(check.get("authentic"))
            if not (authentic and sufficient):
                _unresolved(
                    graph,
                    obligation_id=obl.get("obligation_id"),
                    relation=rtype,
                    reason_code=str(check.get("reason_code") or "unsupported"),
                    affected_entity_ids=[entity_name],
                )
                continue

            if rtype == "BINDS":
                for o in obs_items:
                    if o.get("type") not in {
                        "address_of_nested_member",
                        "common_assign_macro",
                    }:
                        continue
                    recv = str(o.get("receiver") or entity_name)
                    nested = str(o.get("nested_field") or "nested")
                    roots = list(o.get("root_tiling_types") or [])
                    root = str(roots[0] if roots else "TilingData")
                    sub = _ensure_entity(graph, kind="receiver", symbol=recv)
                    obj = _ensure_entity(
                        graph,
                        kind="tiling_field",
                        symbol=f"{root}.{nested}",
                        extra={"root_type": root, "nested_field": nested},
                    )
                    _add_relation(
                        graph,
                        make_relation(
                            relation_id=_rid("binds", recv, nested),
                            relation_type="BINDS",
                            subject=sub,
                            object=obj,
                            evidence_refs=erefs or list(o.get("evidence_refs") or []),
                        ),
                    )
                # get_tiling_data alone → READS root, not WRITES
                for o in obs_items:
                    if o.get("type") != "get_tiling_data":
                        continue
                    fn = str(o.get("function") or entity_name)
                    root = str(o.get("root_type") or "TilingData")
                    sub = _ensure_entity(graph, kind="function", symbol=fn)
                    obj = _ensure_entity(graph, kind="template", symbol=root)
                    _add_relation(
                        graph,
                        make_relation(
                            relation_id=_rid("reads", fn, root),
                            relation_type="READS",
                            subject=sub,
                            object=obj,
                            evidence_refs=erefs,
                        ),
                    )
                    _add_relation(
                        graph,
                        make_relation(
                            relation_id=_rid("sel", fn, root),
                            relation_type="SELECTS_TEMPLATE",
                            subject=sub,
                            object=obj,
                            evidence_refs=erefs,
                        ),
                    )

            elif rtype == "WRITES":
                fn = entity_name
                sub = _ensure_entity(graph, kind="function", symbol=fn)
                for o in obs_items:
                    if o.get("type") != "setter_call":
                        continue
                    recv = str(o.get("receiver") or "")
                    field = str(o.get("field") or "")
                    _ensure_entity(graph, kind="receiver", symbol=recv)
                    obj = _ensure_entity(
                        graph,
                        kind="tiling_field",
                        symbol=f"{recv}.{field}",
                        extra={"receiver": recv, "field": field},
                    )
                    _add_relation(
                        graph,
                        make_relation(
                            relation_id=_rid("writes", fn, recv, field),
                            relation_type="WRITES",
                            subject=sub,
                            object=obj,
                            evidence_refs=erefs,
                        ),
                    )

            elif rtype == "COMPOSES_KEY":
                fn = entity_name
                sub = _ensure_entity(graph, kind="function", symbol=fn)
                obj = _ensure_entity(graph, kind="key", symbol="final_tiling_key")
                _add_relation(
                    graph,
                    make_relation(
                        relation_id=_rid("ckey", fn),
                        relation_type="COMPOSES_KEY",
                        subject=sub,
                        object=obj,
                        evidence_refs=erefs,
                    ),
                )
                # 仅从真实 key_construction observation 参数提取 dimension。
                dims: list[str] = []
                for o in obs_items:
                    if str(o.get("type") or "") not in {"key_macro_call", "key_construction"}:
                        continue
                    args = o.get("arguments") or o.get("argument_symbols") or o.get("dimensions") or []
                    if isinstance(args, list):
                        for a in args:
                            name = str(a.get("name") if isinstance(a, dict) else a).strip()
                            if name:
                                dims.append(name)
                if not dims:
                    _unresolved(
                        graph,
                        obligation_id=obl.get("obligation_id"),
                        relation="COMPOSES_KEY",
                        reason_code="KEY_DIMENSIONS_UNKNOWN",
                        affected_entity_ids=[sub, obj],
                    )
                for dim in dims:
                    dim_e = _ensure_entity(graph, kind="key_dimension", symbol=dim)
                    _add_relation(
                        graph,
                        make_relation(
                            relation_id=_rid("ckdim", fn, dim),
                            relation_type="CONTRIBUTES_TO_KEY",
                            subject=dim_e,
                            object=obj,
                            evidence_refs=erefs,
                        ),
                    )
                    root_id = _find_root_id(graph, dim)
                    if root_id:
                        _ground(graph, dim_e, root_id, evidence_refs=erefs)
                    else:
                        _unresolved(
                            graph,
                            obligation_id=obl.get("obligation_id"),
                            relation="CONTRIBUTES_TO_KEY",
                            reason_code="KEY_DIM_ROOT_UNKNOWN",
                            affected_entity_ids=[dim_e],
                        )

            elif rtype == "CONTRIBUTES_TO_KEY":
                fn = entity_name
                sub = _ensure_entity(graph, kind="function", symbol=fn)
                obj = _ensure_entity(graph, kind="key", symbol="final_tiling_key")
                _add_relation(
                    graph,
                    make_relation(
                        relation_id=_rid("contrib", fn),
                        relation_type="CONTRIBUTES_TO_KEY",
                        subject=sub,
                        object=obj,
                        evidence_refs=erefs,
                    ),
                )

            elif rtype == "EQUIVALENT_TO":
                for o in obs_items:
                    local = str(o.get("local") or entity_name)
                    leaf = str(o.get("tdf_leaf") or o.get("tdf_path") or "")
                    if not local or not leaf:
                        continue
                    sub = _ensure_entity(graph, kind="local", symbol=local)
                    obj = _ensure_entity(graph, kind="tiling_field", symbol=leaf)
                    _add_relation(
                        graph,
                        make_relation(
                            relation_id=_rid("eq", local, leaf),
                            relation_type="EQUIVALENT_TO",
                            subject=sub,
                            object=obj,
                            evidence_refs=erefs,
                        ),
                    )

            elif rtype == "DERIVES":
                local = entity_name
                inputs: list[str] = []
                expression: dict[str, Any] | None = None
                for o in obs_items:
                    if o.get("local") or o.get("output"):
                        local = str(o.get("local") or o.get("output"))
                    for s in o.get("input_symbols") or o.get("inputs") or []:
                        name = str(s.get("name") if isinstance(s, dict) else s).strip()
                        if name:
                            inputs.append(name)
                    if isinstance(o.get("expression"), dict):
                        expression = dict(o.get("expression") or {})
                    elif o.get("expression"):
                        expression = {"raw": str(o.get("expression"))}
                sub = _ensure_entity(graph, kind="local", symbol=local)
                if not inputs:
                    _unresolved(
                        graph,
                        obligation_id=obl.get("obligation_id"),
                        relation="DERIVES",
                        reason_code="DERIVE_INPUTS_INCOMPLETE",
                        affected_entity_ids=[sub],
                    )
                    continue
                resolved_inputs: list[str] = []
                for inp in inputs:
                    rid = _find_root_id(graph, inp)
                    if rid:
                        resolved_inputs.append(rid)
                        _ground(graph, sub, rid, evidence_refs=erefs)
                    else:
                        # 允许 tiling_field / local 作为中间输入
                        mid = _ensure_entity(
                            graph,
                            kind="tiling_field" if "." in inp or inp.startswith("tiling") else "local",
                            symbol=inp,
                        )
                        resolved_inputs.append(mid)
                _add_relation(
                    graph,
                    make_relation(
                        relation_id=_rid("der", local),
                        relation_type="DERIVES",
                        subject=sub,
                        object=resolved_inputs[0] if len(resolved_inputs) == 1 else "",
                        evidence_refs=erefs,
                        inputs=resolved_inputs,
                        extra={"expression": expression} if expression else None,
                    ),
                )

            elif rtype == "GUARDS":
                cond_sym = entity_name
                sub = _ensure_entity(graph, kind="condition", symbol=cond_sym)
                grounded_any = False
                for o in obs_items:
                    symbols = list(o.get("condition_symbols") or [])
                    t = str(o.get("type") or "")
                    if t == "layout_condition":
                        symbols.append("layout")
                    elif t == "dtype_condition":
                        symbols.append("dtype")
                    elif t == "deterministic_or_sparse_condition":
                        symbols.extend(["deterministic", "sparse_mode"])
                    elif t == "shape_dim_ref":
                        symbols.append(str(o.get("dim") or ""))
                    for sym in symbols:
                        rid = _find_root_id(graph, str(sym))
                        if rid and _ground(graph, sub, rid, evidence_refs=erefs):
                            grounded_any = True
                if not grounded_any:
                    _unresolved(
                        graph,
                        obligation_id=obl.get("obligation_id"),
                        relation="GUARDS",
                        reason_code="GUARD_ROOT_UNKNOWN",
                        affected_entity_ids=[sub],
                    )
                branch_target = ""
                for o in obs_items:
                    if o.get("branch_target"):
                        branch_target = str(o.get("branch_target"))
                        break
                if not branch_target:
                    branch_target = f"branch:{cond_sym}"
                br = _ensure_entity(graph, kind="branch", symbol=branch_target)
                _add_relation(
                    graph,
                    make_relation(
                        relation_id=_rid("br", cond_sym),
                        relation_type="GUARDS",
                        subject=sub,
                        object=br,
                        evidence_refs=erefs,
                    ),
                )

            elif rtype == "SELECTS_TEMPLATE":
                fn = entity_name
                sub = _ensure_entity(graph, kind="function", symbol=fn)
                for o in obs_items:
                    if o.get("type") == "get_tiling_data":
                        root = str(o.get("root_type") or "TilingData")
                        obj = _ensure_entity(graph, kind="template", symbol=root)
                        _add_relation(
                            graph,
                            make_relation(
                                relation_id=_rid("tmpl", fn, root),
                                relation_type="SELECTS_TEMPLATE",
                                subject=sub,
                                object=obj,
                                evidence_refs=erefs,
                            ),
                        )
                    elif o.get("type") == "template_alias":
                        alias = str(o.get("alias") or "")
                        obj = _ensure_entity(graph, kind="template", symbol=alias)
                        _add_relation(
                            graph,
                            make_relation(
                                relation_id=_rid("tmpl_a", fn, alias),
                                relation_type="SELECTS_TEMPLATE",
                                subject=sub,
                                object=obj,
                                evidence_refs=erefs,
                            ),
                        )

    return graph


def merge_llm_relation_parts(
    graph: dict[str, Any],
    parts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge LLM relation part documents into graph (fail-closed on conflicts)."""
    out = dict(graph)
    out["entities"] = list(graph.get("entities") or [])
    out["relations"] = list(graph.get("relations") or [])
    out["unresolved"] = list(graph.get("unresolved") or [])
    seen_rel = {
        (str(r.get("type")), str(r.get("subject")), str(r.get("object")))
        for r in out["relations"]
        if isinstance(r, dict)
    }
    for part in parts:
        if not isinstance(part, dict):
            continue
        status = str(part.get("status") or "").lower()
        if status == "unresolved":
            out["unresolved"].append(
                {
                    "obligation_id": part.get("obligation_id"),
                    "reason_code": part.get("reason_code") or "unresolved",
                    "status": "unresolved",
                }
            )
            continue
        for rel in part.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            key = (
                str(rel.get("type") or "").upper(),
                str(rel.get("subject") or ""),
                str(rel.get("object") or ""),
            )
            # Conflict: opposite decision already present with different type same subject intent
            if key in seen_rel:
                continue
            # Check rejected vs confirmed conflicts within same obligation
            try:
                r = make_relation(
                    relation_id=str(rel.get("id") or _rid("llm", *key)),
                    relation_type=str(rel.get("type") or ""),
                    subject=str(rel.get("subject") or ""),
                    object=str(rel.get("object") or ""),
                    evidence_refs=rel.get("evidence_refs") or [],
                    origin="llm",
                    confidence=str(rel.get("confidence") or "medium"),
                )
            except ValueError:
                out["unresolved"].append(
                    {
                        "obligation_id": part.get("obligation_id"),
                        "reason_code": "invalid_relation_type",
                        "status": "unresolved",
                    }
                )
                continue
            out["relations"].append(r)
            seen_rel.add(key)
            # Ensure entities exist
            if r["subject"]:
                kind = "unknown"
                if r["subject"].startswith("input_root:"):
                    kind = "input_root"
                elif r["type"] == "BINDS":
                    kind = "receiver"
                _ensure_entity(out, kind=kind, symbol=r["subject"].split(":", 1)[-1])
            if r["object"]:
                _ensure_entity(out, kind="unknown", symbol=r["object"].split(":", 1)[-1])
        for rej in part.get("rejected_relations") or []:
            if not isinstance(rej, dict):
                continue
            # If a confirmed relation contradicts rejection, mark conflict.
            rtype = str(rej.get("type") or "").upper()
            sub = str(rej.get("subject") or "")
            for existing in list(out["relations"]):
                if (
                    isinstance(existing, dict)
                    and str(existing.get("type") or "").upper() == rtype
                    and str(existing.get("subject") or "") == sub
                    and existing.get("origin") != "llm"
                ):
                    out["unresolved"].append(
                        {
                            "obligation_id": part.get("obligation_id"),
                            "reason_code": "relation_decision_conflict",
                            "status": "conflict",
                            "relation": rtype,
                            "subject": sub,
                        }
                    )
    return out


def validate_input_root_grounding(graph: dict[str, Any]) -> list[str]:
    """Every condition/branch/template/key_dimension/tiling_field must reach an input_root."""
    errors: list[str] = []
    by = index_entities(graph)
    roots = {
        eid
        for eid, e in by.items()
        if is_input_root_entity(e)
    }
    # Also accept graph["input_roots"]
    for rid in graph.get("input_roots") or []:
        roots.add(str(rid))

    # Build adjacency for GROUNDED_IN / DERIVES / READS / EQUIVALENT_TO backward to roots.
    parents: dict[str, set[str]] = {}
    for r in graph.get("relations") or []:
        if not isinstance(r, dict):
            continue
        t = str(r.get("type") or "").upper()
        if t not in {"GROUNDED_IN", "DERIVES", "READS", "EQUIVALENT_TO", "BINDS", "CONTRIBUTES_TO_KEY"}:
            continue
        sub = str(r.get("subject") or "")
        obj = str(r.get("object") or "")
        if not sub:
            continue
        parents.setdefault(sub, set())
        if obj:
            parents[sub].add(obj)
        for inp in r.get("inputs") or []:
            parents[sub].add(str(inp) if ":" in str(inp) else _eid("input_root", str(inp)))

    def reaches_root(node: str, seen: set[str] | None = None) -> bool:
        if node in roots:
            return True
        ent = by.get(node)
        if is_input_root_entity(ent):
            return True
        # symbol-only input_root:B form
        if node.startswith("input_root:"):
            return True
        s = seen or set()
        if node in s:
            return False
        s.add(node)
        for p in parents.get(node) or []:
            if reaches_root(p, s):
                return True
        return False

    must_ground_kinds = {
        "condition",
        "branch",
        "template",
        "key_dimension",
        "tiling_field",
        "key",
    }
    unresolved_subjects = {
        str(u.get("obligation_id") or "")
        for u in (graph.get("unresolved") or [])
        if isinstance(u, dict)
    }
    for eid, ent in by.items():
        kind = str(ent.get("kind") or "")
        if kind not in must_ground_kinds:
            continue
        if reaches_root(eid):
            continue
        # Allow explicit unresolved markers
        if any(eid in str(u) for u in unresolved_subjects):
            continue
        errors.append(
            f"GROUNDING: {eid} (kind={kind}) does not reach an input_root"
        )
    return errors


__all__ = [
    "build_input_roots_from_operator_boundary",
    "close_deterministic_relations",
    "merge_llm_relation_parts",
    "validate_input_root_grounding",
]
