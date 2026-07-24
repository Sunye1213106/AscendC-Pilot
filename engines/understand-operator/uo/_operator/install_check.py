from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


# Paths relative to runtime roots:
#   repo:    <AscendC-Pilot>/generated/opencode/  (skills/agents)
#            + <AscendC-Pilot>/                     (engines/pilot — bundled as-is)
#   install: ~/.config/opencode/ascendc-pilot-plugin/
#
# Skills/agents are compared against generated/opencode; engines/pilot against repo root.
# Keep aligned with install.ps1 / install.sh composition layout.
CHECK_FILES_GENERATED = (
    "skills/uo-init/SKILL.md",
    "skills/uo-update/SKILL.md",
    "skills/uo-query/SKILL.md",
    "skills/ce-review/SKILL.md",
    "skills/tg-init/SKILL.md",
    "skills/operator/SKILL.md",
    "agents/ascendc-pilot.md",
    "agents/uo-key-resolve.md",
    "agents/uo-confidence-review.md",
    "agents/uo-kb-review.md",
    "agents/tg-csv-contract.md",
    "agents/tg-init-audit.md",
)

CHECK_FILES_REPO = (
    "engines/understand-operator/uo/_operator/install_check.py",
    "engines/understand-operator/uo/_operator/kb_compiler.py",
    "engines/understand-operator/uo/scripts/prepare_operator.py",
    "engines/understand-operator/uo/scripts/macro_scope_scan.py",
    "engines/understand-operator/uo/scripts/review_checkpoint.py",
    "engines/understand-operator/uo/scripts/stage_cbm_scope.py",
    "engines/understand-operator/uo/scripts/finalize_scope.py",
    "engines/understand-operator/uo/scripts/build_layered_kb.py",
    "engines/understand-operator/uo/scripts/classify_input_derivable.py",
    "engines/understand-operator/uo/scripts/check_final_confidence.py",
    "engines/understand-operator/uo/scripts/check_kb_integrity.py",
    "engines/understand-operator/spec/bundle.yaml",
    "engines/understand-operator/spec/ownership.yaml",
    "engines/understand-operator/spec/kb_layout.yaml",
    "pilot/ascendc_pilot/workflows/specs.py",
)

# Backward-compatible alias for tests / callers that import CHECK_FILES.
CHECK_FILES = CHECK_FILES_REPO + CHECK_FILES_GENERATED


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() and path.is_file() else ""


def _resolve_repo_root(repo_plugin_root: Path) -> Path:
    """Map engines/understand-operator or plugin dest → AscendC-Pilot repo root."""
    root = repo_plugin_root.resolve()
    if (root / "uo").is_dir() and not (root / "engines").is_dir():
        maybe = root.parents[1]
        if (maybe / "pilot").is_dir() or (maybe / "skills").is_dir():
            return maybe
    if (root / "pilot").is_dir() and (root / "skills").is_dir():
        return root
    if (root / "engines" / "understand-operator").is_dir():
        return root
    return root


def _resolve_generated_root(repo_root: Path, host: str = "opencode") -> Path:
    gen = (repo_root / "generated" / host).resolve()
    if (gen / "skills" / "uo-init" / "SKILL.md").is_file():
        return gen
    return gen


def _resolve_installed_plugin_root(installed_skill_root: Path) -> Path:
    link = installed_skill_root
    candidates = [
        link.parent.parent / "ascendc-pilot-plugin",
        link.resolve().parents[1] if link.exists() else None,
    ]
    for cand in candidates:
        if cand is not None and cand.is_dir():
            return cand.resolve()
    return (link.parent.parent / "ascendc-pilot-plugin").resolve()


def compare_installed_skill(repo_plugin_root: Path, installed_skill_root: Path) -> dict[str, Any]:
    """Compare generated runtime + repo engines against installed plugin tree.

    Primary skill is ``uo-init``. ``repo_plugin_root`` may be ``engines/understand-operator``
    or the AscendC-Pilot repo root. Skills/agents are hashed from ``generated/opencode``;
    engines/pilot from the repo root — matching ``install.ps1`` layout.
    """
    installed_skill_link = installed_skill_root
    installed_plugin_root = _resolve_installed_plugin_root(installed_skill_link)
    repo_root = _resolve_repo_root(repo_plugin_root)
    generated_root = _resolve_generated_root(repo_root)
    installed_skill_root = installed_skill_link.resolve()

    if repo_root == installed_plugin_root:
        return {
            "version": 2,
            "repo_plugin_root": str(repo_root),
            "repo_runtime_root": str(generated_root),
            "installed_skill_root": str(installed_skill_root),
            "installed_plugin_root": str(installed_plugin_root),
            "same_resolved_plugin_root": True,
            "consistent": True,
            "error_code": "",
            "mismatches": [],
        }

    mismatches: list[dict[str, str]] = []

    def _cmp(rel: str, repo_path: Path, installed_path: Path) -> None:
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

    for rel in CHECK_FILES_REPO:
        _cmp(rel, repo_root / rel, installed_plugin_root / rel)

    for rel in CHECK_FILES_GENERATED:
        _cmp(rel, generated_root / rel, installed_plugin_root / rel)

    return {
        "version": 2,
        "repo_plugin_root": str(repo_root),
        "repo_runtime_root": str(generated_root),
        "installed_skill_root": str(installed_skill_root),
        "installed_plugin_root": str(installed_plugin_root),
        "consistent": not mismatches,
        "error_code": "" if not mismatches else "INSTALLED_SKILL_VERSION_MISMATCH",
        "mismatches": mismatches,
    }
