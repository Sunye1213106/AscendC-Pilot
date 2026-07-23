from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


# Paths relative to installed plugin root (ascendc-pilot-plugin).
# Keep aligned with install.ps1 / install.sh composition layout.
CHECK_FILES = (
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


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() and path.is_file() else ""


def compare_installed_skill(repo_plugin_root: Path, installed_skill_root: Path) -> dict[str, Any]:
    """Compare composed plugin install against a skill junction target.

    Primary skill is ``uo-init``. ``repo_plugin_root`` may be ``engines/understand-operator`` or the
    install Dest root (``ascendc-pilot-plugin``). When the installed plugin resolves
    to the same tree, treat as consistent.
    """
    installed_skill_link = installed_skill_root
    # ~/.config/opencode/skills/uo-init → Dest = .../ascendc-pilot-plugin
    candidates = [
        installed_skill_link.parent.parent / "ascendc-pilot-plugin",
        installed_skill_link.resolve().parents[1] if installed_skill_link.resolve().exists() else None,
    ]
    installed_plugin_root = None
    for cand in candidates:
        if cand is not None and cand.is_dir():
            installed_plugin_root = cand.resolve()
            break
    if installed_plugin_root is None:
        installed_plugin_root = (installed_skill_link.parent.parent / "ascendc-pilot-plugin").resolve()

    repo_plugin_root = repo_plugin_root.resolve()
    installed_skill_root = installed_skill_link.resolve()

    # Callers historically pass engines/understand-operator; map to bundle/plugin root when possible.
    if (repo_plugin_root / "uo").is_dir() and not (repo_plugin_root / "engines").is_dir():
        # engines/understand-operator → try repo root two levels up
        maybe_repo = repo_plugin_root.parents[1]
        if (maybe_repo / "pilot").is_dir() or (maybe_repo / "skills").is_dir():
            repo_plugin_root = maybe_repo

    if repo_plugin_root == installed_plugin_root:
        return {
            "version": 2,
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
        if rel.startswith("skills/"):
            installed_path = installed_skill_root.parent / Path(rel).name / "SKILL.md"
            if rel.endswith("SKILL.md"):
                installed_path = installed_skill_root.parent / Path(rel).parts[1] / "SKILL.md"
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
        "version": 2,
        "repo_plugin_root": str(repo_plugin_root),
        "installed_skill_root": str(installed_skill_root),
        "installed_plugin_root": str(installed_plugin_root),
        "consistent": not mismatches,
        "error_code": "" if not mismatches else "INSTALLED_SKILL_VERSION_MISMATCH",
        "mismatches": mismatches,
    }
