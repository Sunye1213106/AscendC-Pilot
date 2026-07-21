from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


CHECK_FILES = (
    "uo/_operator/evidence.py",
    "uo/_operator/install_check.py",
    "uo/_operator/kb_compiler.py",
    "uo/scripts/verify_required_subagents.py",
    "uo/scripts/prepare_operator.py",
    "uo/scripts/macro_scope_scan.py",
    "uo/scripts/review_checkpoint.py",
    "uo/scripts/finalize_phase0.py",
    "uo/scripts/resolve_entrypoints.py",
    "uo/scripts/propose_extract_plan.py",
    "uo/scripts/apply_extract_plan.py",
    "uo/scripts/macro_regions.py",
    "uo/scripts/extract_host_subgraph.py",
    "uo/scripts/extract_kernel_subgraph.py",
    "uo/scripts/build_layered_kb.py",
    "uo/scripts/extract_key_predicates.py",
    "uo/scripts/kb_query_export.py",
    "uo/scripts/export_kb_graph.py",
    "uo/scripts/export_human_views.py",
    "uo/scripts/uo_query_readonly.py",
    "uo/scripts/apply_resolution.py",
    "uo/scripts/check_kb_integrity.py",
    "uo/scripts/detect_kb_changes.py",
    "uo/scripts/update_operator.py",
    "uo/scripts/cbm_client.py",
    "agents/uo-semantic-resolve.md",
    "agents/uo-kb-review.md",
    "prompts/00_subagent_dispatch.md",
    "prompts/00_review_menu.md",
    "prompts/01a_macro_scope_human_review.md",
    "prompts/01_workflow_orchestrator.md",
    "prompts/common/10_tool_execution_rules.md",
    "skills/understand-operator/SKILL.md",
    "skills/uo-init/SKILL.md",
    "skills/uo-query/SKILL.md",
    "skills/uo-update/SKILL.md",
    "spec/bundle.yaml",
    "spec/ownership.yaml",
    "spec/kb_layout.yaml",
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
        if rel.startswith("skills/uo-") or rel.startswith("skills/understand-operator/"):
            installed_path = installed_skill_root.parent / rel
        elif rel.startswith(("prompts/", "uo/", "agents/")):
            installed_path = installed_plugin_root / rel
        else:
            installed_path = installed_plugin_root / rel
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
