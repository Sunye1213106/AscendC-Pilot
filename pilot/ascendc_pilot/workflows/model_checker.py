"""Static Workflow Spec model checker (phase / transition / obligation graph).

Validates that every user-facing workflow is a coherent state machine:
reachable phases, well-formed rework edges, pipeline↔action closure, and
the TG-solve residual routing codes required by the control-plane contract.
"""

from __future__ import annotations

from typing import Any

# User-facing slash workflows: architecture builders ∪ .uo consumers.
MATRIX_WORKFLOWS: tuple[str, ...] = (
    "uo-init",
    "uo-update",
    "uo-query",
    "uo-investigate",
    "tg-init",
    "tg-plan",
    "tg-solve",
    "ce-review",
    "ce-plan",
    "ce-apply",
    "handoff",
)

# tg-solve rework codes after the product-model rebuild.
TG_SOLVE_REWORK_CODES: tuple[str, ...] = (
    "REWORK_CONSTRUCT",
    "OPEN_REMAINING",
    "OPEN_NONEMPTY",
    "CASE_REFINABLE",
)


def _phase_ids(meta: dict[str, Any]) -> list[str]:
    states = meta.get("states") or []
    if states:
        return [str(s["id"]) for s in states if isinstance(s, dict) and s.get("id")]
    return [str(p) for p in (meta.get("phases") or []) if str(p).strip()]


def _forward_reachable(entry: str, transitions: list[dict[str, Any]], phases: set[str]) -> set[str]:
    adj: dict[str, set[str]] = {p: set() for p in phases}
    for edge in transitions:
        if not isinstance(edge, dict):
            continue
        if str(edge.get("kind") or "forward") != "forward":
            continue
        frm = str(edge.get("from") or "")
        to = str(edge.get("to") or "")
        if frm in adj and to in phases:
            adj[frm].add(to)
    seen: set[str] = set()
    stack = [entry] if entry in phases else []
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(sorted(adj.get(cur) or ()))
    return seen


def _all_edge_reachable(entry: str, transitions: list[dict[str, Any]], phases: set[str]) -> set[str]:
    adj: dict[str, set[str]] = {p: set() for p in phases}
    for edge in transitions:
        if not isinstance(edge, dict):
            continue
        frm = str(edge.get("from") or "")
        to = str(edge.get("to") or "")
        if frm in adj and to in phases:
            adj[frm].add(to)
    seen: set[str] = set()
    stack = [entry] if entry in phases else []
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(sorted(adj.get(cur) or ()))
    return seen


def _rework_reason_map(transitions: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """reason_code → list of (from, to)."""
    out: dict[str, list[tuple[str, str]]] = {}
    for edge in transitions:
        if not isinstance(edge, dict) or str(edge.get("kind") or "") != "rework":
            continue
        frm = str(edge.get("from") or "")
        to = str(edge.get("to") or "")
        for code in edge.get("reason_codes") or []:
            c = str(code or "").strip()
            if not c:
                continue
            out.setdefault(c, []).append((frm, to))
    return out


def check_workflow(workflow_id: str, meta: dict[str, Any]) -> list[str]:
    """Return model-checker errors for one workflow meta dict."""
    errors: list[str] = []
    wid = workflow_id
    if meta.get("alias_of"):
        return errors
    if (meta.get("reserved") or not meta.get("slash")) and not (meta.get("actions") or []):
        return errors

    phases = _phase_ids(meta)
    phase_set = set(phases)
    if not phases:
        errors.append(f"{wid}: no phases/states declared")
        return errors

    entry = str(meta.get("entry_state") or "").strip()
    if not entry:
        errors.append(f"{wid}: missing entry_state")
    elif entry not in phase_set:
        errors.append(f"{wid}: entry_state {entry!r} not in phases")

    for term in meta.get("terminal_ready_states") or []:
        t = str(term or "").strip()
        if t and t not in phase_set:
            errors.append(f"{wid}: terminal_ready_state {t!r} not in phases")

    # phases[] list (if present) must match states ids.
    listed = [str(p) for p in (meta.get("phases") or []) if str(p).strip()]
    if listed and set(listed) != phase_set:
        errors.append(f"{wid}: phases[] != states ids ({sorted(set(listed) ^ phase_set)})")

    if "requires_project" not in meta:
        errors.append(f"{wid}: missing requires_project")
    if "requires_architecture" not in meta:
        errors.append(f"{wid}: missing requires_architecture")
    if "requires_uo_product" not in meta:
        errors.append(f"{wid}: missing requires_uo_product")
    if bool(meta.get("requires_architecture")) and bool(meta.get("requires_uo_product")):
        errors.append(
            f"{wid}: requires_architecture and requires_uo_product are mutually exclusive "
            "(build UO chooses arch*; consumers inherit arch from .uo)"
        )
    occ = str(meta.get("occupancy") or "").strip().lower()
    group = str(meta.get("occupancy_group") or "").strip()
    if occ not in {"exclusive", "shared"}:
        errors.append(f"{wid}: occupancy must be exclusive|shared (got {occ!r})")
    elif occ == "exclusive" and not group:
        errors.append(f"{wid}: exclusive occupancy requires occupancy_group")
    elif occ == "shared" and group:
        errors.append(f"{wid}: shared occupancy must have empty occupancy_group")
    from ascendc_pilot.workflows.specs import workflow_resource_sets

    _read, write_set = workflow_resource_sets(wid)
    if occ == "exclusive" and not write_set:
        errors.append(f"{wid}: exclusive occupancy requires non-empty write_set")
    if occ == "shared" and write_set:
        errors.append(f"{wid}: shared occupancy must have empty write_set")
    actions = [a for a in (meta.get("actions") or []) if isinstance(a, dict)]
    action_ids = {str(a.get("id") or "") for a in actions if a.get("id")}
    covered_phases: set[str] = set()
    for action in actions:
        aid = str(action.get("id") or "")
        if not aid:
            errors.append(f"{wid}: action missing id")
            continue
        if str(action.get("schema_version") or "").strip() == "":
            errors.append(f"{wid}/{aid}: missing schema_version")
        a_phases = [str(p) for p in (action.get("phases") or []) if str(p).strip()]
        if not a_phases:
            errors.append(f"{wid}/{aid}: action has no phases")
        for p in a_phases:
            if p not in phase_set:
                errors.append(f"{wid}/{aid}: phase {p!r} not in workflow phases")
            covered_phases.add(p)
        hi = str(action.get("human_interaction") or "none").strip().lower()
        if hi not in {"none", "confirm", "approve"}:
            errors.append(f"{wid}/{aid}: invalid human_interaction={hi!r}")

    pipelines = meta.get("pipelines") if isinstance(meta.get("pipelines"), dict) else {}
    for phase, pipe in pipelines.items():
        ph = str(phase)
        if ph not in phase_set:
            errors.append(f"{wid}: pipeline phase {ph!r} not in phases")
            continue
        if not isinstance(pipe, list):
            errors.append(f"{wid}: pipeline for {ph!r} must be a list")
            continue
        # Empty pipeline is allowed only for terminal_ready_states (no-op final phase).
        terminal = {str(x) for x in (meta.get("terminal_ready_states") or [])}
        if not pipe:
            if ph in terminal:
                covered_phases.add(ph)
            else:
                errors.append(f"{wid}: non-terminal phase {ph!r} has empty pipeline")
            continue
        for raw in pipe:
            pid = str(raw or "").strip()
            if pid and pid not in action_ids:
                errors.append(f"{wid}: pipeline {ph}/{pid} not an action id")
        if pipe:
            covered_phases.add(ph)

    for ph in phase_set:
        if ph not in covered_phases:
            errors.append(f"{wid}: phase {ph!r} has no action/pipeline coverage")

    transitions = [e for e in (meta.get("transitions") or []) if isinstance(e, dict)]
    for edge in transitions:
        frm = str(edge.get("from") or "")
        to = str(edge.get("to") or "")
        kind = str(edge.get("kind") or "forward")
        if frm not in phase_set:
            errors.append(f"{wid}: transition from={frm!r} unknown")
        if to not in phase_set:
            errors.append(f"{wid}: transition to={to!r} unknown")
        if kind == "rework":
            codes = [str(c).strip() for c in (edge.get("reason_codes") or []) if str(c).strip()]
            if not codes:
                errors.append(f"{wid}: rework {frm}->{to} missing reason_codes")

    if entry and entry in phase_set:
        # Side phases (construct/lemma) may only be reachable via rework — require
        # all-edge reachability from entry; forward-only need not cover them.
        reachable = _all_edge_reachable(entry, transitions, phase_set)
        missing = sorted(phase_set - reachable)
        if missing:
            errors.append(f"{wid}: phases unreachable from entry {entry!r}: {missing}")

        # Forward chain should reach at least one terminal.
        forward = _forward_reachable(entry, transitions, phase_set)
        terminals = {str(t) for t in (meta.get("terminal_ready_states") or []) if str(t).strip()}
        if terminals and not (forward & terminals):
            errors.append(
                f"{wid}: no forward path from {entry!r} to any terminal {sorted(terminals)}"
            )

    # Ambiguous rework: same (from, reason_code) → multiple distinct targets.
    by_from_code: dict[tuple[str, str], set[str]] = {}
    for edge in transitions:
        if str(edge.get("kind") or "") != "rework":
            continue
        frm = str(edge.get("from") or "")
        to = str(edge.get("to") or "")
        for code in edge.get("reason_codes") or []:
            c = str(code or "").strip()
            if not c:
                continue
            by_from_code.setdefault((frm, c), set()).add(to)
    for (frm, code), targets in sorted(by_from_code.items()):
        if len(targets) > 1:
            errors.append(
                f"{wid}: ambiguous rework from={frm!r} reason={code!r} targets={sorted(targets)}"
            )

    # Phase/action recovery codes must have a matching rework edge.
    # human_required recoveries stop the machine — no phase edge required.
    meta_block = meta.get("meta") if isinstance(meta.get("meta"), dict) else {}
    recovery = meta_block.get("recovery_by_reason") if isinstance(meta_block, dict) else None
    if isinstance(recovery, dict) and recovery:
        reason_map = _rework_reason_map(transitions)
        for code, spec in recovery.items():
            c = str(code).strip()
            if not c:
                continue
            rtype = ""
            if isinstance(spec, dict):
                rtype = str(spec.get("type") or "").strip().lower()
            if rtype in {"human_required", "abort", "inspect"}:
                continue
            if c not in reason_map:
                errors.append(f"{wid}: recovery_by_reason {c!r} has no rework edge")

    # phase_gates / complete_gates reference known phases / non-empty ids.
    phase_gates = meta.get("phase_gates") if isinstance(meta.get("phase_gates"), dict) else {}
    for ph, gates in phase_gates.items():
        if str(ph) not in phase_set:
            errors.append(f"{wid}: phase_gates key {ph!r} not in phases")
        for g in gates or []:
            if not str(g).strip():
                errors.append(f"{wid}: empty gate under phase_gates[{ph!r}]")

    for g in meta.get("complete_gates") or []:
        if not str(g).strip():
            errors.append(f"{wid}: empty complete_gates entry")

    # Static obligations must map to a settling gate when declared.
    from ascendc_pilot.workflows.specs import STATIC_OBLIGATION_GATE_MAP

    for row in meta.get("static_obligations") or []:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("id") or "").strip()
        if oid and oid not in STATIC_OBLIGATION_GATE_MAP:
            errors.append(f"{wid}: static_obligation {oid!r} missing STATIC_OBLIGATION_GATE_MAP")

    return errors


def check_tg_solve_routing(meta: dict[str, Any] | None = None) -> list[str]:
    """Ensure tg-solve declares the worklog/construct rework reason codes."""
    from ascendc_pilot.workflows import get_workflow

    wf = meta if meta is not None else get_workflow("tg-solve")
    errors: list[str] = []
    reason_map = _rework_reason_map(
        [e for e in (wf.get("transitions") or []) if isinstance(e, dict)]
    )
    for code in TG_SOLVE_REWORK_CODES:
        if code not in reason_map:
            errors.append(f"tg-solve: missing rework reason_code {code!r}")
    # Expected residual targets (contract from audit).
    expected = {
        "REWORK_CONSTRUCT": "construct",
        "OPEN_REMAINING": "construct",
        "OPEN_NONEMPTY": "construct",
        "CASE_REFINABLE": "construct",
    }
    for code, want in expected.items():
        targets = {to for _frm, to in reason_map.get(code, [])}
        if targets and want not in targets:
            errors.append(
                f"tg-solve: {code} should route to {want!r}, got {sorted(targets)}"
            )
    return errors


def check_matrix_coverage(workflows: dict[str, dict[str, Any]] | None = None) -> list[str]:
    from ascendc_pilot.workflows.specs import WORKFLOWS as DEFAULT

    wf_map = workflows if workflows is not None else DEFAULT
    errors: list[str] = []
    for wid in MATRIX_WORKFLOWS:
        meta = wf_map.get(wid)
        if not isinstance(meta, dict):
            errors.append(f"matrix workflow missing: {wid}")
            continue
        if meta.get("reserved") or not meta.get("slash"):
            errors.append(f"matrix workflow {wid} must be a user slash workflow")
    return errors


def check_all_models(workflows: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Run model checker across all user workflows + matrix / tg-solve contracts."""
    from ascendc_pilot.workflows import WORKFLOWS as RUNTIME_WF
    from ascendc_pilot.workflows.specs import WORKFLOWS as SPEC_WF

    # Prefer runtime-normalized registry when caller does not pass a map.
    wf_map = workflows if workflows is not None else RUNTIME_WF
    errors: list[str] = []
    errors.extend(check_matrix_coverage(SPEC_WF if workflows is None else workflows))
    for wid, meta in sorted(wf_map.items()):
        if not isinstance(meta, dict):
            continue
        if meta.get("reserved") or not meta.get("slash"):
            continue
        errors.extend(check_workflow(wid, meta))
    errors.extend(check_tg_solve_routing(wf_map.get("tg-solve") if isinstance(wf_map.get("tg-solve"), dict) else None))
    return errors
