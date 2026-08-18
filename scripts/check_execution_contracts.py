#!/usr/bin/env python3
"""Audit Workflow -> execution actor -> Host-visible prompt contracts.

This check covers semantics that ordinary reference/scope linters cannot see:
deterministic Actions need a deterministic engine identity, LLM Actions need a
Host-spawnable agent, Primary interactive Actions belong to the controller, and
Task prompts must stay Host-neutral and fully renderable by Action Runtime.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
PHYSICAL_COGNITIVE_PATH = re.compile(
    r"(?<![A-Za-z0-9_-])skills/(operator-analysis|testcase-generation|source-proof|code-review|code-engineering)/",
    re.I,
)
TEMPLATE_TOKEN = re.compile(r"<([A-Z][A-Z0-9_]{2,})>")
_CAP_LIST_RE = re.compile(
    r"\((?:\s*`([a-z][a-z0-9-]*)`\s*,\s*)+`([a-z][a-z0-9-]*)`\s*\)"
)
RUNTIME_PROMPT_TOKENS = {
    "RUN_ID",
    "ACTION_ID",
    "WORKFLOW_ID",
    "ACTOR_ID",
    "TARGET_IDS_OR_FILES",
    "TARGET",
    "SHARD_ID",
    "OP_NAME",
    "PROJECT_ROOT",
    "UO_ROOT",
    "TG_ROOT",
    "TOPIC",
    "CONTEXT_PACK_PATH",
    "ARCHITECTURE",
    "ROLE_ID",
    "LEASE_ID",
    "ACTION_SESSION_ID",
    "CANDIDATES_SHA256",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _prompt_path(repo: Path, prompt_id: str) -> Path:
    root = repo / "prompts" / "tasks"
    if "/" in prompt_id:
        domain, name = prompt_id.split("/", 1)
        return root / domain / f"{name}.md"
    return root / f"{prompt_id}.md"


def check_prompt_capability_drift(repo: Path) -> list[str]:
    """Fail when a task prompt hardcodes a capability list that ≠ Action Spec."""
    sys.path.insert(0, str(repo / "pilot"))
    sys.path.insert(0, str(repo / "scripts"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    import compose_runtime as compose

    known_caps = set(compose.CAPABILITY_DIRS)
    # task_prompt_id -> expected capability_ids (first writer wins; warn on conflict)
    expected: dict[str, list[str]] = {}
    owners: dict[str, str] = {}
    errors: list[str] = []
    for wid, wf in WORKFLOWS.items():
        if wf.get("reserved") or wf.get("alias_of"):
            continue
        for action in wf.get("actions") or []:
            tpid = action.get("task_prompt_id")
            if not tpid:
                continue
            caps = list(action.get("capability_ids") or [])
            key = str(tpid)
            if key in expected and expected[key] != caps:
                errors.append(
                    f"prompt-cap-drift: task_prompt_id {key!r} used by "
                    f"{owners[key]} and {wid}/{action.get('id')} with different capability_ids"
                )
                continue
            expected[key] = caps
            owners[key] = f"{wid}/{action.get('id')}"

    tasks_root = repo / "prompts" / "tasks"
    if not tasks_root.is_dir():
        return errors

    for path in sorted(tasks_root.rglob("*.md")):
        rel = path.relative_to(tasks_root).as_posix()
        tpid = rel[:-3] if rel.endswith(".md") else rel
        text = path.read_text(encoding="utf-8")
        for match in _CAP_LIST_RE.finditer(text):
            # Re-parse span: repeating groups only keep the last capture.
            listed = re.findall(r"`([a-z][a-z0-9-]*)`", match.group(0))
            if not listed or not all(cid in known_caps for cid in listed):
                continue
            want = expected.get(tpid)
            if want is None:
                errors.append(
                    f"prompt-cap-drift: {path.as_posix()} hardcodes capabilities "
                    f"{listed} but no Action owns task_prompt_id={tpid!r}"
                )
                continue
            if set(listed) != set(want):
                errors.append(
                    f"prompt-cap-drift: {path.as_posix()} hardcodes {listed} "
                    f"but Action {owners.get(tpid)} expects {want}"
                )
    return errors

def audit(repo: Path = REPO) -> list[str]:
    repo = Path(repo).resolve()
    pilot = repo / "pilot"
    if str(pilot) not in sys.path:
        sys.path.insert(0, str(pilot))

    from ascendc_pilot.workflows import WORKFLOWS

    errors: list[str] = []
    agents_dir = repo / "agents"
    agents = {
        path.stem: _load_yaml(path)
        for path in agents_dir.glob("*.yaml")
        if path.is_file()
    }

    primary = agents.get("ascendc-pilot") or {}
    if str(primary.get("role") or "") != "controller":
        errors.append("PRIMARY_ROLE_DRIFT: agents/ascendc-pilot.yaml must use role=controller")
    if str(primary.get("mode") or "") != "primary":
        errors.append("PRIMARY_MODE_DRIFT: ascendc-pilot must be mode=primary")

    for workflow_id, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        actions = {
            str(row.get("id") or ""): row
            for row in (meta.get("actions") or [])
            if isinstance(row, dict) and row.get("id")
        }
        for phase, pipeline in (meta.get("pipelines") or {}).items():
            for action_id in pipeline or []:
                if str(action_id) not in actions:
                    errors.append(
                        f"PIPELINE_ACTION_MISSING {workflow_id}/{phase}: {action_id}"
                    )

        for action_id, action in actions.items():
            mode = str(action.get("execution_mode") or "")
            role = str(action.get("role_id") or "")
            actor = str(action.get("agent_id") or "").strip()
            actors = [str(x) for x in (action.get("actors") or []) if str(x).strip()]
            prompt_id = str(action.get("task_prompt_id") or "").strip()

            if actor and actors != [actor]:
                errors.append(
                    f"ACTOR_LIST_DRIFT {workflow_id}/{action_id}: agent_id={actor!r} actors={actors!r}"
                )

            if mode == "deterministic" or role == "deterministic_engine":
                if not actor:
                    errors.append(f"DETERMINISTIC_ACTOR_MISSING {workflow_id}/{action_id}")
                    continue
                agent = agents.get(actor) or {}
                if not agent:
                    errors.append(
                        f"DETERMINISTIC_AGENT_MISSING {workflow_id}/{action_id}: {actor}"
                    )
                elif str(agent.get("kind") or "") != "deterministic_engine":
                    errors.append(
                        f"DETERMINISTIC_AGENT_KIND {workflow_id}/{action_id}: {actor} is not deterministic_engine"
                    )
                if prompt_id:
                    errors.append(
                        f"DETERMINISTIC_PROMPT_LEAK {workflow_id}/{action_id}: {prompt_id}"
                    )
                continue

            if mode == "subagent":
                if not actor:
                    errors.append(f"SUBAGENT_ACTOR_MISSING {workflow_id}/{action_id}")
                else:
                    agent = agents.get(actor) or {}
                    if not agent:
                        errors.append(
                            f"SUBAGENT_AGENT_MISSING {workflow_id}/{action_id}: {actor}"
                        )
                    elif str(agent.get("kind") or "") == "deterministic_engine":
                        errors.append(
                            f"SUBAGENT_IS_ENGINE {workflow_id}/{action_id}: {actor}"
                        )
                if not prompt_id:
                    errors.append(f"SUBAGENT_PROMPT_MISSING {workflow_id}/{action_id}")

            if mode == "primary_interactive":
                if actor != "ascendc-pilot" or role != "controller":
                    errors.append(
                        f"PRIMARY_INTERACTIVE_OWNER {workflow_id}/{action_id}: actor={actor!r} role={role!r}"
                    )

            if prompt_id:
                prompt = _prompt_path(repo, prompt_id)
                if not prompt.is_file():
                    errors.append(
                        f"TASK_PROMPT_MISSING {workflow_id}/{action_id}: {prompt_id}"
                    )
                else:
                    body = prompt.read_text(encoding="utf-8")
                    match = PHYSICAL_COGNITIVE_PATH.search(body)
                    if match:
                        errors.append(
                            f"HOST_SPECIFIC_SKILL_PATH {prompt.relative_to(repo).as_posix()}: "
                            f"use logical skill id {match.group(1)!r}, not skills/{match.group(1)}/..."
                        )
                    unknown_tokens = sorted(set(TEMPLATE_TOKEN.findall(body)) - RUNTIME_PROMPT_TOKENS)
                    if unknown_tokens:
                        errors.append(
                            f"UNRENDERABLE_PROMPT_TOKEN {workflow_id}/{action_id}: {unknown_tokens} "
                            f"in {prompt.relative_to(repo).as_posix()}"
                        )

    # End-to-end control-plane invariants for the supported operator flow.
    required = (
        "uo-init",
        "tg-init",
        "tg-plan",
        "tg-solve",
        "ce-review",
        "ce-plan",
        "ce-apply",
        "handoff",
    )
    for workflow_id in required:
        if workflow_id not in WORKFLOWS:
            errors.append(f"FLOW_WORKFLOW_MISSING: {workflow_id}")

    for workflow_id in ("uo-init", "uo-update"):
        for action in (WORKFLOWS.get(workflow_id) or {}).get("actions") or []:
            if str(action.get("execution_mode") or "") == "deterministic" and str(
                action.get("agent_id") or ""
            ) != "deterministic-uo-engine":
                errors.append(
                    f"UO_ENGINE_BINDING {workflow_id}/{action.get('id')}: {action.get('agent_id')!r}"
                )

    for workflow_id in ("tg-init", "tg-plan", "tg-solve"):
        for action in (WORKFLOWS.get(workflow_id) or {}).get("actions") or []:
            if str(action.get("execution_mode") or "") == "deterministic" and str(
                action.get("agent_id") or ""
            ) != "deterministic-tg-engine":
                errors.append(
                    f"TG_ENGINE_BINDING {workflow_id}/{action.get('id')}: {action.get('agent_id')!r}"
                )

    ce_actions = {
        str(a.get("id") or ""): a
        for a in (WORKFLOWS.get("ce-review") or {}).get("actions") or []
        if isinstance(a, dict)
    }
    ce_review = ce_actions.get("code_review") or {}
    if (
        str(ce_review.get("execution_mode") or "") != "subagent"
        or str(ce_review.get("agent_id") or "") != "ce-reviewer"
    ):
        errors.append("CE_EXECUTION_BINDING: ce-review/code_review must dispatch ce-reviewer")

    errors.extend(check_prompt_capability_drift(repo))
    return errors


def main() -> int:
    errors = audit(REPO)
    if errors:
        print(f"execution contract audit FAILED ({len(errors)}):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("execution contract audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
