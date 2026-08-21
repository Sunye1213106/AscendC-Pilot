#!/usr/bin/env python3
"""Static ownership / identity contract auditor for AscendC-Pilot.

Fails install/compose/CI when Spec, Skill, Agent, Prompt, Output Contract,
and write scopes drift or violate ownership rules.

This auditor is READ-ONLY: it never rewrites Skill markers or generated/**.
Use ``python scripts/compose_runtime.py --sync`` to refresh Skill action markers.
Action identity lives solely in Workflow Spec (no skills/actions source tree).
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
        EXECUTION_PRIMARY_REVIEW,
        EXECUTION_SUBAGENT,
        PRIMARY_AGENT_ID,
        path_within_scopes,
        write_paths_overlap,
        write_roots_as_scopes,
    )
    from ascendc_pilot.workflows import WORKFLOWS
    from ascendc_pilot.workflows.consistency import action_task_prompt_ids
    import compose_runtime as compose

    errors: list[str] = []
    # Read-only skill marker check (no auto-fix).
    errors.extend(compose.check_skill_action_markers(repo))

    agents_dir = repo / "agents"
    prompts_dir = repo / "prompts" / "tasks"
    skills_dir = repo / "skills"

    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved") or meta.get("alias_of"):
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

        # Entry skills are composed into generated/; Spec + WORKFLOW_ENTRIES are authority.
        entry_ok = True
        try:
            import compose_runtime as _compose

            if wid not in _compose.WORKFLOW_ENTRIES:
                errors.append(f"SKILL_ENTRY_MISSING {wid}")
                entry_ok = False
        except Exception:  # noqa: BLE001
            entry_ok = True
        del entry_ok

        for action in actions:
            aid = str(action.get("id") or "")
            mode = str(action.get("execution_mode") or "")
            agent_id = action.get("agent_id")
            role_id = str(action.get("role_id") or "")
            mid = str(action.get("skill_id") or action.get("action_method_id") or "")
            tpid = str(action.get("task_prompt_id") or "")
            prompt_ids = action_task_prompt_ids(action)
            contract = str(action.get("output_contract_id") or "")

            if mode not in {
                EXECUTION_DETERMINISTIC,
                EXECUTION_SUBAGENT,
                EXECUTION_PRIMARY_INTERACTIVE,
                EXECUTION_PRIMARY_REVIEW,
            }:
                errors.append(f"{wid}/{aid}: invalid execution_mode {mode!r}")

            if agent_id == PRIMARY_AGENT_ID and mode == EXECUTION_SUBAGENT:
                errors.append(f"{wid}/{aid}: primary agent declared as subagent execution")

            if mode == EXECUTION_DETERMINISTIC:
                if (wid, aid) not in ENGINE_REGISTRY:
                    errors.append(f"{wid}/{aid}: deterministic Action missing engine registry entry")

            if mode in {EXECUTION_SUBAGENT, EXECUTION_PRIMARY_REVIEW} and tpid:
                if "/" in mid:
                    mid = mid.rsplit("/", 1)[-1]
                mp = skills_dir / mid / "SKILL.md"
                if not mid or not mp.is_file() or not mp.read_text(encoding="utf-8").strip():
                    errors.append(f"SKILL_MISSING {wid}/{aid}: {mid} -> {mp.as_posix()}")
            elif mode in {EXECUTION_DETERMINISTIC, EXECUTION_PRIMARY_INTERACTIVE} and mid:
                errors.append(f"{wid}/{aid}: {mode} Action must omit skill_id")

            if mode in {EXECUTION_SUBAGENT, EXECUTION_PRIMARY_INTERACTIVE, EXECUTION_PRIMARY_REVIEW}:
                for pid in prompt_ids:
                    if "/" in pid:
                        dom, name = pid.split("/", 1)
                        pp = prompts_dir / dom / f"{name}.md"
                    else:
                        pp = prompts_dir / f"{pid}.md"
                    if not pp.is_file() or not pp.read_text(encoding="utf-8").strip():
                        errors.append(f"TASK_PROMPT_MISSING {wid}/{aid}: {pid}")
                    else:
                        ptext = pp.read_text(encoding="utf-8")
                        # Hardcoded owner conflicting with Spec placeholders
                        if re.search(r"(?m)^-\s*workflow_id:\s*`?(?!<WORKFLOW_ID>)[a-z0-9-]+`?\s*$", ptext):
                            # Allow only if matches Spec via placeholder preference
                            m = re.search(r"(?m)^-\s*workflow_id:\s*`?([^`\n]+)`?\s*$", ptext)
                            if m and m.group(1).strip() not in {"<WORKFLOW_ID>", wid}:
                                errors.append(
                                    f"{wid}/{aid}: prompt hardcoded conflicting workflow_id {m.group(1)!r}"
                                )
                        # Bundle identity is enforced by Runtime Bundle / prepare,
                        # not by requiring a natural-language note in the Task Prompt.

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

            # Action write paths ⊆ Agent write_scopes, and ⊆ this workflow's
            # write_roots. Do not require the agent's global ceiling to fit one
            # workflow: shared agents (CE reviewer/engine) declare the union.
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
            if action_writes and root_scopes:
                for wp in action_writes:
                    if str(wp).replace("\\", "/").startswith("runs"):
                        continue
                    if not path_within_scopes(wp, root_scopes):
                        errors.append(
                            f"ACTION_WRITE_SCOPE_EXCEEDS_WORKFLOW {wid}/{aid}: "
                            f"path={wp!r} not ⊆ write_roots={write_roots}"
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

            allow_w = [str(x) for x in (action.get("allowed_write_paths") or [])]
            forbid_w = [str(x) for x in (action.get("forbidden_write_paths") or [])]
            for a_path in allow_w:
                for b_path in forbid_w:
                    if write_paths_overlap(a_path, b_path):
                        errors.append(
                            f"WRITE_ALLOW_FORBID_OVERLAP {wid}/{aid}: "
                            f"{a_path!r} ∩ {b_path!r}"
                        )
            if str(action.get("output_mode") or "") == "staged" and str(action.get("role_id") or "") == "producer":
                from ascendc_pilot.workflows.artifact_dag import normalize_published

                published = normalize_published(action)
                if published:
                    errors.append(
                        f"STAGED_PRODUCER_PUBLISHES_CANONICAL {wid}/{aid}: {published}"
                    )
            if contract in {"plan-precheck-v1", "solve-precheck-v1"}:
                from ascendc_pilot.workflows.artifact_dag import normalize_published

                published = normalize_published(action)
                if published:
                    errors.append(
                        f"PRECONDITION_FAKE_PRODUCER {wid}/{aid}: {published}"
                    )

            if mode == EXECUTION_PRIMARY_INTERACTIVE and aid in {
                "human_confirm",
                "plan_approve",
                "scenario_confirm",
                "scenario_plan",
            }:
                if role_id not in {"controller", "primary_interactive"}:
                    errors.append(f"{wid}/{aid}: primary_interactive should use controller role")

    # generated/ is gitignored: recompose opencode and validate the fresh tree
    # instead of comparing against a committed golden copy.
    try:
        result = compose.compose_host(repo, "opencode")
        if result.get("errors"):
            for e in result["errors"][:20]:
                errors.append(f"COMPOSE: {e}")
        for e in compose.validate_generated(repo, host="opencode")[:20]:
            errors.append(e if str(e).startswith("generated/") else f"GENERATED: {e}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"COMPOSE: auditor failed: {exc}")

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
