"""Canonical local artifact paths under .ascendc-agent/."""

from __future__ import annotations

from pathlib import Path

AGENT_DIR = ".ascendc-agent"
UO_SUBDIR = "uo"
TG_SUBDIR = "tg"
MEMORY_SUBDIR = "memory"
RUNS_SUBDIR = "runs"
CONTEXT_SUBDIR = "context"
STATE_SUBDIR = "state"

# Legacy roots (migrate-legacy only; engines must not write here)
LEGACY_UO_DIR = ".understand-operator"
LEGACY_TG_DIR = ".testcase-generator"


def agent_root(project_root: Path) -> Path:
    return Path(project_root).expanduser().resolve() / AGENT_DIR


def uo_root(project_root: Path, op_name: str | None = None) -> Path:
    """KB root. op_name kept for API compat; products are not nested by op name."""
    del op_name
    return agent_root(project_root) / UO_SUBDIR


def tg_root(project_root: Path, op_name: str | None = None) -> Path:
    del op_name
    return agent_root(project_root) / TG_SUBDIR


def memory_root(project_root: Path) -> Path:
    return agent_root(project_root) / MEMORY_SUBDIR


def runs_root(project_root: Path) -> Path:
    return agent_root(project_root) / RUNS_SUBDIR


def context_root(project_root: Path) -> Path:
    return agent_root(project_root) / CONTEXT_SUBDIR


def state_root(project_root: Path) -> Path:
    return agent_root(project_root) / STATE_SUBDIR


def ensure_agent_layout(project_root: Path) -> Path:
    root = agent_root(project_root)
    for rel in (
        UO_SUBDIR,
        TG_SUBDIR,
        f"{MEMORY_SUBDIR}/candidate",
        f"{MEMORY_SUBDIR}/stable",
        RUNS_SUBDIR,
        CONTEXT_SUBDIR,
        STATE_SUBDIR,
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def legacy_uo_root(project_root: Path, op_name: str) -> Path:
    return Path(project_root).expanduser().resolve() / LEGACY_UO_DIR / op_name


def legacy_tg_root(project_root: Path, op_name: str) -> Path:
    return Path(project_root).expanduser().resolve() / LEGACY_TG_DIR / op_name


def global_memory_root() -> Path:
    return Path.home() / ".ascendc-agent" / "global-memory"
