from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


CHECK_FILES = (
    "understand_operator/_operator/evidence.py",
    "understand_operator/_operator/yaml_gate.py",
    "understand_operator/_operator/install_check.py",
    "understand_operator/_operator/kb_compiler.py",
    "understand_operator/scripts/quality_gate.py",
    "understand_operator/scripts/verify_subagent_barrier.py",
    "understand_operator/scripts/verify_required_subagents.py",
    "understand_operator/scripts/prepare_fact_file.py",
    "understand_operator/scripts/merge_fact_entries.py",
    "understand_operator/scripts/prepare_operator.py",
    "agents/uo-boundary-agent.md",
    "agents/uo-host-extraction.md",
    "agents/uo-flow-extraction.md",
    "agents/uo-kernel-overview-agent.md",
    "agents/uo-kernel-slice-planner.md",
    "agents/uo-kernel-slice-agent.md",
    "agents/uo-step2-fact-review-agent.md",
    "agents/uo-step3-fact-review-agent.md",
    "agents/uo-behavior-abstraction-agent.md",
    "prompts/00_subagent_dispatch.md",
    "prompts/common/10_tool_execution_rules.md",
    "prompts/common/11_phase1_boundary_yaml_authoring.md",
    "skills/understand-operator/quality_gate.py",
    "skills/understand-operator/prepare_operator.py",
    "skills/understand-operator/verify_subagent_barrier.py",
    "skills/understand-operator/verify_required_subagents.py",
    "skills/understand-operator/prepare_fact_file.py",
    "skills/understand-operator/merge_fact_entries.py",
    "skills/understand-operator/SKILL.md",
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() and path.is_file() else ""


def compare_installed_skill(repo_plugin_root: Path, installed_skill_root: Path) -> dict[str, Any]:
    installed_skill_link = installed_skill_root
    installed_plugin_link = installed_skill_link.parent.parent / "understand-operator-plugin"
    repo_plugin_root = repo_plugin_root.resolve()
    installed_skill_root = installed_skill_link.resolve()
    installed_plugin_root = installed_plugin_link.resolve()
    if repo_plugin_root == installed_plugin_root:
        return {
            "version": 1,
            "repo_plugin_root": str(repo_plugin_root),
            "installed_skill_root": str(installed_skill_root),
            "installed_plugin_root": str(installed_plugin_root),
            "same_resolved_plugin_root": True,
            "consistent": True,
            "error_code": "",
            "mismatches": [],
        }
    mismatches: list[dict[str, str]] = []
    for rel in CHECK_FILES:
        repo_path = repo_plugin_root / rel
        installed_path = installed_plugin_root / rel if rel.startswith(("prompts/", "understand_operator/", "agents/")) else installed_skill_root.parent / rel
        if rel.startswith("skills/understand-operator/"):
            installed_path = installed_skill_root / Path(rel).name
        repo_hash = file_hash(repo_path)
        installed_hash = file_hash(installed_path)
        if repo_hash != installed_hash:
            mismatches.append(
                {
                    "path": rel,
                    "repo_path": str(repo_path),
                    "installed_path": str(installed_path),
                    "repo_hash": repo_hash,
                    "installed_hash": installed_hash,
                }
            )
    return {
        "version": 1,
        "repo_plugin_root": str(repo_plugin_root),
        "installed_skill_root": str(installed_skill_root),
        "installed_plugin_root": str(installed_plugin_root),
        "consistent": not mismatches,
        "error_code": "" if not mismatches else "INSTALLED_SKILL_VERSION_MISMATCH",
        "mismatches": mismatches,
    }
