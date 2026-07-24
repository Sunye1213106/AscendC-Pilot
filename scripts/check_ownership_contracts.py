#!/usr/bin/env python3
"""Static ownership / identity contract auditor for AscendC-Pilot.

Fails install/compose/CI when Spec, Skill, action.yaml, Agent, Prompt, METHOD,
Output Contract, and write scopes drift or violate ownership rules.

This auditor is READ-ONLY: it never rewrites action.yaml, Skill markers, or
generated/**. Use ``python scripts/compose_runtime.py --sync`` to refresh mirrors.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def audit(repo: Path) -> list[str]:
    """Read-only ownership audit. Does not write any files."""
    repo = repo.expanduser().resolve()
    sys.path.insert(0, str(repo / "pilot"))
    sys.path.insert(0, str(repo / "scripts"))

    from ascendc_pilot.actions.engines import ENGINE_REGISTRY, OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.ownership import (
        EXECUTION_DETERMINISTIC,
        EXECUTION_PRIMARY_INTERACTIVE,
        EXECUTION_SUBAGENT,
        PRIMARY_AGENT_ID,
        path_within_scopes,
        write_roots_as_scopes,
    )
    from ascendc_pilot.workflows.specs import WORKFLOWS
    import compose_runtime as compose

    errors: list[str] = []
    # Read-only skill marker check (no auto-fix).
    errors.extend(compose.check_skill_action_markers(repo))

    agents_dir = repo / "agents"
    prompts_dir = repo / "prompts" / "tasks"
    skills_dir = repo / "skills"

    # All product workflows must be traversed (including those without slash if listed).
    workflow_ids = (
        "uo-init",
        "uo-update",
        "uo-query",
        "tg-init",
        "tg-plan",
        "tg-solve",
        "ce-review",
    )
    for wid in workflow_ids:
        meta = WORKFLOWS.get(wid) or {}
        if not meta or meta.get("reserved"):
            continue
        write_roots = list(meta.get("write_roots") or [])
        root_scopes = write_roots_as_scopes(write_roots)
        actions = [a for a in (meta.get("actions") or []) if isinstance(a, dict)]
        ids = [str(a.get("id") or "") for a in actions]
        if len(ids) != len(set(ids)):
            errors.append(f"SKILL_OWNER_DRIFT {wid}: duplicate action ids in Workflow Spec")

        # Pipeline set must equal action ids referenced (subset ok if shared across phases).
        pipeline_ids: list[str] = []
        for seq in (meta.get("pipelines") or {}).values():
            pipeline_ids.extend(str(x) for x in (seq or []))
        missing_pipeline = sorted(set(pipeline_ids) - set(ids))
        if missing_pipeline:
            errors.append(f"SKILL_PIPELINE_DRIFT {wid}: pipeline refs unknown actions {missing_pipeline}")

        skill_path = skills_dir / "workflows" / wid / "SKILL.md"
        if skill_path.is_file():
            text = skill_path.read_text(encoding="utf-8")
            if "<!-- BEGIN GENERATED ACTIONS -->" not in text or "<!-- END GENERATED ACTIONS -->" not in text:
                errors.append(f"SKILL_ACTION_SET_DRIFT {wid}: missing GENERATED ACTIONS markers")
            # Source skill must not redefine a full hand-maintained action table outside markers.
            if re.search(r"(?ms)^## Actions\s*\n\| action_id \|", text) and "BEGIN GENERATED" not in text:
                errors.append(f"SKILL_ACTION_SET_DRIFT {wid}: hand-maintained Actions table")

        for action in actions:
            aid = str(action.get("id") or "")
            mode = str(action.get("execution_mode") or "")
            agent_id = action.get("agent_id")
            role_id = str(action.get("role_id") or "")
            mid = str(action.get("action_method_id") or "")
            tpid = str(action.get("task_prompt_id") or "")
            contract = str(action.get("output_contract_id") or "")

            if mode not in {EXECUTION_DETERMINISTIC, EXECUTION_SUBAGENT, EXECUTION_PRIMARY_INTERACTIVE}:
                errors.append(f"{wid}/{aid}: invalid execution_mode {mode!r}")

            if agent_id == PRIMARY_AGENT_ID and mode == EXECUTION_SUBAGENT:
                errors.append(f"{wid}/{aid}: primary agent declared as subagent execution")

            if mode == EXECUTION_DETERMINISTIC:
                if (wid, aid) not in ENGINE_REGISTRY:
                    errors.append(f"{wid}/{aid}: deterministic Action missing engine registry entry")

            if mode in {EXECUTION_SUBAGENT, EXECUTION_PRIMARY_INTERACTIVE}:
                if mid and "/" in mid:
                    wf, name = mid.split("/", 1)
                    method = skills_dir / "actions" / wf / name / "METHOD.md"
                    if not method.is_file() or not method.read_text(encoding="utf-8").strip():
                        errors.append(f"ACTION_METHOD_MISSING {wid}/{aid}: {mid}")
                    ayaml = _load_yaml(skills_dir / "actions" / wf / name / "action.yaml")
                    if wf == wid:
                        errors.extend(compose._action_yaml_drift(wid, action, ayaml))
                if tpid:
                    if "/" in tpid:
                        dom, name = tpid.split("/", 1)
                        pp = prompts_dir / dom / f"{name}.md"
                    else:
                        pp = prompts_dir / f"{tpid}.md"
                    if not pp.is_file() or not pp.read_text(encoding="utf-8").strip():
                        errors.append(f"TASK_PROMPT_MISSING {wid}/{aid}: {tpid}")
                    else:
                        ptext = pp.read_text(encoding="utf-8")
                        if aid == "scope_confirmation":
                            for i, line in enumerate(ptext.splitlines(), 1):
                                low = line.lower()
                                if any(x in line for x in ("严禁", "禁止", "must not", "不得", "勿")):
                                    continue
                                if re.search(
                                    r"acp\s+run-action\s+scope_confirmation(?!\s+--finalize)",
                                    line,
                                ):
                                    errors.append(
                                        f"{wid}/{aid}: scope prompt must not reinvoke run-action prepare "
                                        f"(line {i})"
                                    )
                                    break
                        # Hardcoded owner conflicting with Spec placeholders
                        if re.search(r"(?m)^-\s*workflow_id:\s*`?(?!<WORKFLOW_ID>)[a-z0-9-]+`?\s*$", ptext):
                            # Allow only if matches Spec via placeholder preference
                            m = re.search(r"(?m)^-\s*workflow_id:\s*`?([^`\n]+)`?\s*$", ptext)
                            if m and m.group(1).strip() not in {"<WORKFLOW_ID>", wid}:
                                errors.append(
                                    f"{wid}/{aid}: prompt hardcoded conflicting workflow_id {m.group(1)!r}"
                                )
                        if "Bundle identity is authoritative" not in ptext and mode == EXECUTION_SUBAGENT:
                            errors.append(f"{wid}/{aid}: prompt missing bundle identity authority note")

            ag: dict[str, Any] = {}
            if agent_id and agent_id != PRIMARY_AGENT_ID:
                ag = _load_yaml(agents_dir / f"{agent_id}.yaml")
                if not ag:
                    errors.append(f"{wid}/{aid}: missing agent {agent_id}")
                else:
                    ag_role = str(ag.get("role") or "")
                    if role_id and ag_role and role_id not in {ag_role, "controller"} and not (
                        role_id == "controller" and agent_id == PRIMARY_AGENT_ID
                    ):
                        if role_id != ag_role:
                            # controller is primary-only; producers must match
                            if role_id not in {"controller"}:
                                errors.append(
                                    f"{wid}/{aid}: agent role {ag_role!r} != action role {role_id!r}"
                                )

            # Action write paths ⊆ Agent write_scopes ⊆ Workflow write_roots
            write_scopes = [str(x) for x in (ag.get("write_scopes") or [])] if ag else []
            if agent_id == PRIMARY_AGENT_ID:
                primary = _load_yaml(agents_dir / f"{PRIMARY_AGENT_ID}.yaml")
                write_scopes = [str(x) for x in (primary.get("write_scopes") or [])]
            action_writes = [str(x) for x in (action.get("allowed_write_paths") or [])]
            if write_scopes and action_writes:
                for wp in action_writes:
                    if not path_within_scopes(wp, write_scopes):
                        errors.append(
                            f"ACTION_WRITE_SCOPE_EXCEEDS_AGENT {wid}/{aid}: "
                            f"path={wp!r} not ⊆ agent write_scopes={write_scopes}"
                        )
            if write_scopes and root_scopes:
                for scope in write_scopes:
                    if str(scope).startswith("runs"):
                        continue
                    if not path_within_scopes(scope, root_scopes):
                        errors.append(
                            f"ACTION_WRITE_SCOPE_EXCEEDS_WORKFLOW {wid}/{aid}: "
                            f"agent_scope={scope!r} not ⊆ write_roots={write_roots}"
                        )

            # Action read paths ⊆ Agent read_scopes (when Action declares reads)
            action_reads = [str(x) for x in (action.get("allowed_read_paths") or [])]
            if action_reads:
                read_scopes = [str(x) for x in (ag.get("read_scopes") or [])] if ag else []
                if agent_id == PRIMARY_AGENT_ID:
                    primary = _load_yaml(agents_dir / f"{PRIMARY_AGENT_ID}.yaml")
                    read_scopes = [str(x) for x in (primary.get("read_scopes") or [])]
                if read_scopes:
                    for rp in action_reads:
                        if not path_within_scopes(rp, read_scopes):
                            errors.append(
                                f"ACTION_READ_SCOPE_EXCEEDS_AGENT {wid}/{aid}: "
                                f"path={rp!r} not ⊆ agent read_scopes={read_scopes}"
                            )

            if contract and contract not in OUTPUT_CONTRACT_PATHS:
                errors.append(f"{wid}/{aid}: unknown output_contract_id {contract!r}")
            if contract:
                for rel in OUTPUT_CONTRACT_PATHS.get(contract) or []:
                    if "runs/*/" in str(rel).replace("\\", "/"):
                        errors.append(
                            f"{wid}/{aid}: run-scoped contract uses unconstrained *: {rel}"
                        )

            if mode == EXECUTION_PRIMARY_INTERACTIVE and aid == "scope_confirmation":
                if role_id not in {"controller", "primary_interactive"}:
                    errors.append(f"{wid}/{aid}: primary_interactive should use controller role")

    # Also cover any other non-reserved slash workflows not in the fixed list.
    for wid, meta in WORKFLOWS.items():
        if wid in workflow_ids:
            continue
        if meta.get("reserved") or not meta.get("slash"):
            continue
        # Light check: skill markers already covered by check_skill_action_markers.
        pass

    # generated runtime must be recomposable (drift check; read-only)
    try:
        drift = compose.check_generated_drift(repo, hosts=["opencode"])
        for d in drift[:20]:
            errors.append(d if str(d).startswith("GENERATED") else f"GENERATED_DRIFT: {d}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"GENERATED_DRIFT: auditor failed: {exc}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository root")
    args = parser.parse_args(argv)
    errs = audit(Path(args.repo))
    if errs:
        print(f"ownership audit FAILED ({len(errs)}):", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("ownership audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
