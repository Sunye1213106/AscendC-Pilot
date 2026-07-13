from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


CHECK_FILES = (
    "skills/understand-operator/quality_gate.py",
    "understand_operator/_operator/kb_compiler.py",
    "skills/understand-operator/prepare_operator.py",
    "skills/understand-operator/verify_subagent_barrier.py",
    "skills/understand-operator/SKILL.md",
    "prompts/08_evidence_consistency_agent.md",
    "prompts/10_quality_gate_agent.md",
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() and path.is_file() else ""


def compare_installed_skill(repo_plugin_root: Path, installed_skill_root: Path) -> dict[str, Any]:
    repo_plugin_root = repo_plugin_root.resolve()
    installed_skill_root = installed_skill_root.resolve()
    installed_plugin_root = installed_skill_root.parent / "understand-operator-plugin"
    mismatches: list[dict[str, str]] = []
    for rel in CHECK_FILES:
        repo_path = repo_plugin_root / rel
        installed_path = installed_plugin_root / rel if rel.startswith(("prompts/", "understand_operator/")) else installed_skill_root.parent / rel
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
