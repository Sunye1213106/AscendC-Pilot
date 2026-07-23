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


def validate_extract_plan_against_candidates(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> list[str]:
    """Return rejection reasons; empty means OK."""
    errors: list[str] = []
    if int(plan.get("version") or 0) != 1:
        errors.append("version must be 1")

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
    # Also allow writers/receivers/aliases by casefold match
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
        if role not in WRITER_ROLES:
            errors.append(f"invalid writer role: {role!r}")

    for item in plan.get("receivers") or []:
        if not isinstance(item, dict):
            errors.append("receiver entry must be mapping")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            errors.append("receiver missing name")
        elif name not in recv_names and name.casefold() not in recv_cf:
            errors.append(f"receiver not in candidates: {name}")
        if "is_tiling_sink" not in item:
            errors.append(f"receiver {name} missing is_tiling_sink")

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
