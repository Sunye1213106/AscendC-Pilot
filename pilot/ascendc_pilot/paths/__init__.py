"""Canonical local artifact paths under .ascendc-pilot/."""

from __future__ import annotations

import shutil
from pathlib import Path

AGENT_DIR = ".ascendc-pilot"
LEGACY_AGENT_DIR = ".ascendc-agent"
UO_SUBDIR = "uo"
TG_SUBDIR = "tg"
CE_SUBDIR = "ce"
MEMORY_SUBDIR = "memory"
RUNS_SUBDIR = "runs"
CONTEXT_SUBDIR = "context"
STATE_SUBDIR = "state"


def agent_root(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR


def uo_root(project_root: Path, op_name: str | None = None) -> Path:
    del op_name
    return agent_root(project_root) / UO_SUBDIR


def tg_root(project_root: Path, op_name: str | None = None) -> Path:
    del op_name
    return agent_root(project_root) / TG_SUBDIR


def ce_root(project_root: Path, op_name: str | None = None) -> Path:
    del op_name
    return agent_root(project_root) / CE_SUBDIR


def memory_root(project_root: Path) -> Path:
    return agent_root(project_root) / MEMORY_SUBDIR


def runs_root(project_root: Path) -> Path:
    return agent_root(project_root) / RUNS_SUBDIR


def context_root(project_root: Path) -> Path:
    return agent_root(project_root) / CONTEXT_SUBDIR


def state_root(project_root: Path) -> Path:
    return agent_root(project_root) / STATE_SUBDIR


def migrate_legacy_agent_dir(project_root: Path) -> dict[str, object]:
    """Migrate .ascendc-agent → .ascendc-pilot when only legacy exists.

    If both exist, refuse to merge.
    """
    root = Path(project_root).expanduser().resolve()
    legacy = root / LEGACY_AGENT_DIR
    modern = root / AGENT_DIR
    if modern.exists() and legacy.exists():
        return {
            "ok": False,
            "error": "both_agent_dirs_exist",
            "message": "Both .ascendc-agent and .ascendc-pilot exist; refuse automatic merge.",
        }
    if modern.exists() or not legacy.exists():
        return {"ok": True, "migrated": False, "root": str(modern if modern.exists() else "")}
    shutil.move(str(legacy), str(modern))
    ctx = modern / CONTEXT_SUBDIR
    old_params = ctx / "harness_params.yaml"
    new_params = ctx / "pilot_params.yaml"
    if old_params.exists() and not new_params.exists():
        old_params.rename(new_params)
    elif old_params.exists() and new_params.exists():
        old_params.unlink()
    (modern / CE_SUBDIR).mkdir(parents=True, exist_ok=True)
    return {"ok": True, "migrated": True, "root": str(modern)}


def ensure_agent_layout(project_root: Path) -> Path:
    migrate_legacy_agent_dir(project_root)
    root = agent_root(project_root)
    for rel in (
        UO_SUBDIR,
        TG_SUBDIR,
        CE_SUBDIR,
        f"{MEMORY_SUBDIR}/candidate",
        f"{MEMORY_SUBDIR}/stable",
        RUNS_SUBDIR,
        CONTEXT_SUBDIR,
        STATE_SUBDIR,
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def global_memory_root() -> Path:
    return Path.home() / ".ascendc-pilot" / "global-memory"
