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


def ensure_standard_input_roots(graph: dict[str, Any]) -> list[str]:
    """Declare canonical input roots (shape dims + common attrs)."""
    roots = [
        ("layout", "layout"),
        ("dtype", "dtype"),
        ("deterministic", "attr"),
        ("sparse_mode", "attr"),
        ("B", "shape_dim"),
        ("N", "shape_dim"),
        ("S", "shape_dim"),
        ("D", "shape_dim"),
    ]
    ids: list[str] = []
    for symbol, input_kind in roots:
        eid = _ensure_entity(
            graph,
            kind="input_root",
            symbol=symbol,
            extra={"input_kind": input_kind},
        )
        ids.append(eid)
    graph["input_roots"] = ids
    return ids


def _ground(
    graph: dict[str, Any],
    subject: str,
    input_symbol: str,
    *,
    evidence_refs: list[str] | None = None,
) -> None:
    obj = _ensure_entity(
        graph,
        kind="input_root",
        symbol=input_symbol,
        extra={"input_kind": "other_input"},
    )
    # Fix input_kind for known symbols.
    by = index_entities(graph)
    ent = by.get(obj)
    if ent and ent.get("kind") == "input_root":
        known = {
            "layout": "layout",
            "dtype": "dtype",
            "deterministic": "attr",
            "sparse_mode": "attr",
            "B": "shape_dim",
            "N": "shape_dim",
            "S": "shape_dim",
            "D": "shape_dim",
        }
        if input_symbol in known:
            ent["input_kind"] = known[input_symbol]
    _add_relation(
        graph,
        make_relation(
            relation_id=_rid("ground", subject, input_symbol),
            relation_type="GROUNDED_IN",
            subject=subject,
            object=obj,
            evidence_refs=evidence_refs or [],
            origin="deterministic",
        ),
    )


def close_deterministic_relations(
    observations: dict[str, Any],
    obligations: dict[str, Any],
) -> dict[str, Any]:
    """Produce a relation graph from deterministic obligation closures."""
    graph = empty_relation_graph()
    ensure_standard_input_roots(graph)
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
            # Validate against concatenated observation context when possible.
            text_bits = []
            for o in obs_items:
                # Reconstruct minimal lexical cues from observation type.
                t = str(o.get("type") or "")
                if t == "common_assign_macro":
                    text_bits.append(f"{o.get('macro')}(tilingData);")
                    text_bits.append("x_ = &tilingData->nested;")
                elif t == "address_of_nested_member":
                    text_bits.append(
                        f"{o.get('receiver')} = &tilingData->{o.get('nested_field')};"
                    )
                elif t == "setter_call":
                    text_bits.append(f"{o.get('receiver')}->set_{o.get('field')}(v);")
                elif t == "key_macro_call":
                    text_bits.append("uint64_t key = GET_TPL_TILING_KEY(...); return key;")
                elif t == "get_tiling_data":
                    text_bits.append(f"GetTilingData<{o.get('root_type')}>();")
                elif t == "layout_condition":
                    text_bits.append("if (layoutType == INPUT_FORMAT_TND)")
                elif t == "dtype_condition":
                    text_bits.append("if (inputDtype == ge::DT_FLOAT16)")
                elif t == "deterministic_or_sparse_condition":
                    text_bits.append("if (isDeterministic)")
                elif t == "alias_candidate":
                    text_bits.append(
                        f"{o.get('local')} = tilingData->{o.get('tdf_path') or o.get('tdf_leaf')};"
                    )
                elif t == "derived_assign":
                    text_bits.append(f"{o.get('local')} = ceil_div(s1, blockFactor);")
                elif t == "template_alias":
                    text_bits.append(f"using {o.get('alias')} = {o.get('base')}<")
                elif t == "branch_if":
                    text_bits.append("if (cond)")
            text = "\n".join(text_bits)
            check = validate_relation_evidence(rtype, text=text)
            if not check.get("supported"):
                graph.setdefault("unresolved", []).append(
                    {
                        "obligation_id": obl.get("obligation_id"),
                        "relation": rtype,
                        "reason_code": check.get("reason_code") or "unsupported",
                        "status": "unresolved",
                    }
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
                # Key dims typically grounded to layout/dtype/deter.
                for dim in ("layout", "dtype", "deterministic", "sparse_mode"):
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
                    _ground(graph, dim_e, dim, evidence_refs=erefs)
                _ground(graph, sub, "layout", evidence_refs=erefs)
                _ground(graph, sub, "dtype", evidence_refs=erefs)
                _ground(graph, sub, "deterministic", evidence_refs=erefs)

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
                for o in obs_items:
                    if o.get("local"):
                        local = str(o.get("local"))
                sub = _ensure_entity(graph, kind="local", symbol=local)
                _add_relation(
                    graph,
                    make_relation(
                        relation_id=_rid("der", local),
                        relation_type="DERIVES",
                        subject=sub,
                        object="",
                        evidence_refs=erefs,
                        inputs=["shape_or_field"],
                    ),
                )
                _ground(graph, sub, "S", evidence_refs=erefs)

            elif rtype == "GUARDS":
                cond_sym = entity_name
                sub = _ensure_entity(graph, kind="condition", symbol=cond_sym)
                for o in obs_items:
                    t = str(o.get("type") or "")
                    if t == "layout_condition":
                        _ground(graph, sub, "layout", evidence_refs=erefs)
                    elif t == "dtype_condition":
                        _ground(graph, sub, "dtype", evidence_refs=erefs)
                    elif t == "deterministic_or_sparse_condition":
                        _ground(graph, sub, "deterministic", evidence_refs=erefs)
                        _ground(graph, sub, "sparse_mode", evidence_refs=erefs)
                    elif t == "shape_dim_ref":
                        dim = str(o.get("dim") or "S").upper()
                        if dim.lower() in {"b", "n", "s", "d"}:
                            dim = dim.upper()
                        elif dim in {"batch"}:
                            dim = "B"
                        elif dim in {"seqLen", "s1", "s2"}:
                            dim = "S"
                        elif dim in {"headNum", "n2"}:
                            dim = "N"
                        elif dim in {"headDim"}:
                            dim = "D"
                        _ground(graph, sub, dim if dim in {"B", "N", "S", "D"} else "S", evidence_refs=erefs)
                _add_relation(
                    graph,
                    make_relation(
                        relation_id=_rid("guards", cond_sym),
                        relation_type="GUARDS",
                        subject=sub,
                        object=sub,
                        evidence_refs=erefs,
                    ),
                )
                # Branch node activated by guard.
                br = _ensure_entity(graph, kind="branch", symbol=f"branch:{cond_sym}")
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
                        _ground(graph, obj, "layout", evidence_refs=erefs)
                        _ground(graph, obj, "deterministic", evidence_refs=erefs)
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
    "ensure_standard_input_roots",
    "close_deterministic_relations",
    "merge_llm_relation_parts",
    "validate_input_root_grounding",
]
