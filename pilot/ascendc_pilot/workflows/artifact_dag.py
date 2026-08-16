"""Static Producer/Consumer DAG for Workflow Spec artifacts.

``produces`` / output contracts are facts. ``allowed_write_paths`` are
permissions only and must never be treated as producers.
"""

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
    "uo_product_ready": ["uo/*.uo"],
    "integrity": ["uo/checks/integrity.yaml"],
    # gate_uo_ready_tg: CodeMap .uo product (+ view blobs inside).
    "kb_ready": ["uo/*.uo"],
    "uo_ready": ["uo/*.uo"],
    # EXTERNAL rebuildable context pack.
    "context_pack": ["context/**"],
    "init_confirmed": ["tg/init/status.yaml"],
    "tg_init_confirmed": ["tg/init/status.yaml"],
    "kb_fingerprint_fresh": ["tg/init/kb_fingerprint.yaml"],
    # Also reads .uo view blobs (covered by uo/*.uo logical producer).
    "tilingkey_binding_ready": ["tg/realization/binding_inventory.yaml"],
    "audit_pass": ["tg/init/audit_report.yaml"],
    "plan_approved": ["tg/plan/levels/*/human_supplement.yaml"],
    # Ledger soundness (certificate is written by certify after this gate).
    "closure_soundness": [
        "tg/closure/R.txt",
        "tg/closure/open.txt",
        "tg/closure/excluded.txt",
    ],
    "obligations_classified": [
        "ce/impact/risk_classification.yaml",
        "ce/impact/obligations.yaml",
    ],
    "impact_ledger_ready": [
        "ce/impact/obligations.yaml",
        "ce/impact/ledger.yaml",
    ],
    "ce_certificate_sound": ["ce/verify/certificate.yaml"],
    "scenario_coverage_sound": [
        "tg/closure/scenario_certificate.yaml",
        "tg/closure/scenarios/construct.yaml",
        "tg/closure/scenarios/harness_results.yaml",
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
    "uo/*.uo",
}


def _norm(path: str) -> str:
    p = str(path or "").replace("\\", "/").strip()
    if not p:
        return ""
    # Collapse logical CodeMap product roots only — keep concrete uo/** paths.
    if p in {"uo", "uo/**", "../uo", "../uo/**", "../uo/*.uo", "uo/*.uo"}:
        return "uo/*.uo"
    if fnmatch.fnmatch(p, "../uo/*.uo") or fnmatch.fnmatch(p, "uo/*.uo"):
        return "uo/*.uo"
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
    return path in _UO_LOGICAL or path == "uo/*.uo" or path.endswith(".uo")


def _contract_paths(contract_id: str) -> list[str]:
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS

    out: list[str] = []
    cid = str(contract_id or "").strip()
    if not cid:
        return out
    for raw in OUTPUT_CONTRACT_PATHS.get(cid) or []:
        p = _norm(str(raw))
        if p and p not in out:
            out.append(p)
    return out


def action_pre_gates(action: dict[str, Any]) -> list[str]:
    return [str(g).strip() for g in (action.get("pre_gates") or []) if str(g).strip()]


def action_post_gates(action: dict[str, Any]) -> list[str]:
    return [str(g).strip() for g in (action.get("post_gates") or []) if str(g).strip()]


def is_staged_producer(action: dict[str, Any]) -> bool:
    return (
        str(action.get("output_mode") or "").strip().lower() == "staged"
        and str(action.get("role_id") or "") == "producer"
    )


def normalize_actor_outputs(action: dict[str, Any]) -> list[str]:
    """Paths the LLM/actor writes (staging contract only)."""
    if not is_staged_producer(action):
        return []
    return _contract_paths(str(action.get("staging_contract_id") or ""))


def normalize_published(action: dict[str, Any]) -> list[str]:
    """Canonical published paths. Staged producers do not own merge/canonical files."""
    explicit = action.get("produces")
    if explicit is not None:
        out: list[str] = []
        for raw in explicit:
            p = _norm(str(raw))
            if p and p not in out:
                out.append(p)
        return out
    if is_staged_producer(action):
        return []
    return _contract_paths(str(action.get("output_contract_id") or ""))


def normalize_produces(action: dict[str, Any]) -> list[str]:
    """DAG produces = published canonical outputs only."""
    return normalize_published(action)


def normalize_consumes(action: dict[str, Any]) -> list[str]:
    """Resolve consumed artifact paths (explicit + pre_gate-inferred).

    ``post_gates`` must never contribute consumes.
    """
    out: list[str] = []
    for raw in action.get("consumes") or []:
        p = _norm(str(raw))
        if p and p not in out:
            out.append(p)
    for gid in action_pre_gates(action):
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


def _action_phases(action: dict[str, Any]) -> set[str]:
    return {str(p) for p in (action.get("phases") or []) if str(p).strip()}


def _phase_of_owner(meta: dict[str, Any], aid: str) -> str:
    for action in meta.get("actions") or []:
        if not isinstance(action, dict):
            continue
        if str(action.get("id") or "") != aid:
            continue
        phases = list(_action_phases(action))
        return phases[0] if phases else ""
    return ""


def _reachable_forward_only(
    entry: str,
    transitions: list[dict[str, Any]],
    phases: set[str],
) -> dict[str, set[str]]:
    """Map phase -> phases reachable via *forward* edges only.

    Rework edges encode recovery legality, not initial artifact availability.
    Including them would falsely allow a later producer to precede an earlier
    consumer through a back-edge (e.g. commit → analyze → extract).
    """
    del entry  # reachability is computed from each phase; entry unused
    adj: dict[str, set[str]] = {p: set() for p in phases}
    for edge in transitions:
        if not isinstance(edge, dict):
            continue
        kind = str(edge.get("kind") or "forward").strip().lower()
        if kind != "forward":
            continue
        frm = str(edge.get("from") or "")
        to = str(edge.get("to") or "")
        if frm in adj and to in phases:
            adj[frm].add(to)

    def flood(start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start] if start in phases else []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(sorted(adj.get(cur) or ()))
        return seen

    return {p: flood(p) for p in phases}


def _producer_precedes_consumer(
    *,
    producer_owner: str,
    consumer_owner: str,
    meta: dict[str, Any],
    reach: dict[str, set[str]],
) -> bool:
    """True when producer phase can reach consumer phase (incl. same phase earlier in pipeline)."""
    p_wid, _, p_aid = producer_owner.partition("/")
    c_wid, _, c_aid = consumer_owner.partition("/")
    del p_wid, c_wid
    p_phase = _phase_of_owner(meta, p_aid)
    c_phase = _phase_of_owner(meta, c_aid)
    if not p_phase or not c_phase:
        return True  # cannot prove; leave to orphan check only
    if p_phase == c_phase:
        # Same phase: producer must appear at or before consumer in pipeline list.
        pipes = meta.get("pipelines") if isinstance(meta.get("pipelines"), dict) else {}
        pipe = [str(x) for x in (pipes.get(p_phase) or [])]
        if p_aid in pipe and c_aid in pipe:
            return pipe.index(p_aid) <= pipe.index(c_aid)
        # Shared multi-phase action covering both — ok.
        return True
    return c_phase in (reach.get(p_phase) or set())


def check_artifact_dag(
    workflows: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Return orphan / topology / ambiguity errors for slash workflows."""
    # Ensure composite OUTPUT_CONTRACT_PATHS overlays are applied.
    try:
        import ascendc_pilot.actions  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    # Per-workflow producers: path -> set of owner ids within that workflow.
    # Cross-workflow UO product uses dedicated logical ownership.
    errors: list[str] = []
    user_wfs = _iter_user_workflows(workflows)

    # Global producers for cross-workflow existence (e.g. tg-init → tg-plan).
    global_producers: dict[str, set[str]] = {}

    def add_global(path: str, owner: str) -> None:
        path = _norm(path)
        if not path:
            return
        global_producers.setdefault(path, set()).add(owner)
        if path == "uo/*.uo" or path.endswith(".uo"):
            for logical in _UO_LOGICAL:
                global_producers.setdefault(logical, set()).add(owner)

    for wid, meta in user_wfs:
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            if not aid:
                continue
            owner = f"{wid}/{aid}"
            for path in normalize_produces(action):
                add_global(path, owner)
    add_global("uo/*.uo", "uo-init/commit")

    for wid, meta in user_wfs:
        producers: dict[str, set[str]] = {}

        def add_producer(path: str, owner: str) -> None:
            path = _norm(path)
            if not path:
                return
            producers.setdefault(path, set()).add(owner)
            if path == "uo/*.uo" or path.endswith(".uo"):
                for logical in _UO_LOGICAL:
                    producers.setdefault(logical, set()).add(owner)

        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            if not aid:
                continue
            owner = f"{wid}/{aid}"
            for path in normalize_produces(action):
                add_producer(path, owner)
            # NOTE: allowed_write_paths are permissions, never producers.

        if wid == "uo-init":
            producers.setdefault("uo/*.uo", set()).add("uo-init/commit")
            for logical in _UO_LOGICAL:
                producers.setdefault(logical, set()).add("uo-init/commit")

        transitions = [e for e in (meta.get("transitions") or []) if isinstance(e, dict)]
        phases = set()
        for action in meta.get("actions") or []:
            if isinstance(action, dict):
                phases |= _action_phases(action)
        for st in meta.get("states") or []:
            if isinstance(st, dict) and st.get("id"):
                phases.add(str(st["id"]))
        entry = str(meta.get("entry_state") or "")
        reach = _reachable_forward_only(entry, transitions, phases)

        for path, owners in sorted(producers.items()):
            if path in _UO_LOGICAL or path == "uo/*.uo":
                continue
            if _is_external(path):
                continue
            if len(owners) <= 1:
                continue
            # Sequential rewrites along the pipeline are allowed; flag only when
            # two producers are incomparable on the reachability graph.
            owner_list = sorted(owners)
            unordered = False
            for i, a in enumerate(owner_list):
                for b in owner_list[i + 1 :]:
                    ab = _producer_precedes_consumer(
                        producer_owner=a,
                        consumer_owner=b,
                        meta=meta,
                        reach=reach,
                    )
                    ba = _producer_precedes_consumer(
                        producer_owner=b,
                        consumer_owner=a,
                        meta=meta,
                        reach=reach,
                    )
                    if not ab and not ba:
                        unordered = True
                        break
                if unordered:
                    break
            if unordered:
                errors.append(
                    f"ARTIFACT_PRODUCER_AMBIGUOUS: {wid} path {path} owners={owner_list}"
                )

        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            if not aid:
                continue
            owner = f"{wid}/{aid}"
            consume_paths = normalize_consumes(action)
            published = normalize_published(action)
            overlap = [
                p
                for p in published
                if p in consume_paths and p and not _is_external(p)
            ]
            if overlap:
                errors.append(
                    f"ARTIFACT_SELF_CONSUME: {owner} published∩consumes={overlap}"
                )
            for gid in action_post_gates(action):
                for raw in GATE_ARTIFACT_READS.get(gid) or []:
                    p = _norm(str(raw))
                    if p and p in consume_paths and not _is_external(p):
                        errors.append(
                            f"ARTIFACT_POST_GATE_CONSUME: {owner} post_gate {gid} "
                            f"must not infer consumes {p}"
                        )
            for path in consume_paths:
                if not path or _is_external(path):
                    continue
                local_owners = _producer_covers(path, producers)
                global_owners = _producer_covers(path, global_producers)
                if _is_uo_logical(path):
                    if local_owners or global_owners or _producer_covers("uo/*.uo", global_producers):
                        continue
                    errors.append(f"ARTIFACT_ORPHAN_CONSUME: {owner} consumes {path}")
                    continue
                if not local_owners and not global_owners:
                    errors.append(f"ARTIFACT_ORPHAN_CONSUME: {owner} consumes {path}")
                    continue
                # Topology only for same-workflow producers.
                if not local_owners:
                    continue
                ok_order = False
                for prod_owner in local_owners:
                    if prod_owner == owner:
                        continue
                    if _producer_precedes_consumer(
                        producer_owner=prod_owner,
                        consumer_owner=owner,
                        meta=meta,
                        reach=reach,
                    ):
                        ok_order = True
                        break
                if not ok_order:
                    errors.append(
                        "ARTIFACT_PRODUCER_NOT_BEFORE_CONSUMER: "
                        f"{owner} consumes {path} producers={sorted(local_owners)}"
                    )
    return sorted(set(errors))


RECEIPT_ARTIFACTS = frozenset(
    {
        "runs/{run_id}/receipts/uo_ready.yaml",
        "runs/{run_id}/receipts/integrity_gate.yaml",
    }
)


def check_artifact_usage(repo_root: Any = None) -> list[str]:
    """Declared contract paths must appear as writers in engines.py.

    Catches historical stubs (e.g. understand_contract.json) that the DAG
    listed but no later step actually read.
    """
    from pathlib import Path

    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS

    here = Path(__file__).resolve()
    engines = here.parents[1] / "actions" / "engines.py"
    if repo_root is not None:
        root = Path(repo_root)
        engines = root / "pilot" / "ascendc_pilot" / "actions" / "engines.py"
        pkg = root / "pilot" / "ascendc_pilot"
        harness = (
            root
            / "engines"
            / "code-engineering"
            / "code_engineering"
            / "harness"
            / "__init__.py"
        )
    else:
        pkg = here.parents[1]
        harness = (
            here.parents[3]
            / "engines"
            / "code-engineering"
            / "code_engineering"
            / "harness"
            / "__init__.py"
        )
    blobs: list[str] = []
    for path in (
        engines,
        pkg / "actions" / "__init__.py",
        pkg / "ownership.py",
        pkg / "actions" / "runtime.py",
        harness,
    ):
        if path.is_file():
            blobs.append(path.read_text(encoding="utf-8"))
    text = "\n".join(blobs)
    errors: list[str] = []
    for cid, paths in OUTPUT_CONTRACT_PATHS.items():
        for raw in paths:
            name = str(raw).replace("\\", "/").rsplit("/", 1)[-1]
            if not name or "*" in name or "{" in name:
                continue
            if name not in text:
                errors.append(
                    f"ARTIFACT_USAGE: {cid} declares {raw} but no engine/harness/ownership mention of {name}"
                )
    for raw in RECEIPT_ARTIFACTS:
        rel = str(raw).replace("\\", "/")
        if not rel.startswith("runs/") or "/receipts/" not in rel:
            errors.append(f"RECEIPT_NOT_UNDER_RUNS: {raw}")
        name = rel.rsplit("/", 1)[-1]
        if name and f'_write_run_receipt' in text:
            if f'"{name}"' not in text and f"'{name}'" not in text:
                errors.append(f"ARTIFACT_USAGE: receipt {raw} has no _write_run_receipt writer")
    if "understand_contract.json" in text and "write_text" in text:
        # Residual stub writer is a usage bug even if not in OUTPUT_CONTRACT_PATHS.
        if "snapshot_hash" in text or "tg-tilingkey-snapshot" in text:
            errors.append("ARTIFACT_USAGE: understand_contract.json stub writer still present")
    return errors
