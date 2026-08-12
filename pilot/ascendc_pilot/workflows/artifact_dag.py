"""Static Producer/Consumer DAG for Workflow Spec artifacts."""

from __future__ import annotations

import fnmatch
from typing import Any

# Gate → artifact paths it reads. Paths are under the arch-scoped agent root
# unless noted. Prefer under-declare over inventing wrong paths.
#
# EXTERNAL roots (not Spec-produced): context/**, runs/**, source/**,
# op_host/**, op_kernel/**, op_api/**, local/**, control/**
GATE_ARTIFACT_READS: dict[str, list[str]] = {
    # gate_layout_receipt: manifest + operator only (not build_variant).
    "layout_receipt": ["uo/manifest.yaml", "uo/operator.yaml"],
    "scope_receipt": ["uo/runs/{run_id}/scope/scope_validated.yaml"],
    "extract_receipt": [
        "uo/ir/host_extract_receipt.yaml",
        "uo/kernel/fold_receipt.yaml",
    ],
    "uo_product_ready": ["../uo/*.uo"],
    "integrity": ["uo/checks/integrity.yaml"],
    # gate_uo_ready_tg: CodeMap .uo product (+ view blobs inside).
    "kb_ready": ["../uo/*.uo"],
    "uo_ready": ["../uo/*.uo"],
    # EXTERNAL rebuildable context pack.
    "context_pack": ["context/**"],
    "init_confirmed": ["tg/init/status.yaml"],
    "tg_init_confirmed": ["tg/init/status.yaml"],
    "kb_fingerprint_fresh": ["tg/init/kb_fingerprint.yaml"],
    # Also reads .uo view blobs (covered by ../uo/*.uo logical producer).
    "tilingkey_binding_ready": ["tg/realization/binding_inventory.yaml"],
    "audit_pass": ["tg/init/audit_report.yaml"],
    "plan_approved": ["tg/plan/levels/*/human_supplement.yaml"],
    # Ledger soundness (certificate is written by certify after this gate).
    "closure_soundness": [
        "tg/closure/R.txt",
        "tg/closure/open.txt",
        "tg/closure/excluded.txt",
    ],
}

_EXTERNAL_ROOTS = (
    "context/**",
    "runs/**",
    "source/**",
    "op_host/**",
    "op_kernel/**",
    "op_api/**",
    "local/**",
    "control/**",
)

_UO_LOGICAL = {
    "uo:product",
    "uo:view:tiling/exhaustive_key_space",
    "uo:view:tiling/legal_key_index",
    "uo:view:ir/tg_host_view",
    "uo:view:ir/operator_graph",
    "uo:view:views/kernel",
    "uo:view:views/tilingdata",
    "../uo/*.uo",
}


def _norm(path: str) -> str:
    p = str(path or "").replace("\\", "/").strip()
    if not p:
        return ""
    # Collapse logical CodeMap product roots only — keep concrete uo/** paths.
    if p in {"uo", "uo/**", "../uo", "../uo/**", "../uo/*.uo"}:
        return "../uo/*.uo"
    if fnmatch.fnmatch(p, "../uo/*.uo") or fnmatch.fnmatch(p, "uo/*.uo"):
        return "../uo/*.uo"
    return p


def _is_external(path: str) -> bool:
    for root in _EXTERNAL_ROOTS:
        if fnmatch.fnmatch(path, root) or path == root.rstrip("/**") or path.startswith(root.rstrip("*")):
            return True
    for prefix in (
        "context/",
        "runs/",
        "source/",
        "op_host/",
        "op_kernel/",
        "op_api/",
        "local/",
        "control/",
    ):
        if path.startswith(prefix) or path == prefix.rstrip("/"):
            return True
    return False


def _is_uo_logical(path: str) -> bool:
    return path in _UO_LOGICAL or path == "../uo/*.uo" or path.endswith(".uo")


def normalize_produces(action: dict[str, Any]) -> list[str]:
    """Resolve produced artifact paths for an action."""
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS

    explicit = action.get("produces")
    if explicit is not None:
        out: list[str] = []
        for raw in explicit:
            p = _norm(str(raw))
            if p and p not in out:
                out.append(p)
        return out

    out = []
    cid = str(action.get("output_contract_id") or "").strip()
    if cid:
        for raw in OUTPUT_CONTRACT_PATHS.get(cid) or []:
            p = _norm(str(raw))
            if p and p not in out:
                out.append(p)
    sid = str(action.get("staging_contract_id") or "").strip()
    if sid:
        for raw in OUTPUT_CONTRACT_PATHS.get(sid) or []:
            p = _norm(str(raw))
            if p and p not in out:
                out.append(p)
    return out


def normalize_consumes(action: dict[str, Any]) -> list[str]:
    """Resolve consumed artifact paths (explicit + gate-inferred)."""
    out: list[str] = []
    for raw in action.get("consumes") or []:
        p = _norm(str(raw))
        if p and p not in out:
            out.append(p)
    for gate in action.get("gates") or []:
        gid = str(gate or "").strip()
        for raw in GATE_ARTIFACT_READS.get(gid) or []:
            p = _norm(str(raw))
            if p and p not in out:
                out.append(p)
    return out


def _producer_covers(path: str, producers: dict[str, set[str]]) -> set[str]:
    if path in producers:
        return set(producers[path])
    owners: set[str] = set()
    for prod, who in producers.items():
        if fnmatch.fnmatch(path, prod) or fnmatch.fnmatch(prod, path):
            owners |= who
        if prod.endswith("/**") and (path.startswith(prod[:-3]) or fnmatch.fnmatch(path, prod)):
            owners |= who
        if path.endswith("/**") and prod.startswith(path[:-3]):
            owners |= who
    return owners


def _iter_user_workflows(
    workflows: dict[str, dict[str, Any]] | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Yield (workflow_id, meta) for slash user workflows (not reserved)."""
    if workflows is not None:
        items = list(workflows.items())
    else:
        from ascendc_pilot.workflows import WORKFLOWS, get_workflow

        items = []
        for wid, meta in WORKFLOWS.items():
            if not isinstance(meta, dict):
                continue
            if not meta.get("slash") or meta.get("reserved") or meta.get("alias_of"):
                continue
            try:
                items.append((wid, get_workflow(wid)))
            except Exception:  # noqa: BLE001
                items.append((wid, meta))

    out: list[tuple[str, dict[str, Any]]] = []
    for wid, meta in items:
        if not isinstance(meta, dict):
            continue
        if not meta.get("slash") or meta.get("reserved") or meta.get("alias_of"):
            continue
        out.append((str(wid), meta))
    return out


def check_artifact_dag(
    workflows: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Return ARTIFACT_ORPHAN_CONSUME errors for slash workflows."""
    # Ensure composite OUTPUT_CONTRACT_PATHS overlays are applied.
    try:
        import ascendc_pilot.actions  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    producers: dict[str, set[str]] = {}

    def add_producer(path: str, owner: str) -> None:
        path = _norm(path)
        if not path:
            return
        producers.setdefault(path, set()).add(owner)
        if path == "../uo/*.uo" or path.endswith(".uo"):
            for logical in _UO_LOGICAL:
                producers.setdefault(logical, set()).add(owner)

    user_wfs = _iter_user_workflows(workflows)
    for wid, meta in user_wfs:
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            if not aid:
                continue
            owner = f"{wid}/{aid}"
            for path in normalize_produces(action):
                add_producer(path, owner)
            # Declared write scopes also count as producers (e.g. overlay paths
            # like tg/init/kb_fingerprint.yaml beyond the output contract).
            for raw in action.get("allowed_write_paths") or []:
                add_producer(str(raw), owner)

    # Formal UO product ownership even if contract list is incomplete.
    producers.setdefault("../uo/*.uo", set()).add("uo-init/commit")
    for logical in _UO_LOGICAL:
        producers.setdefault(logical, set()).add("uo-init/commit")

    errors: list[str] = []
    for wid, meta in user_wfs:
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            if not aid:
                continue
            owner = f"{wid}/{aid}"
            consume_paths = normalize_consumes(action)
            # Also require every GATE_ARTIFACT_READS entry for action gates.
            for gate in action.get("gates") or []:
                gid = str(gate or "").strip()
                if gid not in GATE_ARTIFACT_READS:
                    continue
                for raw in GATE_ARTIFACT_READS[gid]:
                    p = _norm(str(raw))
                    if p and p not in consume_paths:
                        consume_paths.append(p)
            for path in consume_paths:
                if not path or _is_external(path):
                    continue
                if _is_uo_logical(path):
                    if _producer_covers(path, producers) or _producer_covers("../uo/*.uo", producers):
                        continue
                owners = _producer_covers(path, producers)
                if owners:
                    continue
                errors.append(
                    f"ARTIFACT_ORPHAN_CONSUME: {owner} consumes {path}"
                )
    return sorted(set(errors))
