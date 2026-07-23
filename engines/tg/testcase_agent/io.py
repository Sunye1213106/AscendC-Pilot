from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def assert_tg_write_path(path: Path | str, *, out_root: Path | None = None) -> Path:
    """Delegate to isolation module (avoid circular import at package load)."""
    from .isolation import assert_tg_write_path as _assert

    return _assert(path, out_root=out_root)


def read_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return {} if data is None else data


def write_yaml(path: Path, data: Any) -> None:
    assert_tg_write_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    assert_tg_write_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def output_root(project_root: Path, op_name: str) -> Path:
    del op_name  # products live under .ascendc-agent/tg (no op nesting)
    return project_root / ".ascendc-agent" / "tg"


def ensure_output_dirs(root: Path) -> None:
    for rel in (
        "snapshot",
        "intake",
        "plan",
        "solve",
        "extract",
        "cases",
        "topics",
        "realization",
        "contract",
        "init",
        "bind",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)


def resolve_plan_dir(out_root: Path, level: str = "") -> Path:
    """Resolve plan/levels/<L> for solve/approve. Root plan/ is not the obligations source of truth."""
    level = str(level or "").strip().upper()
    if not level:
        latest_path = out_root / "plan" / "latest_level.yaml"
        if latest_path.is_file():
            latest = read_yaml(latest_path)
            if isinstance(latest, dict):
                level = str(latest.get("level") or "").strip().upper()
    if not level:
        raise FileNotFoundError(
            "PLAN_LEVEL_REQUIRED: pass --level L0|L1|L2 "
            "(expected plan/levels/<L>/coverage_obligations.yaml). "
            "Do not Copy-Item root plan/*.yaml into levels/."
        )
    # Compat: legacy L1-BRANCH dir → L1
    plan_dir = out_root / "plan" / "levels" / level
    if level == "L1-BRANCH" and not (plan_dir / "coverage_obligations.yaml").is_file():
        legacy = out_root / "plan" / "levels" / "L1"
        if (legacy / "coverage_obligations.yaml").is_file():
            plan_dir = legacy
            level = "L1"
    obligations = plan_dir / "coverage_obligations.yaml"
    if not obligations.is_file():
        raise FileNotFoundError(
            f"Missing coverage plan for {level}: {obligations}. "
            f"Re-run tg-plan --level {level}. "
            "Do not Copy-Item root plan/coverage_obligations.yaml into levels/."
        )
    return plan_dir
