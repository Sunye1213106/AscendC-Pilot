#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static integrity check: Workflow ↔ Agent ↔ Prompt ↔ Contract ↔ Engine graph.

Fails when production forward references are missing, unused, or deprecated
prompts remain under prompts/tasks/.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PILOT = REPO / "pilot"
sys.path.insert(0, str(PILOT))

FORBIDDEN_PROD_MARKERS = re.compile(
    r"(?i)\b(deprecated|RESERVED\s*—\s*deprecated|codebase-memory|codebasememory|"
    r"stage_cbm_scope|cbm_scope|cbm_db)\b"
)
CBM_ALLOW = ("docs/history/",)


def _main() -> int:
    from ascendc_pilot.actions.engines import ENGINE_REGISTRY, OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.workflows import WORKFLOWS

    errors: list[str] = []
    agents_dir = REPO / "agents"
    prompts_dir = REPO / "prompts" / "tasks"
    skills_dir = REPO / "skills"

    used_agents: set[str] = set()
    used_prompts: set[str] = set()
    used_contracts: set[str] = set()
    used_engine_actions: set[tuple[str, str]] = set()

    for wf_id, meta in WORKFLOWS.items():
        if not isinstance(meta, dict):
            continue
        for row in meta.get("agents") or []:
            if isinstance(row, dict) and row.get("id"):
                aid = str(row["id"])
                used_agents.add(aid)
                if not (agents_dir / f"{aid}.yaml").is_file():
                    errors.append(f"workflow {wf_id}: missing agents/{aid}.yaml")
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = str(action.get("id") or "")
            agent_id = str(action.get("agent_id") or "").strip()
            if agent_id:
                used_agents.add(agent_id)
                if not (agents_dir / f"{agent_id}.yaml").is_file():
                    errors.append(
                        f"workflow {wf_id} action {aid}: missing agents/{agent_id}.yaml"
                    )
            tpid = action.get("task_prompt_id")
            if tpid:
                tpid_s = str(tpid)
                used_prompts.add(tpid_s)
                if "/" not in tpid_s:
                    errors.append(
                        f"workflow {wf_id} action {aid}: bad task_prompt_id {tpid_s!r}"
                    )
                else:
                    dom, name = tpid_s.split("/", 1)
                    pp = prompts_dir / dom / f"{name}.md"
                    if not pp.is_file():
                        errors.append(
                            f"workflow {wf_id} action {aid}: missing prompt {pp.relative_to(REPO)}"
                        )
            ocid = action.get("output_contract_id")
            if ocid:
                ocid_s = str(ocid)
                used_contracts.add(ocid_s)
                if ocid_s not in OUTPUT_CONTRACT_PATHS:
                    errors.append(
                        f"workflow {wf_id} action {aid}: unknown output_contract_id {ocid_s}"
                    )
            mode = str(action.get("execution_mode") or "")
            if mode == "deterministic" or agent_id in {
                "deterministic-uo-engine",
                "deterministic-tg-engine",
            }:
                key = (wf_id, aid)
                used_engine_actions.add(key)
                if key not in ENGINE_REGISTRY and aid not in {
                    "diff_only",  # alias handled separately sometimes
                    "human_confirm",
                    "plan_approve",
                    "init_audit",
                    "lemma_verify",
                }:
                    # human/interactive may not be engines; only require registered if deterministic engine agent
                    if agent_id.startswith("deterministic-"):
                        if key not in ENGINE_REGISTRY:
                            errors.append(
                                f"workflow {wf_id} action {aid}: missing ENGINE_REGISTRY entry"
                            )

    # Production prompts must not be deprecated / contain CBM markers
    if prompts_dir.is_dir():
        for md in prompts_dir.rglob("*.md"):
            body = md.read_text(encoding="utf-8", errors="replace")
            if FORBIDDEN_PROD_MARKERS.search(body):
                errors.append(f"production prompt has forbidden marker: {md.relative_to(REPO)}")

    # Unused production prompts are warnings; forward refs above are authoritative.
    unused_prompts: list[str] = []
    if prompts_dir.is_dir():
        for md in prompts_dir.rglob("*.md"):
            rel = md.relative_to(prompts_dir).as_posix()
            if not rel.endswith(".md"):
                continue
            tid = rel[:-3]
            if tid not in used_prompts:
                unused_prompts.append(tid)
    for tid in unused_prompts:
        print(f"  warn: unused production prompt prompts/tasks/{tid}.md")

    # Agents: every production agent yaml must be used (allow primary + known)
    agent_allow = {"ascendc-pilot"}
    if agents_dir.is_dir():
        for yml in agents_dir.glob("*.yaml"):
            aid = yml.stem
            if aid not in used_agents and aid not in agent_allow:
                errors.append(f"unused production agent: agents/{aid}.yaml")

    # Skill refs from agents (skills: list)
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml and agents_dir.is_dir():
        for yml in agents_dir.glob("*.yaml"):
            meta = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
            for sk in meta.get("skills") or []:
                sk_s = str(sk).strip()
                if not sk_s:
                    continue
                if not (skills_dir / sk_s / "SKILL.md").is_file():
                    errors.append(f"agent {yml.stem}: missing skill {sk_s}")

    # CBM hygiene in production trees (not docs/history)
    cbm_re = re.compile(
        r"(?i)(codebase-memory|codebasememory|stage_cbm_scope|cbm_scope|cbm_db)"
    )
    scan_roots = [
        REPO / "pilot",
        REPO / "engines",
        REPO / "agents",
        REPO / "prompts",
        REPO / "skills",
        REPO / "scripts",
    ]
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".ts", ".sh", ".ps1"}:
                continue
            rel = path.relative_to(REPO).as_posix()
            if any(rel.startswith(a) for a in CBM_ALLOW):
                continue
            if "_pytest_tmp" in rel or "/tests/" in f"/{rel}" or rel.startswith("evals/"):
                continue
            if path.name == "check_runtime_graph.py":
                continue
            # Deny-lists that mention CBM to block it are allowed.
            if rel.replace("\\", "/").endswith("authorize/__init__.py"):
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if cbm_re.search(body):
                errors.append(f"CBM marker in production path: {rel}")

    if errors:
        print(f"check_runtime_graph: {len(errors)} issue(s)")
        for e in errors[:80]:
            print(f"  - {e}")
        if len(errors) > 80:
            print(f"  ... and {len(errors) - 80} more")
        return 1
    print("check_runtime_graph: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
