"""Legacy .understand-operator / .testcase-generator → .ascendc-agent migration."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ascendc_harness.paths import (
    AGENT_DIR,
    LEGACY_TG_DIR,
    LEGACY_UO_DIR,
    ensure_agent_layout,
    legacy_tg_root,
    legacy_uo_root,
    tg_root,
    uo_root,
)


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def discover_legacy_ops(project_root: Path) -> dict[str, list[str]]:
    root = Path(project_root).expanduser().resolve()
    uo_ops: list[str] = []
    tg_ops: list[str] = []
    uo_base = root / LEGACY_UO_DIR
    tg_base = root / LEGACY_TG_DIR
    if uo_base.is_dir():
        uo_ops = [p.name for p in uo_base.iterdir() if p.is_dir() and (p / "manifest.yaml").is_file()]
    if tg_base.is_dir():
        tg_ops = [p.name for p in tg_base.iterdir() if p.is_dir()]
    return {"uo": sorted(uo_ops), "tg": sorted(tg_ops)}


def migrate_legacy(
    project_root: Path,
    *,
    op_name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy legacy trees into .ascendc-agent/{uo,tg}. Does not delete legacy."""
    root = Path(project_root).expanduser().resolve()
    discovered = discover_legacy_ops(root)
    uo_ops = discovered["uo"]
    tg_ops = discovered["tg"]

    if op_name:
        uo_ops = [op for op in uo_ops if op == op_name] or ([op_name] if legacy_uo_root(root, op_name).is_dir() else [])
        tg_ops = [op for op in tg_ops if op == op_name] or ([op_name] if legacy_tg_root(root, op_name).is_dir() else [])
    elif len(uo_ops) > 1:
        return {
            "ok": False,
            "error": "multiple_legacy_ops",
            "message": f"Multiple legacy UO ops {uo_ops}; pass --op-name",
            "discovered": discovered,
        }

    actions: list[dict[str, str]] = []
    if not dry_run:
        ensure_agent_layout(root)

    for op in uo_ops:
        src = legacy_uo_root(root, op)
        dst = uo_root(root)
        if src.is_dir():
            actions.append({"from": src.as_posix(), "to": dst.as_posix(), "kind": "uo"})
            if not dry_run:
                _copy_tree(src, dst)

    for op in tg_ops:
        src = legacy_tg_root(root, op)
        dst = tg_root(root)
        if src.is_dir():
            actions.append({"from": src.as_posix(), "to": dst.as_posix(), "kind": "tg"})
            if not dry_run:
                _copy_tree(src, dst)

    marker = root / AGENT_DIR / "migrate_legacy.yaml"
    result = {
        "ok": True,
        "dry_run": dry_run,
        "actions": actions,
        "agent_root": (root / AGENT_DIR).as_posix(),
        "note": "Legacy trees retained; engines now read .ascendc-agent only.",
    }
    if not dry_run and actions:
        try:
            import yaml

            marker.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return result
