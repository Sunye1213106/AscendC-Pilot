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


def _cand_identity(item: dict[str, Any]) -> str:
    if item.get("identity_key"):
        return str(item["identity_key"]).casefold()
    fp = str(item.get("file_path") or "").replace("\\", "/")
    qn = str(item.get("qualified_name") or item.get("name") or "")
    cls = str(item.get("class_or_namespace") or "")
    return f"{fp}|{qn}|{cls}".casefold()


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
    roots = plan.get("non_sink_roots") or []
    return {str(r).strip().casefold() for r in roots if str(r).strip()}


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
    roots = plan.get("derived_roots") or []
    return {str(r).strip() for r in roots if str(r).strip()}


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
    }
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
    return by_name[0] if by_name else None


def normalize_plan_from_candidates(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing role / is_tiling_sink from candidate suggestions before validate.

    Does not invent writers/receivers; only completes confirmation labels.
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
            else:
                # Receivers that made it into candidates via set_* are sinks by default.
                row["is_tiling_sink"] = True
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

    for root in plan.get("non_sink_roots") or []:
        r = str(root).strip()
        if r and r.casefold() not in non_sink_cands and r.casefold() not in recv_cf:
            # Allow non_sink from receivers too (LLM may mark intermediate receivers)
            if r.casefold() not in {n.casefold() for n in recv_names}:
                errors.append(f"non_sink_root not in candidates: {r}")

    for entry in plan.get("extra_host_entries") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
        else:
            name = str(entry).strip()
        if name and name not in extra_cands and name.casefold() not in {n.casefold() for n in extra_cands}:
            errors.append(f"extra_host_entry not in candidates: {name}")

    return errors
