from __future__ import annotations

from typing import Any

from .constraint_ir import normalize_expr, ConstraintIRError
from .hashing import stable_hash


CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


def extract_generation_conditions(
    snapshot: dict[str, Any],
    *,
    level: str = "L1",
    topic: str = "",
) -> dict[str, Any]:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    conditions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    contract = _as_dict(files.get("contracts/testcase.yaml"))
    constraints = _as_dict(files.get("tiling/constraints.yaml"))
    coverage = _as_dict(files.get("tiling/coverage_model.yaml"))
    branches = _as_dict(files.get("kernel/branches.yaml"))
    key_cards = _collect_key_cards(files)

    for idx, spec in enumerate(_iter_items(contract.get("typed_constraints")), start=1):
        cid = str(spec.get("id") or f"GC_TYPED_{idx:03d}")
        try:
            expr = normalize_expr(spec.get("expr") if "expr" in spec else spec)
            conditions.append(
                _condition(
                    cid,
                    expr=expr,
                    confidence=CONFIDENCE_HIGH,
                    source_refs=["contracts/testcase.yaml"],
                    role=str(spec.get("role") or "legal"),
                    topic=topic,
                )
            )
        except ConstraintIRError as exc:
            gaps.append(_gap(cid, "UNSUPPORTED_EXPRESSION", str(exc), priority="high"))

    for idx, rel in enumerate(_iter_items(constraints.get("relations")), start=1):
        cid = str(rel.get("id") or f"GC_REL_{idx:03d}")
        expr, confidence, gap = _relation_to_expr(rel)
        if gap:
            gaps.append(_gap(cid, gap["code"], gap["message"], priority="high"))
            continue
        if expr:
            conditions.append(
                _condition(
                    cid,
                    expr=expr,
                    confidence=confidence,
                    source_refs=["tiling/constraints.yaml"],
                    role="legal",
                    topic=topic,
                )
            )

    for field_name, item in sorted(_as_dict(coverage.get("key_field_obligations")).items()):
        if not isinstance(item, dict):
            continue
        var_id = f"VAR_KEY_{str(field_name).removeprefix('KEY_').upper()}"
        values = item.get("values") or item.get("enum_values") or []
        confidence = CONFIDENCE_HIGH if values else CONFIDENCE_LOW
        if not values:
            gaps.append(_gap(f"GC_FIELD_{field_name}", "DOMAIN_MISSING", f"key field {field_name} has no values", priority="normal"))
            continue
        conditions.append(
            _condition(
                f"GC_FIELD_DOMAIN_{field_name}",
                expr={"op": "in", "var": var_id, "values": list(values)},
                confidence=confidence,
                source_refs=["tiling/coverage_model.yaml"],
                role="coverage_target",
                topic=topic,
                free_vars=[var_id],
            )
        )

    for item in _iter_items(branches.get("branches")):
        branch_id = str(item.get("id") or item.get("branch_id") or "")
        if not branch_id:
            continue
        if item.get("compile_time_fixed") is True or item.get("runtime") is False:
            continue
        var_id = f"VAR_{branch_id}" if not branch_id.startswith("VAR_") else branch_id
        if str(item.get("reachability") or "").lower() in {"unreachable", "excluded"}:
            conditions.append(
                _condition(
                    f"GC_BRANCH_UNREACH_{branch_id}",
                    expr={"op": "eq", "var": var_id, "value": False},
                    confidence=CONFIDENCE_MEDIUM,
                    source_refs=["kernel/branches.yaml"],
                    role="legal",
                    topic=topic,
                    free_vars=[var_id],
                )
            )
            continue
        conditions.append(
            _condition(
                f"GC_BRANCH_{branch_id}",
                expr={"op": "in", "var": var_id, "values": [False, True]},
                confidence=CONFIDENCE_HIGH,
                source_refs=["kernel/branches.yaml"],
                role="coverage_target",
                topic=topic,
                free_vars=[var_id],
            )
        )

    for card_id, card in sorted(key_cards.items()):
        set_by = _as_dict(card.get("set_by"))
        host = _as_dict(card.get("host_reachable"))
        recipe = _as_dict(card.get("hit_recipe"))
        var_id = f"VAR_{card_id}" if card_id.startswith("KEY_") else f"VAR_KEY_{card_id}"
        domain = card.get("domain") or []
        if domain:
            conditions.append(
                _condition(
                    f"GC_KEYCARD_DOMAIN_{card_id}",
                    expr={"op": "in", "var": var_id, "values": list(domain)},
                    confidence=CONFIDENCE_HIGH,
                    source_refs=[f"tiling/key_cards/{card_id}.yaml"],
                    role="legal",
                    topic=topic,
                    free_vars=[var_id],
                )
            )
        for field_name, status_blob in (("set_by", set_by), ("host_reachable", host), ("hit_recipe", recipe)):
            status = str(status_blob.get("status") or "").lower()
            if status in {"missing", "unknown", ""}:
                topic_l = topic.lower()
                card_l = card_id.lower()
                topic_related = bool(topic) and (
                    topic_l in card_l
                    or any(tok and tok in card_l for tok in topic_l.replace("-", "_").split("_"))
                    or any(tok in card_l for tok in ("deter", "pse", "drop", "mask", "rope"))
                )
                gaps.append(
                    _gap(
                        f"GC_{card_id}_{field_name.upper()}",
                        "EXTRACT_GAP",
                        status_blob.get("note") or f"{card_id}.{field_name} status={status or 'missing'}",
                        priority="high" if topic_related else "normal",
                        source_refs=[f"tiling/key_cards/{card_id}.yaml"],
                        llm_fields=[field_name],
                        entity_ref=card_id,
                    )
                )

    for rid, rule in sorted(_as_dict(constraints.get("input_realization")).items()):
        if not isinstance(rule, dict):
            gaps.append(_gap(f"GC_IR_{rid}", "INPUT_REALIZATION_INVALID", "input_realization entry must be a mapping", priority="high"))
            continue
        pattern = _as_dict(rule.get("matches") or rule.get("key_pattern") or rule.get("pattern"))
        shape = rule.get("shape") or rule.get("shape_intent") or rule.get("minimal_shape")
        confidence = CONFIDENCE_HIGH if shape else CONFIDENCE_MEDIUM
        if not pattern and not shape:
            confidence = CONFIDENCE_LOW
            gaps.append(_gap(f"GC_IR_{rid}", "EXTRACT_GAP", f"input_realization {rid} missing pattern/shape", priority="normal"))
        conditions.append(
            _condition(
                f"GC_IR_{rid}",
                expr={"op": "and", "args": [{"op": "eq", "var": f"VAR_{k}", "value": v} for k, v in sorted(pattern.items())]} if pattern else {"op": "eq", "var": "VAR_REALIZATION_REF", "value": str(rid)},
                confidence=confidence,
                source_refs=["tiling/constraints.yaml"],
                role="realization_hint",
                topic=topic,
                meta={"realization_ref": rid, "shape": shape},
            )
        )

    conditions = _dedupe_conditions(conditions)
    gaps = sorted(gaps, key=lambda item: (item.get("priority", ""), item.get("id", "")))
    needs_llm = [item for item in gaps if item.get("code") == "EXTRACT_GAP" and item.get("priority") in {"hard", "high"}]
    return {
        "version": 1,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "level": level,
        "topic": topic or "",
        "conditions": conditions,
        "gaps": gaps,
        "needs_llm_completion": bool(needs_llm),
        "llm_gap_ids": [item["id"] for item in needs_llm],
        "extract_hash": stable_hash({"conditions": conditions, "gaps": gaps, "level": level, "topic": topic}),
    }


def merge_llm_patches(extract_doc: dict[str, Any], patches: list[dict[str, Any]], *, declared_variables: set[str] | None = None) -> dict[str, Any]:
    """Validate LLM LogicExpr patches and merge into extract conditions."""
    declared_variables = declared_variables or set()
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    conditions = list(extract_doc.get("conditions") or [])
    for patch in patches:
        if not isinstance(patch, dict):
            rejected.append({"reason": "patch must be a mapping", "patch": patch})
            continue
        try:
            expr = normalize_expr(patch.get("expr") if "expr" in patch else patch)
        except ConstraintIRError as exc:
            rejected.append({"id": patch.get("id"), "reason": str(exc), "patch": patch})
            continue
        free_vars = sorted(_collect_vars(expr))
        unknown = [var for var in free_vars if declared_variables and var not in declared_variables]
        if unknown:
            rejected.append({"id": patch.get("id"), "reason": f"unknown variables: {', '.join(unknown)}", "patch": patch})
            continue
        cid = str(patch.get("id") or f"GC_LLM_{len(accepted)+1:03d}")
        accepted.append(
            _condition(
                cid,
                expr=expr,
                confidence=CONFIDENCE_MEDIUM,
                source_refs=[str(ref) for ref in (patch.get("source_refs") or [])],
                role=str(patch.get("role") or "legal"),
                topic=str(patch.get("topic") or extract_doc.get("topic") or ""),
                free_vars=free_vars,
                extractor="llm",
            )
        )
    conditions.extend(accepted)
    gaps = [item for item in (extract_doc.get("gaps") or []) if item.get("id") not in {c.get("closes_gap") for c in patches if isinstance(c, dict)}]
    # Close gaps referenced by accepted patches
    closed = {str(p.get("closes_gap") or p.get("id") or "") for p in patches if isinstance(p, dict)}
    gaps = [item for item in gaps if item.get("id") not in closed]
    out = dict(extract_doc)
    out["conditions"] = _dedupe_conditions(conditions)
    out["gaps"] = gaps
    out["accepted_llm_patches"] = accepted
    out["rejected_llm_patches"] = rejected
    out["needs_llm_completion"] = any(item.get("code") == "EXTRACT_GAP" and item.get("priority") in {"hard", "high"} for item in gaps)
    out["extract_hash"] = stable_hash({"conditions": out["conditions"], "gaps": gaps})
    return out


def legal_exprs(extract_doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [item["expr"] for item in extract_doc.get("conditions") or [] if item.get("role") == "legal" and item.get("expr")]


def _relation_to_expr(rel: dict[str, Any]) -> tuple[dict[str, Any] | None, str, dict[str, str] | None]:
    rtype = str(rel.get("type") or rel.get("relation_type") or "").lower()
    if rtype == "mutex":
        fields = [str(item) for item in (rel.get("fields") or [])]
        if len(fields) < 2:
            return None, CONFIDENCE_LOW, {"code": "MUTEX_INCOMPLETE", "message": "mutex needs >=2 fields"}
        args = [{"op": "eq", "var": _var(field), "value": True} for field in fields]
        return {"op": "mutex", "args": args}, CONFIDENCE_HIGH, None
    if rtype in {"implies", "requires"}:
        source = rel.get("source") or rel.get("if")
        target = rel.get("target") or rel.get("then") or rel.get("requires")
        antecedent = _predicate_expr(source)
        consequent = _predicate_expr(target)
        if not antecedent or not consequent:
            return None, CONFIDENCE_LOW, {"code": "IMPLIES_INCOMPLETE", "message": f"{rtype} missing source/target"}
        return {"op": "implies", "antecedent": antecedent, "consequent": consequent}, CONFIDENCE_HIGH, None
    if rtype == "compatible_set":
        combos = rel.get("combinations") or rel.get("must_cover") or []
        if not combos:
            return None, CONFIDENCE_LOW, {"code": "COMPAT_EMPTY", "message": "compatible_set empty"}
        # Legal form: at least one combo must be allowed — encoded as soft coverage, not global AND
        return None, CONFIDENCE_MEDIUM, None
    if not rtype:
        return None, CONFIDENCE_LOW, None
    return None, CONFIDENCE_LOW, {"code": "UNSUPPORTED_RELATION", "message": f"unsupported relation type: {rtype}"}


def _predicate_expr(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        field = value.get("field") or value.get("var") or value.get("key")
        if field and any(key in value for key in ("equals", "value", "is")):
            return {"op": "eq", "var": _var(str(field)), "value": value.get("equals", value.get("value", value.get("is")))}
        if "op" in value:
            try:
                return normalize_expr(value)
            except ConstraintIRError:
                return None
    if isinstance(value, str) and value:
        return {"op": "eq", "var": _var(value), "value": True}
    return None


def _condition(
    cid: str,
    *,
    expr: dict[str, Any],
    confidence: str,
    source_refs: list[str],
    role: str,
    topic: str,
    free_vars: list[str] | None = None,
    extractor: str = "script",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "id": cid,
        "topic": topic or "",
        "source_refs": source_refs,
        "confidence": confidence,
        "extractor": extractor,
        "free_vars": free_vars or sorted(_collect_vars(expr)),
        "expr": expr,
        "role": role,
    }
    if meta:
        item["meta"] = meta
    return item


def _gap(cid: str, code: str, message: str, *, priority: str, source_refs: list[str] | None = None, llm_fields: list[str] | None = None, entity_ref: str = "") -> dict[str, Any]:
    return {
        "id": cid,
        "code": code,
        "message": message,
        "priority": priority,
        "source_refs": source_refs or [],
        "llm_fields": llm_fields or [],
        "entity_ref": entity_ref,
    }


def _collect_key_cards(files: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, value in files.items():
        if not isinstance(key, str) or not key.startswith("tiling/key_cards/"):
            continue
        if isinstance(value, dict):
            card_id = str(value.get("id") or key.rsplit("/", 1)[-1].removesuffix(".yaml"))
            out[card_id] = value
    # Also accept nested map under tiling/key_cards.yaml
    nested = files.get("tiling/key_cards.yaml")
    if isinstance(nested, dict):
        for card_id, card in nested.items():
            if isinstance(card, dict):
                out[str(card.get("id") or card_id)] = card
    return out


def _dedupe_conditions(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for item in conditions:
        key = stable_hash({"expr": item.get("expr"), "role": item.get("role")})
        seen[key] = item
    return sorted(seen.values(), key=lambda item: item["id"])


def _collect_vars(expr: Any) -> set[str]:
    found: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            var = node.get("var")
            if isinstance(var, str):
                found.add(var)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(expr)
    return found


def _var(name: str) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(name)).strip("_").upper()
    if text.startswith("VAR_"):
        return text
    return f"VAR_{text or 'UNKNOWN'}"


def _iter_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [{"id": str(key), **item} if isinstance(item, dict) else {"id": str(key), "value": item} for key, item in sorted(value.items())]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
