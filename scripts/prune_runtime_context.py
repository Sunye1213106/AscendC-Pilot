#!/usr/bin/env python3
"""Prune generated host context to assets a model can actually execute.

Deterministic Actions are engine calls, not model-selectable agents. Keep only
agents/prompts reachable from non-deterministic workflow actions (including
mode-overlay variants), and make generated Skill tables display deterministic
owners as ``engine`` rather than ``human``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterable


def _merged_action(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    if "agent_id" in patch or "role_id" in patch:
        try:
            from ascendc_pilot.ownership import infer_execution_mode

            out["execution_mode"] = infer_execution_mode(
                agent_id=str(out.get("agent_id") or "") or None,
                role_id=str(out.get("role_id") or "") or None,
                execution_mode=None,
            )
        except Exception:
            pass
    return out


def _action_variants(meta: dict[str, Any]) -> Iterable[dict[str, Any]]:
    base = {
        str(row.get("id") or ""): row
        for row in (meta.get("actions") or [])
        if isinstance(row, dict) and row.get("id")
    }
    yield from base.values()
    overlays = meta.get("mode_overlays")
    if not isinstance(overlays, dict):
        return
    for overlay in overlays.values():
        if not isinstance(overlay, dict):
            continue
        overrides = overlay.get("action_overrides")
        if not isinstance(overrides, dict):
            continue
        for action_id, patch in overrides.items():
            row = base.get(str(action_id))
            if row is None or not isinstance(patch, dict):
                continue
            yield _merged_action(row, patch)


def referenced_runtime_assets(workflows: dict[str, dict[str, Any]]) -> tuple[set[str], set[str]]:
    agents: set[str] = set()
    prompts: set[str] = set()
    for meta in workflows.values():
        if not isinstance(meta, dict) or meta.get("reserved") or not meta.get("slash"):
            continue
        for action in _action_variants(meta):
            if str(action.get("execution_mode") or "") == "deterministic":
                continue
            agent_id = str(action.get("agent_id") or "").strip()
            if agent_id:
                agents.add(agent_id)
            prompt_id = str(action.get("task_prompt_id") or "").strip()
            if prompt_id:
                prompts.add(prompt_id)
    return agents, prompts


def _prompt_path(root: Path, prompt_id: str) -> Path:
    if "/" in prompt_id:
        domain, name = prompt_id.split("/", 1)
        return root / "tasks" / domain / f"{name}.md"
    return root / "tasks" / f"{prompt_id}.md"


def _rewrite_deterministic_skill_owners(
    skills_dir: Path,
    workflows: dict[str, dict[str, Any]],
) -> list[str]:
    """Render deterministic Actions as engine-owned, never human/agent-owned."""
    changed: list[str] = []
    for workflow_id, meta in workflows.items():
        if not isinstance(meta, dict) or meta.get("reserved") or not meta.get("slash"):
            continue
        deterministic = {
            str(action.get("id") or "")
            for action in meta.get("actions") or []
            if isinstance(action, dict)
            and str(action.get("execution_mode") or "") == "deterministic"
        }
        if not deterministic:
            continue
        skill = skills_dir / workflow_id / "SKILL.md"
        if not skill.is_file():
            continue
        text = skill.read_text(encoding="utf-8")
        original = text
        for action_id in sorted(deterministic):
            aid = re.escape(action_id)
            # Generated Actions table: execution_mode | agent | role.
            text = re.sub(
                rf"(?m)^(\|\s*`{aid}`\s*\|\s*`deterministic`\s*\|\s*)`human`(\s*\|)",
                r"\1`engine`\2",
                text,
            )
            # Composition index ends with the agent column.
            text = re.sub(
                rf"(?m)^(\|\s*`{aid}`\s*\|[^\n]*\|\s*)`human`\s*\|$",
                r"\1`engine` |",
                text,
            )
        if text != original:
            skill.write_text(text, encoding="utf-8")
            changed.append(skill.relative_to(skills_dir).as_posix())
    return changed


def prune(repo: Path, host: str) -> dict[str, Any]:
    repo = repo.expanduser().resolve()
    pilot = repo / "pilot"
    if str(pilot) not in sys.path:
        sys.path.insert(0, str(pilot))

    from ascendc_pilot.workflows import WORKFLOWS

    agent_ids, prompt_ids = referenced_runtime_assets(WORKFLOWS)
    generated = repo / "generated" / host
    skills_dir = generated / "skills"
    agents_dir = generated / "agents"
    prompts_dir = generated / "prompts"
    removed_agents: list[str] = []
    removed_prompts: list[str] = []

    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            if path.stem not in agent_ids:
                path.unlink()
                removed_agents.append(path.name)

    keep_prompt_paths = {_prompt_path(prompts_dir, prompt_id).resolve() for prompt_id in prompt_ids}
    if prompts_dir.is_dir():
        for path in sorted(prompts_dir.rglob("*"), reverse=True):
            if path.is_file() and path.resolve() not in keep_prompt_paths:
                removed_prompts.append(path.relative_to(prompts_dir).as_posix())
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass

    rewritten_skills = _rewrite_deterministic_skill_owners(skills_dir, WORKFLOWS)
    missing_agents = sorted(
        agent_id for agent_id in agent_ids if not (agents_dir / f"{agent_id}.md").is_file()
    )
    missing_prompts = sorted(
        prompt_id for prompt_id in prompt_ids if not _prompt_path(prompts_dir, prompt_id).is_file()
    )
    return {
        "ok": not missing_agents and not missing_prompts,
        "host": host,
        "kept_agents": sorted(agent_ids),
        "kept_prompts": sorted(prompt_ids),
        "removed_agents": removed_agents,
        "removed_prompts": removed_prompts,
        "rewritten_skills": rewritten_skills,
        "missing_agents": missing_agents,
        "missing_prompts": missing_prompts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune generated runtime context")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--host", action="append", default=[])
    args = parser.parse_args(argv)
    hosts = args.host or ["opencode", "cursor", "codex"]
    results = [prune(args.repo, host) for host in hosts]
    print({"ok": all(row["ok"] for row in results), "results": results})
    return 0 if all(row["ok"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
