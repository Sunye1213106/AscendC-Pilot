#!/usr/bin/env python3
"""Prune generated host context to assets a model can actually execute.

Deterministic Actions are engine calls, not model-selectable agents. Keep only
agents/prompts reachable from non-deterministic workflow actions (including
mode-overlay variants), and make generated Skill tables display deterministic
owners as ``engine`` rather than a Host-spawnable agent.
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
        if not isinstance(meta, dict) or meta.get("alias_of"):
            continue
        # Slash user workflows, plus reserved Harness workflows that still have LLM Actions.
        if (meta.get("reserved") or not meta.get("slash")) and not (meta.get("actions") or []):
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
    """Render deterministic Actions as internal engine-owned, never Task actors."""
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
            text = re.sub(
                rf"(?m)^(\|\s*`{aid}`\s*\|\s*`deterministic`\s*\|\s*)`[^`]+`(\s*\|)",
                r"\1`engine`\2",
                text,
            )
            text = re.sub(
                rf"(?m)^(\|\s*`{aid}`\s*\|[^\n]*\|\s*)`[^`]+`\s*\|$",
                r"\1`engine` |",
                text,
            )
        if text != original:
            skill.write_text(text, encoding="utf-8")
            changed.append(skill.relative_to(skills_dir).as_posix())
    return changed


def prune(
    repo: Path,
    host: str,
    *,
    generated_root: Path | None = None,
) -> dict[str, Any]:
    """Prune one generated host runtime.

    ``generated_root`` is the host runtime root itself (the directory containing
    ``skills/``, ``agents/`` and ``prompts/``).  It defaults to the committed
    ``generated/<host>`` tree, but an explicit root lets drift checks prune a
    temporary compose with exactly the same pipeline used by installers/CI.
    """
    repo = repo.expanduser().resolve()
    pilot = repo / "pilot"
    if str(pilot) not in sys.path:
        sys.path.insert(0, str(pilot))

    from ascendc_pilot.workflows import WORKFLOWS

    agent_ids, prompt_ids = referenced_runtime_assets(WORKFLOWS)
    generated = (
        Path(generated_root).expanduser().resolve()
        if generated_root is not None
        else repo / "generated" / host
    )
    skills_dir = generated / "skills"
    agents_dir = generated / "agents"
    prompts_dir = generated / "prompts"
    removed_agents: list[str] = []
    removed_prompts: list[str] = []

    engine_ids: set[str] = set()
    agents_src = repo / "agents"
    if agents_src.is_dir():
        try:
            import yaml  # type: ignore
        except ImportError:
            yaml = None  # type: ignore
        if yaml is not None:
            for ag in agents_src.glob("*.yaml"):
                data = yaml.safe_load(ag.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict) and str(data.get("kind") or "").strip() == "deterministic_engine":
                    engine_ids.add(str(data.get("id") or ag.stem))

    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            if path.stem not in agent_ids or path.stem in engine_ids:
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
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from install_manifest import write_install_manifest

    manifest_path = write_install_manifest(generated, host)
    return {
        "ok": not missing_agents and not missing_prompts,
        "host": host,
        "generated_root": generated.as_posix(),
        "kept_agents": sorted(agent_ids),
        "kept_prompts": sorted(prompt_ids),
        "removed_agents": removed_agents,
        "removed_prompts": removed_prompts,
        "rewritten_skills": rewritten_skills,
        "missing_agents": missing_agents,
        "missing_prompts": missing_prompts,
        "install_manifest": manifest_path.as_posix(),
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
