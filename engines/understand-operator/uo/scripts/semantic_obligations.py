"""从 observations + candidates 构建语义义务。

稳定 identity + 细粒度 conflict_group；仅完整结构证据可 deterministic close。
"""
from __future__ import annotations

import hashlib
from typing import Any


def _oid(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts if p)
    return "obl_" + hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _cond_hash(expr: str) -> str:
    return hashlib.sha1(str(expr or "").encode("utf-8", errors="ignore")).hexdigest()[:10]


_BINDING_MACRO_OBS = frozenset({"common_assign_macro", "receiver_binding_macro"})


def _stable_identity(o: dict[str, Any]) -> tuple[str, str, str]:
    """返回 (stable_id_key, pool, conflict_group)。"""
    t = str(o.get("type") or "")
    recv = str(o.get("receiver") or "").strip()
    nested = str(o.get("nested_path") or o.get("nested_field") or "").strip()
    fn = str(o.get("function") or "").strip()
    field = str(o.get("field") or "").strip()
    local = str(o.get("local") or o.get("output") or "").strip()
    tdf = str(o.get("tdf_path") or o.get("tdf_leaf") or "").strip()
    dim = str(o.get("dimension") or o.get("dim") or "").strip()
    ctor = str(o.get("constructor") or o.get("macro") or "").strip()

    if t in {"address_of_nested_member", "receiver_binding", *_BINDING_MACRO_OBS}:
        key = f"binding:{recv or 'anon'}:{nested or 'nested'}"
        return key, "binding_relations", key
    if t == "setter_call":
        key = f"write:{fn or 'anon'}:{recv or 'anon'}:{field or 'field'}"
        return key, "writer_relations", key
    if t in {"key_macro_call", "key_construction"}:
        key = f"key:{fn or ctor or 'anon'}"
        return key, "key_relations", key
    if t in {"layout_condition", "dtype_condition", "deterministic_or_sparse_condition"} and dim:
        key = f"key_dimension:{fn or 'anon'}:{dim}"
        return key, "key_relations", key
    if t in {"alias_candidate", "tdf_field_assign"}:
        key = f"alias:{local or 'anon'}:{tdf or 'path'}"
        return key, "alias_vs_derive", key
    if t == "derived_assign":
        key = f"derive:{fn or 'anon'}:{local or 'anon'}"
        return key, "alias_vs_derive", key
    if t in {
        "layout_condition",
        "dtype_condition",
        "deterministic_or_sparse_condition",
        "branch_if",
        "branch_condition",
    }:
        ch = _cond_hash(str(o.get("condition_expr") or o.get("text") or o.get("id") or ""))
        key = f"condition:{fn or 'anon'}:{ch}"
        return key, "architecture_relations", key
    if t in {"template_alias", "get_tiling_data"}:
        tmpl = str(o.get("alias") or o.get("root_type") or o.get("template_identity") or "tmpl")
        key = f"template:{fn or 'anon'}:{tmpl}"
        return key, "architecture_relations", key
    key = f"misc:{t}:{fn or recv or local or o.get('id') or 'anon'}"
    return key, "writer_relations", key


def _has_real_evidence(o: dict[str, Any]) -> bool:
    if str(o.get("evidence_snippet") or "").strip():
        return True
    sw = o.get("source_window") if isinstance(o.get("source_window"), dict) else {}
    return bool(str(sw.get("text") or "").strip())


def _macro_body_resolved(o: dict[str, Any]) -> bool:
    """宏仅见 invocation 且无解析体 → False。"""
    if str(o.get("type") or "") not in _BINDING_MACRO_OBS:
        return True
    if o.get("macro_body_resolved") is True:
        return True
    # 有嵌套字段赋值证据视作已解析
    if o.get("nested_field") and _has_real_evidence(o):
        return True
    return False


def build_semantic_obligations(
    observations: dict[str, Any],
    candidates: dict[str, Any] | None = None,
    *,
    closed_relation_ids: set[str] | None = None,
) -> dict[str, Any]:
    """按稳定 identity 分组；完整结构证据 → deterministic，否则 → llm_required。"""
    closed = closed_relation_ids or set()
    cand = candidates if isinstance(candidates, dict) else {}
    obs_list = [
        o for o in (observations.get("observations") or []) if isinstance(o, dict)
    ]

    # 用 candidates 辅助消歧：同名多模板实例
    writer_names: dict[str, int] = {}
    for c in cand.get("writer_candidates") or []:
        if isinstance(c, dict):
            n = str(c.get("name") or "").strip()
            if n:
                writer_names[n] = writer_names.get(n, 0) + 1

    groups: dict[str, list[dict[str, Any]]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for o in obs_list:
        key, pool, cg = _stable_identity(o)
        groups.setdefault(key, []).append(o)
        meta[key] = (pool, cg)

    deterministic: list[dict[str, Any]] = []
    llm_required: list[dict[str, Any]] = []

    def _pack(
        *,
        identity_key: str,
        pool: str,
        conflict_group: str,
        entities: list[str],
        candidate_ids: list[str],
        evidence_refs: list[str],
        observations: list[Any],
        candidate_relations: list[str],
        llm: bool,
        close_as: list[str] | None = None,
        question: str = "",
        allowed_entities: list[str] | None = None,
    ) -> dict[str, Any]:
        oid = _oid(identity_key)
        row: dict[str, Any] = {
            "obligation_id": oid,
            "identity_key": identity_key,
            "pool": pool,
            "conflict_group": conflict_group,
            "entities": entities,
            "allowed_entities": allowed_entities or entities,
            "candidate_ids": candidate_ids,
            "candidate_relations": candidate_relations,
            "observations": observations,
            "evidence_refs": evidence_refs,
            "llm_required": llm,
        }
        if close_as:
            row["close_as"] = close_as
        if question:
            row["question"] = question
        return row

    for key, items in groups.items():
        pool, cg = meta.get(key, ("writer_relations", key))
        types = {str(x.get("type") or "") for x in items}
        entities = sorted(
            {
                str(
                    x.get("function")
                    or x.get("receiver")
                    or x.get("local")
                    or x.get("output")
                    or key
                )
                for x in items
            }
        )
        # writer 义务优先 function 作为主实体
        if pool == "writer_relations" or any(str(x.get("type") or "") == "setter_call" for x in items):
            fns = [str(x.get("function") or "").strip() for x in items if x.get("function")]
            if fns:
                entities = sorted(set(fns))
        if pool == "binding_relations" or any(
            str(x.get("type") or "")
            in {"address_of_nested_member", "receiver_binding", *_BINDING_MACRO_OBS}
            for x in items
        ):
            recvs = [str(x.get("receiver") or "").strip() for x in items if x.get("receiver")]
            if recvs:
                entities = sorted(set(recvs))
        candidate_ids = sorted(
            {str(x.get("candidate_id") or "") for x in items if x.get("candidate_id")}
        )
        evidence_refs = sorted(
            {r for x in items for r in (x.get("evidence_refs") or []) if r}
        )
        obs_ids = [x.get("id") for x in items]

        # 同名多模板 / 多实例 → LLM
        for e in entities:
            if writer_names.get(e, 0) > 1:
                llm_required.append(
                    _pack(
                        identity_key=key,
                        pool=pool,
                        conflict_group=cg,
                        entities=entities,
                        candidate_ids=candidate_ids,
                        evidence_refs=evidence_refs,
                        observations=obs_ids,
                        candidate_relations=["WRITES", "BINDS", "COMPOSES_KEY", "READS"],
                        llm=True,
                        question="同名函数存在多个模板实例，需确认 Relation",
                    )
                )
                break
        else:
            pass
        if any(writer_names.get(e, 0) > 1 for e in entities):
            continue

        # 宏未解析体 → LLM
        if any(
            str(x.get("type") or "") in _BINDING_MACRO_OBS and not _macro_body_resolved(x)
            for x in items
        ):
            llm_required.append(
                _pack(
                    identity_key=key,
                    pool=pool,
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=["BINDS", "READS"],
                    llm=True,
                    question="宏仅见 invocation，未解析宏体",
                )
            )
            continue

        # 低置信 observation 不得单独 deterministic close
        if all(str(x.get("confidence") or "high").lower() == "low" for x in items):
            llm_required.append(
                _pack(
                    identity_key=key,
                    pool=pool,
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=["BINDS", "WRITES", "DERIVES", "EQUIVALENT_TO"],
                    llm=True,
                    question="仅有低置信观察，需确认 Relation",
                )
            )
            continue

        has_bind = bool(
            types
            & {
                "common_assign_macro",
                "receiver_binding_macro",
                "address_of_nested_member",
                "receiver_binding",
                "get_tiling_data",
            }
        )
        has_cond = bool(
            types
            & {
                "layout_condition",
                "dtype_condition",
                "deterministic_or_sparse_condition",
                "branch_if",
                "branch_condition",
                "template_alias",
            }
        )

        # 精确 receiver 绑定
        if has_bind and "setter_call" not in types and "key_macro_call" not in types and "key_construction" not in types:
            # receiver identity 不确定
            if any(
                not str(x.get("receiver") or "").strip()
                for x in items
                if str(x.get("type") or "") in {"address_of_nested_member", "receiver_binding"}
            ):
                llm_required.append(
                    _pack(
                        identity_key=key,
                        pool="binding_relations",
                        conflict_group=cg,
                        entities=entities,
                        candidate_ids=candidate_ids,
                        evidence_refs=evidence_refs,
                        observations=obs_ids,
                        candidate_relations=["BINDS", "READS"],
                        llm=True,
                        question="receiver identity 不确定",
                    )
                )
                continue
            close = ["BINDS"]
            crels = ["BINDS", "READS"]
            if has_cond:
                if types & {
                    "layout_condition",
                    "dtype_condition",
                    "deterministic_or_sparse_condition",
                    "branch_if",
                    "branch_condition",
                }:
                    close.append("GUARDS")
                    crels.append("GUARDS")
                if "template_alias" in types or "get_tiling_data" in types:
                    close.append("SELECTS_TEMPLATE")
                    crels.append("SELECTS_TEMPLATE")
            obl = _pack(
                identity_key=key,
                pool="binding_relations",
                conflict_group=cg,
                entities=entities,
                candidate_ids=candidate_ids,
                evidence_refs=evidence_refs,
                observations=obs_ids,
                candidate_relations=crels,
                llm=False,
                close_as=close,
            )
            if obl["obligation_id"] not in closed:
                deterministic.append(obl)
            continue

        # 精确 setter → WRITES（有 field + 真实证据即可；value 不完整进 LLM）
        if "setter_call" in types and "address_of_nested_member" not in types:
            incomplete = any(
                str(x.get("type") or "") == "setter_call" and not x.get("field")
                for x in items
            )
            no_evidence = not any(_has_real_evidence(x) for x in items if str(x.get("type") or "") == "setter_call")
            if incomplete or no_evidence:
                llm_required.append(
                    _pack(
                        identity_key=key,
                        pool="writer_relations",
                        conflict_group=cg,
                        entities=entities,
                        candidate_ids=candidate_ids,
                        evidence_refs=evidence_refs,
                        observations=obs_ids,
                        candidate_relations=["WRITES"],
                        llm=True,
                        question="setter field/证据不完整",
                    )
                )
                continue
            deterministic.append(
                _pack(
                    identity_key=key,
                    pool="writer_relations",
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=["WRITES"],
                    llm=False,
                    close_as=["WRITES"],
                )
            )
            continue

        # Key
        if types & {"key_macro_call", "key_construction"}:
            # helper 与 final composer 不确定
            if any(str(x.get("confidence") or "").lower() == "low" for x in items) or any(
                x.get("is_helper") for x in items
            ):
                llm_required.append(
                    _pack(
                        identity_key=key,
                        pool="key_relations",
                        conflict_group=cg,
                        entities=entities,
                        candidate_ids=candidate_ids,
                        evidence_refs=evidence_refs,
                        observations=obs_ids,
                        candidate_relations=["COMPOSES_KEY", "CONTRIBUTES_TO_KEY"],
                        llm=True,
                        question="key helper 与 final key composer 不确定",
                    )
                )
                continue
            deterministic.append(
                _pack(
                    identity_key=key,
                    pool="key_relations",
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=["COMPOSES_KEY", "CONTRIBUTES_TO_KEY"],
                    llm=False,
                    close_as=["COMPOSES_KEY"],
                )
            )
            continue

        # alias vs derive 冲突
        if "alias_candidate" in types and "derived_assign" in types:
            llm_required.append(
                _pack(
                    identity_key=key,
                    pool="alias_vs_derive",
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=["EQUIVALENT_TO", "DERIVES"],
                    llm=True,
                    question="alias 与 derive 冲突",
                )
            )
            continue

        if "alias_candidate" in types or "tdf_field_assign" in types:
            deterministic.append(
                _pack(
                    identity_key=key,
                    pool="alias_vs_derive",
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=["EQUIVALENT_TO"],
                    llm=False,
                    close_as=["EQUIVALENT_TO"],
                )
            )
            continue

        if "derived_assign" in types:
            incomplete = any(
                str(x.get("type") or "") == "derived_assign"
                and not (x.get("input_symbols") or x.get("inputs"))
                for x in items
            )
            if incomplete:
                llm_required.append(
                    _pack(
                        identity_key=key,
                        pool="alias_vs_derive",
                        conflict_group=cg,
                        entities=entities,
                        candidate_ids=candidate_ids,
                        evidence_refs=evidence_refs,
                        observations=obs_ids,
                        candidate_relations=["DERIVES"],
                        llm=True,
                        question="DERIVE_INPUTS_INCOMPLETE",
                    )
                )
                continue
            deterministic.append(
                _pack(
                    identity_key=key,
                    pool="alias_vs_derive",
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=["DERIVES"],
                    llm=False,
                    close_as=["DERIVES"],
                )
            )
            continue

        if types & {
            "layout_condition",
            "dtype_condition",
            "deterministic_or_sparse_condition",
            "branch_if",
            "branch_condition",
            "template_alias",
            "get_tiling_data",
        }:
            # branch target 不确定
            if any(
                str(x.get("type") or "") in {"branch_if", "branch_condition"}
                and not x.get("branch_target")
                for x in items
            ):
                llm_required.append(
                    _pack(
                        identity_key=key,
                        pool="architecture_relations",
                        conflict_group=cg,
                        entities=entities,
                        candidate_ids=candidate_ids,
                        evidence_refs=evidence_refs,
                        observations=obs_ids,
                        candidate_relations=["GUARDS", "SELECTS_TEMPLATE"],
                        llm=True,
                        question="branch target 不确定",
                    )
                )
                continue
            close: list[str] = []
            crels: list[str] = []
            if types & {
                "layout_condition",
                "dtype_condition",
                "deterministic_or_sparse_condition",
                "branch_if",
                "branch_condition",
            }:
                close.append("GUARDS")
                crels.append("GUARDS")
            if "template_alias" in types or "get_tiling_data" in types:
                close.append("SELECTS_TEMPLATE")
                crels.append("SELECTS_TEMPLATE")
            if close:
                deterministic.append(
                    _pack(
                        identity_key=key,
                        pool="architecture_relations",
                        conflict_group=cg,
                        entities=entities,
                        candidate_ids=candidate_ids,
                        evidence_refs=evidence_refs,
                        observations=obs_ids,
                        candidate_relations=crels or ["GUARDS"],
                        llm=False,
                        close_as=close,
                    )
                )
                continue

        if len(types) > 1:
            llm_required.append(
                _pack(
                    identity_key=key,
                    pool=pool,
                    conflict_group=cg,
                    entities=entities,
                    candidate_ids=candidate_ids,
                    evidence_refs=evidence_refs,
                    observations=obs_ids,
                    candidate_relations=sorted(
                        {
                            "BINDS",
                            "WRITES",
                            "READS",
                            "COMPOSES_KEY",
                            "CONTRIBUTES_TO_KEY",
                            "GUARDS",
                            "SELECTS_TEMPLATE",
                            "DERIVES",
                            "EQUIVALENT_TO",
                        }
                    ),
                    llm=True,
                    question="混合观察，需确认 Relation",
                )
            )

    return {
        "version": 1,
        "deterministic_count": len(deterministic),
        "llm_required_count": len(llm_required),
        "deterministic": deterministic,
        "llm_required": llm_required,
        "obligations": deterministic + llm_required,
    }


__all__ = ["build_semantic_obligations"]
