"""Materialize extract_plan surfaces from an input-rooted relation graph.

Roles/sinks are derived from relations — never chosen by LLM.
"""
from __future__ import annotations

from typing import Any

from uo.scripts.semantic_relations import index_entities, index_relations_by_type


def materialize_from_relations(
    graph: dict[str, Any],
    candidates: dict[str, Any] | None = None,
    *,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expand relation graph into a validate-ready extract_plan (pre-slim)."""
    cand = candidates if isinstance(candidates, dict) else {}
    by_ent = index_entities(graph)
    by_type = index_relations_by_type(graph)

    plan: dict[str, Any] = {
        "version": 1,
        "writers": [],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
        "derived_roots": [],
        "extra_host_entries": [],
        "receiver_bindings": [],
        "accepted_candidates": [],
        "rejected_candidates": [],
        "deferred_candidates": [],
        # New surfaces (input-rooted)
        "input_roots": [],
        "condition_nodes": [],
        "branch_nodes": [],
        "template_nodes": [],
        "key_dimensions": [],
        "derived_values": [],
        "groundings": [],
        "semantic_relations_ref": True,
    }
    if identity:
        for k in ("actor_id", "run_id", "workflow_id", "candidates_sha256", "architecture"):
            if identity.get(k) is not None:
                plan[k] = identity[k]
    if cand.get("architecture") and "architecture" not in plan:
        plan["architecture"] = cand.get("architecture")

    # input_roots
    for eid in graph.get("input_roots") or []:
        ent = by_ent.get(str(eid)) or {}
        plan["input_roots"].append(
            {
                "id": eid,
                "symbol": ent.get("symbol") or str(eid).split(":")[-1],
                "input_kind": ent.get("input_kind") or "other_input",
            }
        )
    if not plan["input_roots"]:
        for eid, ent in by_ent.items():
            if ent.get("kind") == "input_root":
                plan["input_roots"].append(
                    {
                        "id": eid,
                        "symbol": ent.get("symbol"),
                        "input_kind": ent.get("input_kind") or "other_input",
                    }
                )

    # BINDINGS
    for rel in by_type.get("BINDS") or []:
        sub = str(rel.get("subject") or "")
        obj = str(rel.get("object") or "")
        recv_ent = by_ent.get(sub) or {}
        field_ent = by_ent.get(obj) or {}
        recv = str(recv_ent.get("symbol") or sub.split(":")[-1])
        nested = str(
            field_ent.get("nested_field")
            or (field_ent.get("symbol") or obj).split(".")[-1]
        )
        root = str(field_ent.get("root_type") or "")
        if not root and "." in str(field_ent.get("symbol") or ""):
            root = str(field_ent.get("symbol")).split(".", 1)[0]
        binding = {
            "receiver": recv,
            "nested_field": nested,
            "root_tiling_types": [root] if root else [],
            "canonical_owner_key": {
                "root_type": root,
                "nested_path": nested,
                "member_type": field_ent.get("member_type") or "",
            },
            "evidence_refs": rel.get("evidence_refs") or [],
            "origin": "relation:BINDS",
        }
        # Attach candidate_id if evidence ref looks like CAND:
        for er in binding["evidence_refs"]:
            if str(er).startswith("CAND:"):
                binding["candidate_id"] = str(er)[5:]
                break
        plan["receiver_bindings"].append(binding)

    # WRITES → tiling_writer + tiling_sink receivers
    writer_names: set[str] = set()
    sink_receivers: set[str] = set()
    for rel in by_type.get("WRITES") or []:
        sub = str(rel.get("subject") or "")
        obj = str(rel.get("object") or "")
        fn_ent = by_ent.get(sub) or {}
        field_ent = by_ent.get(obj) or {}
        fn = str(fn_ent.get("symbol") or sub.split(":")[-1])
        recv = str(field_ent.get("receiver") or (field_ent.get("symbol") or obj).split(".")[0])
        field = str(field_ent.get("field") or (field_ent.get("symbol") or obj).split(".")[-1])
        if fn not in writer_names:
            writer_names.add(fn)
            plan["writers"].append(
                {
                    "name": fn,
                    "role": "tiling_writer",
                    "candidate_kind": "function_writer",
                    "evidence_refs": rel.get("evidence_refs") or [],
                    "decision_reason": "materialized from WRITES relation",
                    "evidence_source": "source",
                    "source_verified": True,
                }
            )
        sink_receivers.add(recv)
        plan.setdefault("tiling_field_sinks", []).append(
            {
                "receiver": recv,
                "field": field,
                "path": f"{recv}.{field}",
                "writer": fn,
                "evidence_refs": rel.get("evidence_refs") or [],
            }
        )

    for recv in sorted(sink_receivers):
        plan["receivers"].append(
            {
                "name": recv,
                "is_tiling_sink": True,
                "decision_reason": "materialized from WRITES relation",
                "evidence_source": "source",
                "source_verified": True,
            }
        )

    # COMPOSES_KEY → key_writer
    composed_fns: set[str] = set()
    for rel in by_type.get("COMPOSES_KEY") or []:
        sub = str(rel.get("subject") or "")
        fn_ent = by_ent.get(sub) or {}
        fn = str(fn_ent.get("symbol") or sub.split(":")[-1])
        if fn in composed_fns:
            continue
        composed_fns.add(fn)
        plan["writers"].append(
            {
                "name": fn,
                "role": "key_writer",
                "candidate_kind": "function_writer",
                "evidence_refs": rel.get("evidence_refs") or [],
                "decision_reason": "materialized from COMPOSES_KEY",
                "evidence_source": "source",
                "source_verified": True,
            }
        )

    # CONTRIBUTES_TO_KEY without COMPOSES_KEY on same subject → key_dimension_source
    for rel in by_type.get("CONTRIBUTES_TO_KEY") or []:
        sub = str(rel.get("subject") or "")
        ent = by_ent.get(sub) or {}
        kind = str(ent.get("kind") or "")
        sym = str(ent.get("symbol") or sub.split(":")[-1])
        if kind == "key_dimension":
            plan["key_dimensions"].append(
                {
                    "id": sub,
                    "symbol": sym,
                    "evidence_refs": rel.get("evidence_refs") or [],
                }
            )
            continue
        if kind == "function" and sym not in composed_fns:
            plan["writers"].append(
                {
                    "name": sym,
                    "role": "key_dimension_source",
                    "candidate_kind": "key_dimension_source",
                    "evidence_refs": rel.get("evidence_refs") or [],
                    "decision_reason": "materialized from CONTRIBUTES_TO_KEY",
                    "evidence_source": "source",
                    "source_verified": True,
                }
            )

    # EQUIVALENT_TO → aliases; DERIVES → derived_values (not aliases)
    for rel in by_type.get("EQUIVALENT_TO") or []:
        sub = str(rel.get("subject") or "")
        obj = str(rel.get("object") or "")
        local = (by_ent.get(sub) or {}).get("symbol") or sub.split(":")[-1]
        leaf = (by_ent.get(obj) or {}).get("symbol") or obj.split(":")[-1]
        plan["aliases"].append(
            {
                "local": local,
                "tdf_leaf": leaf.split(".")[-1],
                "tdf_path": leaf,
                "origin": "relation:EQUIVALENT_TO",
            }
        )

    for rel in by_type.get("DERIVES") or []:
        sub = str(rel.get("subject") or "")
        local = (by_ent.get(sub) or {}).get("symbol") or sub.split(":")[-1]
        plan["derived_values"].append(
            {
                "local": local,
                "inputs": rel.get("inputs") or [],
                "origin": "relation:DERIVES",
            }
        )
        plan["derived_roots"].append(local)

    # GUARDS / SELECTS_TEMPLATE / GROUNDED_IN
    for rel in by_type.get("GUARDS") or []:
        sub = str(rel.get("subject") or "")
        obj = str(rel.get("object") or "")
        sub_ent = by_ent.get(sub) or {}
        obj_ent = by_ent.get(obj) or {}
        if sub_ent.get("kind") == "condition":
            plan["condition_nodes"].append(
                {
                    "id": sub,
                    "symbol": sub_ent.get("symbol"),
                    "evidence_refs": rel.get("evidence_refs") or [],
                }
            )
        if obj_ent.get("kind") == "branch":
            plan["branch_nodes"].append(
                {
                    "id": obj,
                    "symbol": obj_ent.get("symbol"),
                    "guard": sub,
                    "evidence_refs": rel.get("evidence_refs") or [],
                }
            )

    for rel in by_type.get("SELECTS_TEMPLATE") or []:
        obj = str(rel.get("object") or "")
        ent = by_ent.get(obj) or {}
        plan["template_nodes"].append(
            {
                "id": obj,
                "symbol": ent.get("symbol") or obj.split(":")[-1],
                "selected_by": rel.get("subject"),
                "evidence_refs": rel.get("evidence_refs") or [],
            }
        )

    for rel in by_type.get("GROUNDED_IN") or []:
        plan["groundings"].append(
            {
                "subject": rel.get("subject"),
                "input_root": rel.get("object"),
                "evidence_refs": rel.get("evidence_refs") or [],
            }
        )

    # Deferred unresolved
    for u in graph.get("unresolved") or []:
        if isinstance(u, dict):
            plan["deferred_candidates"].append(
                {
                    "obligation_id": u.get("obligation_id"),
                    "reason_code": u.get("reason_code") or "unresolved",
                }
            )

    # Deduplicate writers by (name, role)
    seen_w: set[tuple[str, str]] = set()
    uniq_w = []
    for w in plan["writers"]:
        key = (str(w.get("name") or ""), str(w.get("role") or ""))
        if key in seen_w:
            continue
        seen_w.add(key)
        uniq_w.append(w)
    plan["writers"] = uniq_w

    seen_r: set[str] = set()
    uniq_r = []
    for r in plan["receivers"]:
        name = str(r.get("name") or "")
        if name in seen_r:
            continue
        seen_r.add(name)
        uniq_r.append(r)
    plan["receivers"] = uniq_r

    return plan


def hydrate_materialized_plan(
    plan: dict[str, Any],
    candidates: dict[str, Any],
    *,
    candidates_sha256: str = "",
) -> dict[str, Any]:
    """Stamp sha + copy candidate evidence/identity onto relation-derived rows.

    Relation materialize proves *what* is selected; candidates remain the evidence
    authority for windows / roles / identity fields required by validate.
    """
    from uo.scripts.extract_plan_autofill import required_high_confidence_candidate_ids
    from uo.scripts.extract_plan_io import HELPER_WRITER_NAMES, _match_candidate

    if candidates_sha256 and not plan.get("candidates_sha256"):
        plan["candidates_sha256"] = candidates_sha256
    if not plan.get("candidates_sha256"):
        side = str(candidates.get("candidates_sha256") or "").strip()
        if side:
            plan["candidates_sha256"] = side

    writer_pool = [c for c in (candidates.get("writer_candidates") or []) if isinstance(c, dict)]
    recv_pool = [c for c in (candidates.get("receiver_candidates") or []) if isinstance(c, dict)]
    by_cid = {
        str(c.get("candidate_id") or ""): c
        for c in writer_pool + recv_pool
        if str(c.get("candidate_id") or "").strip()
    }

    used_ids: set[str] = set()

    def _pick_by_name(row: dict[str, Any], pool: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Disambiguate same-name candidates for hydrate (prefer CAND ref / role / score)."""
        # Prefer explicit CAND: evidence_refs from relation closure.
        for er in row.get("evidence_refs") or []:
            s = str(er or "")
            if s.startswith("CAND:"):
                hit = by_cid.get(s[5:])
                if hit is not None:
                    return hit
            elif s.startswith("CAND_") and s in by_cid:
                return by_cid[s]

        hit = _match_candidate(row, pool)
        if hit is not None:
            return hit

        name = str(row.get("name") or "").strip()
        if not name:
            return None
        same = [
            c
            for c in pool
            if str(c.get("name") or "").strip().casefold() == name.casefold()
        ]
        if not same:
            return None
        role = str(row.get("role") or "").strip()
        # Prefer non-ignore + role match + highest score + has source_window.
        def _key(c: dict[str, Any]) -> tuple:
            sug = str(c.get("role_suggested") or "").strip()
            ignore = 1 if sug == "ignore" else 0
            role_miss = 0 if (not role or sug == role or not sug) else 1
            has_sw = 0 if isinstance(c.get("source_window"), dict) else 1
            score = -float(c.get("score") or 0)
            return (ignore, role_miss, has_sw, score)

        same.sort(key=_key)
        return same[0]

    def _apply_window(row: dict[str, Any], cand: dict[str, Any]) -> None:
        sw = cand.get("source_window") if isinstance(cand.get("source_window"), dict) else {}
        fp = str(cand.get("file_path") or sw.get("file_path") or "").replace("\\", "/").strip()
        if fp and not row.get("file_path"):
            row["file_path"] = fp
        for k in ("qualified_name", "class_or_namespace", "identity_key", "start_line", "end_line"):
            if cand.get(k) is not None and not row.get(k):
                row[k] = cand.get(k)
        cid = str(cand.get("candidate_id") or "").strip()
        if cid:
            row["candidate_id"] = cid
            used_ids.add(cid)
        suggested = str(cand.get("role_suggested") or "").strip()
        if suggested:
            row["role"] = suggested
        if sw:
            lo = int(sw.get("start_line") or cand.get("start_line") or 0)
            hi = int(sw.get("end_line") or cand.get("end_line") or lo)
            text = str(sw.get("text") or "")
            sha = str(sw.get("sha256") or "").strip()
            if fp:
                row.setdefault("evidence_files", [fp])
            if lo and hi:
                row.setdefault("evidence_lines", [lo, hi])
            if text and not row.get("evidence_snippet"):
                row["evidence_snippet"] = text
            if sha and not row.get("evidence_window_sha256"):
                row["evidence_window_sha256"] = sha
            row["evidence_source"] = "source"
            row["source_verified"] = True
        elif cand.get("snippet") and not row.get("evidence_snippet"):
            row.setdefault("evidence_source", "candidate_only")

    writers: list[Any] = []
    for item in plan.get("writers") or []:
        if not isinstance(item, dict):
            writers.append(item)
            continue
        name = str(item.get("name") or "").strip()
        if name.casefold() in HELPER_WRITER_NAMES:
            # Alignment/math helpers must not be promoted writers.
            continue
        row = dict(item)
        cand = _pick_by_name(row, writer_pool)
        if cand is not None:
            _apply_window(row, cand)
            # Drop after hydrate if candidate says ignore.
            if str(row.get("role") or "") == "ignore":
                continue
        if name.casefold() in HELPER_WRITER_NAMES:
            continue
        writers.append(row)
    plan["writers"] = writers

    receivers: list[Any] = []
    for item in plan.get("receivers") or []:
        if not isinstance(item, dict):
            receivers.append(item)
            continue
        row = dict(item)
        cand = _pick_by_name(row, recv_pool)
        if cand is not None:
            _apply_window(row, cand)
            if "is_tiling_sink_suggested" in cand and "is_tiling_sink" not in row:
                row["is_tiling_sink"] = bool(cand.get("is_tiling_sink_suggested"))
        receivers.append(row)
    plan["receivers"] = receivers

    for b in plan.get("receiver_bindings") or []:
        if isinstance(b, dict) and b.get("candidate_id"):
            used_ids.add(str(b["candidate_id"]))
    for a in plan.get("aliases") or []:
        if isinstance(a, dict) and a.get("candidate_id"):
            used_ids.add(str(a["candidate_id"]))

    plan.setdefault("accepted_candidates", [])
    plan.setdefault("rejected_candidates", [])
    plan.setdefault("deferred_candidates", [])
    accepted_ids = {
        str(x.get("candidate_id") or "")
        for x in plan["accepted_candidates"]
        if isinstance(x, dict)
    }
    for cid in sorted(used_ids):
        if cid and cid not in accepted_ids:
            plan["accepted_candidates"].append(
                {"candidate_id": cid, "reason_code": "relation_materialized"}
            )
            accepted_ids.add(cid)

    covered = set(accepted_ids)
    for key in ("rejected_candidates", "deferred_candidates"):
        for x in plan.get(key) or []:
            if isinstance(x, dict) and x.get("candidate_id"):
                covered.add(str(x["candidate_id"]))
    for cid in required_high_confidence_candidate_ids(candidates):
        if cid not in covered:
            plan["deferred_candidates"].append(
                {
                    "candidate_id": cid,
                    "reason_code": "relation_not_selected",
                }
            )
            covered.add(cid)

    return plan


__all__ = ["materialize_from_relations", "hydrate_materialized_plan"]
