"""Shared extract_plan load / validate helpers (no operator-specific names)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml

WRITER_ROLES = frozenset(
    {
        "tiling_writer",
        "key_writer",
        "workspace_writer",
        "provenance_helper",
        "ignore",
    }
)

# Roles that stay on the host call chain (attrs/branches), including TDF writers.
CHAIN_ROLES = frozenset(
    {
        "tiling_writer",
        "key_writer",
        "workspace_writer",
        "provenance_helper",
    }
)

EVIDENCE_SOURCES = frozenset({"source", "cbm", "candidate_only"})
PROMOTED_WRITER_ROLES = frozenset({"tiling_writer", "key_writer"})
WEAK_SCORE_THRESHOLD = 0.55


def _cand_identity(item: dict[str, Any]) -> str:
    if item.get("identity_key"):
        return str(item["identity_key"]).casefold()
    fp = str(item.get("file_path") or "").replace("\\", "/")
    qn = str(item.get("qualified_name") or item.get("name") or "")
    cls = str(item.get("class_or_namespace") or "")
    sig = str(item.get("normalized_signature") or item.get("signature") or "")
    tpl = str(item.get("template_arity_or_signature") or "")
    return f"{fp}|{qn}|{cls}|{sig}|{tpl}".casefold()


def load_extract_plan(uo_root: Path) -> dict[str, Any] | None:
    path = uo_root / "ir" / "extract_plan.yaml"
    if not path.is_file():
        return None
    data = read_yaml(path)
    return data if isinstance(data, dict) else None


def plan_writer_names(plan: dict[str, Any], *, roles: set[str] | None = None) -> set[str]:
    allowed = roles or CHAIN_ROLES
    out: set[str] = set()
    for item in plan.get("writers") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in allowed:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            out.add(name)
            out.add(name.casefold())
    return out


def plan_tiling_writer_names(plan: dict[str, Any]) -> set[str]:
    return plan_writer_names(plan, roles={"tiling_writer", "workspace_writer"})


def plan_chain_names(plan: dict[str, Any]) -> set[str]:
    """Helpers kept on host chain (writers + provenance), excluding ignore."""
    return plan_writer_names(plan, roles=set(CHAIN_ROLES))


def plan_provenance_names(plan: dict[str, Any]) -> set[str]:
    return plan_writer_names(plan, roles={"provenance_helper"})

def plan_tiling_sink_receivers(plan: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in plan.get("receivers") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("is_tiling_sink"):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            out.add(name)
            out.add(name.casefold())
    return out


def plan_non_sink_roots(plan: dict[str, Any]) -> set[str]:
    """Accepted non-sink roots are bare string names only (contract)."""
    out: set[str] = set()
    for r in plan.get("non_sink_roots") or []:
        if isinstance(r, str) and r.strip():
            out.add(r.strip().casefold())
    return out


def plan_aliases(plan: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in plan.get("aliases") or []:
        if not isinstance(item, dict):
            continue
        local = str(item.get("local") or "").strip()
        leaf = str(item.get("tdf_leaf") or "").strip()
        if local and leaf:
            out[local] = leaf
    return out


def plan_derived_roots(plan: dict[str, Any]) -> set[str]:
    """Accepted derived roots are bare string names only (contract)."""
    out: set[str] = set()
    for r in plan.get("derived_roots") or []:
        if isinstance(r, str) and r.strip():
            out.add(r.strip())
    return out


def _validate_string_name_list(
    values: Any,
    *,
    field: str,
    allowed_cf: set[str],
    errors: list[str],
) -> None:
    """``non_sink_roots`` / ``derived_roots``: string names only; no mapping/adjudication objects."""
    if values is None:
        return
    if not isinstance(values, list):
        errors.append(f"{field} must be a list of string names")
        return
    for item in values:
        if isinstance(item, dict):
            errors.append(
                f"{field} entry must be a string name, got mapping "
                "(do not write adjudication/unresolved objects; "
                "confirm with a bare string or omit the name)"
            )
            continue
        if not isinstance(item, str):
            errors.append(f"{field} entry must be a string name, got {type(item).__name__}")
            continue
        name = item.strip()
        if not name:
            continue
        if name.casefold() not in allowed_cf:
            errors.append(f"{field[:-1] if field.endswith('s') else field} not in candidates: {name}")


# Top-level keys that belong in ledger / llm_tasks — never in extract_plan.yaml.
FORBIDDEN_EXTRACT_PLAN_KEYS = frozenset(
    {
        "call_edge_adjudications",
        "llm_tasks",
        "tasks",
        "edge_patches",
        "semantic_patches",
        "dispatches_to",
        "mark_missing",
        "accepted_edges",
        "entrypoint_dispatch_bind",
        "accepted_candidate_ids",
        "blocking_reasons",
    }
)


def _effective_evidence_source(item: dict[str, Any]) -> str:
    raw = str(item.get("evidence_source") or "").strip()
    if raw in EVIDENCE_SOURCES:
        return raw
    return "candidate_only"


def _evidence_list(cand: dict[str, Any] | None) -> set[str]:
    if not cand:
        return set()
    ev = cand.get("evidence")
    if not isinstance(ev, list):
        return set()
    return {str(x).strip() for x in ev if str(x).strip()}


STRONG_WRITER_EVIDENCE = frozenset(
    {"tilingdata_assign", "recv_set_call", "sink_set_writer", "one_hop_callee"}
)


def _writer_candidate_weak(
    item: dict[str, Any],
    cand: dict[str, Any] | None,
    all_writers: list[dict[str, Any]],
) -> bool:
    """True when heuristic score/evidence is too weak to promote without source read."""
    name = str(item.get("name") or "").strip()
    if not name:
        return False
    same_name = sum(
        1
        for c in all_writers
        if isinstance(c, dict) and str(c.get("name") or "").casefold() == name.casefold()
    )
    if same_name > 1:
        return True
    if not cand:
        # No matched candidate — treat promotion as weak (fail-closed).
        return True
    score = float(cand.get("score") or 0)
    if score > 0 and score < WEAK_SCORE_THRESHOLD:
        return True
    ev = _evidence_list(cand)
    if "assign_lhs_only" in ev:
        return True
    if "has_set_field" in ev and not (ev & STRONG_WRITER_EVIDENCE):
        return True
    # Suggested non-sink cannot be promoted to sink writer roles without source proof.
    if cand.get("is_tiling_sink_suggested") is False:
        return True
    if cand.get("non_sink_suggested") is True or cand.get("suggested_non_sink") is True:
        return True
    # Setter name alone cannot prove a real TilingData sink write.
    setter_only = bool(ev & {"has_set_field", "setter_name"}) and not (ev & STRONG_WRITER_EVIDENCE)
    if setter_only:
        return True
    qn = str(cand.get("qualified_name") or "").strip()
    cn = str(cand.get("name") or "").strip()
    if qn and cn and qn == cn and not str(cand.get("class_or_namespace") or "").strip():
        # Incomplete qualified name.
        return True
    start = int(item.get("start_line") or cand.get("start_line") or 0)
    if start > 0:
        fp = str(item.get("file_path") or cand.get("file_path") or "").replace("\\", "/")
        overlaps = [
            c
            for c in all_writers
            if isinstance(c, dict)
            and str(c.get("file_path") or "").replace("\\", "/") == fp
            and int(c.get("start_line") or 0) == start
            and str(c.get("name") or "").casefold() != name.casefold()
        ]
        if overlaps:
            return True
    return False


def _validate_decision_evidence(
    item: dict[str, Any],
    *,
    label: str,
    errors: list[str],
    cand: dict[str, Any] | None = None,
    all_pool: list[dict[str, Any]] | None = None,
    check_weak_writer_promotion: bool = False,
) -> None:
    """Source-evidence contract for accepted writer/receiver mappings."""
    evidence_source = _effective_evidence_source(item)
    source_verified = item.get("source_verified") is True

    if source_verified:
        if evidence_source not in ("source", "cbm"):
            errors.append(
                f"{label} source_verified:true requires evidence_source source or cbm "
                f"(got {evidence_source!r})"
            )
        files = item.get("evidence_files")
        if not isinstance(files, list) or not any(str(f).strip() for f in files):
            errors.append(f"{label} source_verified:true requires non-empty evidence_files")

    if evidence_source == "candidate_only":
        if source_verified:
            errors.append(f"{label} candidate_only cannot set source_verified:true")
        conf = str(item.get("confidence") or "").strip()
        if conf and conf != "candidate":
            errors.append(
                f"{label} evidence_source candidate_only requires confidence:candidate "
                f"(got {conf!r})"
            )

    if not str(item.get("evidence_source") or "").strip() and source_verified:
        errors.append(
            f"{label} source_verified:true requires explicit evidence_source source|cbm"
        )

    if check_weak_writer_promotion:
        role = str(item.get("role") or "").strip()
        promoting = role in PROMOTED_WRITER_ROLES or item.get("is_tiling_sink") is True
        if promoting and _writer_candidate_weak(item, cand, all_pool or []):
            # Weak candidate → must have real source/cbm evidence to promote.
            files = item.get("evidence_files")
            lines = item.get("evidence_lines")
            reason = str(item.get("decision_reason") or "").strip()
            has_files = isinstance(files, list) and any(str(f).strip() for f in files)
            has_lines = isinstance(lines, list) and any(str(x).strip() for x in lines)
            if evidence_source == "candidate_only" or not (
                evidence_source in ("source", "cbm")
                and item.get("source_verified") is True
                and has_files
                and has_lines
                and reason
            ):
                errors.append(
                    f"{label} weak candidate cannot promote to {role or 'tiling_sink'!r} "
                    "with candidate_only / missing source evidence "
                    "(require evidence_source source|cbm, source_verified:true, "
                    "non-empty evidence_files/evidence_lines/decision_reason; "
                    "or set role:ignore / omit the candidate)"
                )


def _match_candidate(
    item: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    fp = str(item.get("file_path") or "").replace("\\", "/").strip()
    qn = str(item.get("qualified_name") or "").strip()
    exact: list[dict[str, Any]] = []
    by_name: list[dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        cn = str(c.get("name") or "").strip()
        if cn.casefold() != name.casefold():
            continue
        by_name.append(c)
        cfp = str(c.get("file_path") or "").replace("\\", "/").strip()
        cqn = str(c.get("qualified_name") or "").strip()
        if (fp and cfp and fp == cfp) or (qn and cqn and qn == cqn):
            exact.append(c)
    if exact:
        return exact[0]
    if len(by_name) == 1:
        return by_name[0]
    # Ambiguous short-name match — fail closed (do not pick arbitrarily).
    return None


def normalize_plan_from_candidates(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing role from candidate suggestions before validate.

    Does not invent writers/receivers; does NOT default missing is_tiling_sink to true.
    Missing sink evidence must fail closed in validate.
    """
    out = dict(plan)
    writers = []
    for item in out.get("writers") or []:
        if not isinstance(item, dict):
            writers.append(item)
            continue
        row = dict(item)
        role = str(row.get("role") or "").strip()
        if role not in WRITER_ROLES:
            cand = _match_candidate(row, list(candidates.get("writer_candidates") or []))
            suggested = str((cand or {}).get("role_suggested") or "").strip()
            if suggested in WRITER_ROLES:
                row["role"] = suggested
        writers.append(row)
    out["writers"] = writers

    receivers = []
    for item in out.get("receivers") or []:
        if not isinstance(item, dict):
            receivers.append(item)
            continue
        row = dict(item)
        if "is_tiling_sink" not in row:
            cand = _match_candidate(row, list(candidates.get("receiver_candidates") or []))
            if cand is not None and "is_tiling_sink_suggested" in cand:
                row["is_tiling_sink"] = bool(cand.get("is_tiling_sink_suggested"))
            # else: leave unset → validate fails closed
        receivers.append(row)
    out["receivers"] = receivers
    return out


def validate_extract_plan_against_candidates(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> list[str]:
    """Return rejection reasons; empty means OK."""
    errors: list[str] = []
    if int(plan.get("version") or 0) != 1:
        errors.append("version must be 1")

    for key in plan:
        if str(key) in FORBIDDEN_EXTRACT_PLAN_KEYS:
            errors.append(
                f"forbidden extract_plan field {key!r} "
                "(edge/llm_task adjudication belongs in semantic_resolution_ledger via apply_semantic_patch)"
            )

    writer_names = {
        str(c.get("name") or "").strip()
        for c in (candidates.get("writer_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    recv_names = {
        str(c.get("name") or "").strip()
        for c in (candidates.get("receiver_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    alias_pairs = {
        (str(c.get("local") or "").strip(), str(c.get("tdf_leaf") or "").strip())
        for c in (candidates.get("alias_candidates") or [])
        if isinstance(c, dict)
    }
    non_sink_cands = {
        str(c.get("name") or "").strip().casefold()
        for c in (candidates.get("non_sink_root_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    extra_cands = {
        str(c.get("name") or "").strip()
        for c in (candidates.get("extra_entry_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    writer_cf = {n.casefold() for n in writer_names}
    recv_cf = {n.casefold() for n in recv_names}

    for item in plan.get("writers") or []:
        if not isinstance(item, dict):
            errors.append("writer entry must be mapping")
            continue
        name = str(item.get("name") or "").strip()
        role = str(item.get("role") or "").strip()
        if not name:
            errors.append("writer missing name")
        elif name not in writer_names and name.casefold() not in writer_cf:
            errors.append(f"writer not in candidates: {name}")
        # Require identity fields — ban short-name-only hits.
        if not (item.get("file_path") or item.get("qualified_name") or item.get("identity_key")):
            # Ban short-name-only when multiple candidates share the name.
            matches = [
                c
                for c in (candidates.get("writer_candidates") or [])
                if isinstance(c, dict) and str(c.get("name") or "").casefold() == name.casefold()
            ]
            if len(matches) > 1:
                errors.append(f"writer {name} ambiguous without identity fields (file_path|qualified_name|identity_key)")
        if role not in WRITER_ROLES:
            errors.append(
                f"writer {name or '?'} missing/invalid role {role!r} "
                f"(copy role_suggested from extract_plan_candidates.yaml; "
                f"allowed: {sorted(WRITER_ROLES)})"
            )
        writer_pool = list(candidates.get("writer_candidates") or [])
        matched = _match_candidate(item, writer_pool)
        _validate_decision_evidence(
            item,
            label=f"writer {name or '?'}",
            errors=errors,
            cand=matched,
            all_pool=writer_pool,
            check_weak_writer_promotion=True,
        )

    for item in plan.get("receivers") or []:
        if not isinstance(item, dict):
            errors.append("receiver entry must be mapping")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            errors.append("receiver missing name")
        elif name not in recv_names and name.casefold() not in recv_cf:
            errors.append(f"receiver not in candidates: {name}")
        if not (item.get("file_path") or item.get("qualified_name") or item.get("identity_key")):
            matches = [
                c
                for c in (candidates.get("receiver_candidates") or [])
                if isinstance(c, dict) and str(c.get("name") or "").casefold() == name.casefold()
            ]
            if len(matches) > 1:
                errors.append(f"receiver {name} ambiguous without identity fields (file_path|qualified_name|identity_key)")
        if "is_tiling_sink" not in item:
            errors.append(
                f"receiver {name} missing is_tiling_sink "
                "(copy is_tiling_sink_suggested from extract_plan_candidates.yaml)"
            )
        recv_pool = list(candidates.get("receiver_candidates") or [])
        matched_recv = _match_candidate(item, recv_pool)
        _validate_decision_evidence(
            item,
            label=f"receiver {name or '?'}",
            errors=errors,
            cand=matched_recv,
            all_pool=recv_pool,
            check_weak_writer_promotion=False,
        )

    for item in plan.get("aliases") or []:
        if not isinstance(item, dict):
            errors.append("alias entry must be mapping")
            continue
        local = str(item.get("local") or "").strip()
        leaf = str(item.get("tdf_leaf") or "").strip()
        if not local or not leaf:
            errors.append("alias missing local/tdf_leaf")
        elif (local, leaf) not in alias_pairs and not any(
            a[0].casefold() == local.casefold() and a[1].casefold() == leaf.casefold() for a in alias_pairs
        ):
            errors.append(f"alias not in candidates: {local}={leaf}")

    # non_sink_roots: bare string names only (no identity fields; no adjudication dicts).
    # Allow names from non_sink_root_candidates or receivers (intermediate receivers).
    non_sink_allowed = set(non_sink_cands) | recv_cf | {n.casefold() for n in recv_names}
    _validate_string_name_list(
        plan.get("non_sink_roots"),
        field="non_sink_roots",
        allowed_cf=non_sink_allowed,
        errors=errors,
    )

    # derived_roots: bare string names only when present (optional; empty OK).
    derived = plan.get("derived_roots")
    if derived is not None:
        if not isinstance(derived, list):
            errors.append("derived_roots must be a list of string names")
        else:
            for item in derived:
                if isinstance(item, dict):
                    errors.append(
                        "derived_roots entry must be a string name, got mapping "
                        "(do not write adjudication/unresolved objects)"
                    )
                elif not isinstance(item, str):
                    errors.append(
                        f"derived_roots entry must be a string name, got {type(item).__name__}"
                    )

    for entry in plan.get("extra_host_entries") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
        else:
            name = str(entry).strip()
        if name and name not in extra_cands and name.casefold() not in {n.casefold() for n in extra_cands}:
            errors.append(f"extra_host_entry not in candidates: {name}")

    return errors
