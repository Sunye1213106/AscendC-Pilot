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


def output_root(project_root: Path, op_name: str, *, arch: str | None = None) -> Path:
    """``<op_src>/.ascendc-pilot/<arch>/tg`` — op nesting is via arch, not op_name."""
    del op_name
    try:
        from ascendc_pilot.paths import tg_root

        return tg_root(project_root, arch=arch)
    except Exception:
        arch_name = (arch or "").strip()
        if not arch_name:
            raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
        return project_root / ".ascendc-pilot" / arch_name / "tg"


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
    del level
    root = Path(out_root)
    plan = root / "plan.md"
    if not plan.is_file():
        raise FileNotFoundError("missing tg/plan.md; run /tg-plan")
    return root
