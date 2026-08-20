#!/usr/bin/env python3
"""Generate native OpenCode slash commands for AscendC-Pilot workflows."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PILOT = REPO / "pilot"
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))


def _command_body(workflow_id: str) -> str:
    if workflow_id == "uo-query":
        return """查询已有 Operator CodeMap。不要 `pilot_run`。怎么拆见 `cognitive-skills/operator-analysis/routing/uo-query.md`。形态见 code-access 不变量。

用户参数：$ARGUMENTS

简单查询直接调用 `pilot_cli` `uo-query`；复杂查询同一轮委派 `Task(agent=uo-query)`。
"""
    if workflow_id == "uo-init":
        return """对当前算子项目运行 AscendC-Pilot 工作流 `uo-init`。

用户参数：$ARGUMENTS

用 Host `pilot_run` 启动。Host 返回 `UO_ALREADY_READY` 时按选项原样呈现，不要自动 `pilot_run workflow=uo-query`。
"""
    return f"""对当前算子项目运行 AscendC-Pilot 工作流 `{workflow_id}`。

用户参数：$ARGUMENTS

用 Host `pilot_run` 启动 `{workflow_id}`。Task 正文用 `task_prompt_stub` 原文。
"""


def compose(repo: Path = REPO, *, out_root: Path | None = None) -> dict[str, object]:
    """Compose commands under one OpenCode runtime root.

    ``out_root`` is the host runtime root (the directory containing
    ``skills/``, ``agents/`` and ``commands/``).  Keeping it explicit lets the
    generated-drift checker compose the exact install pipeline in a temporary
    directory instead of comparing unlike products.
    """
    repo = Path(repo).resolve()
    pilot = repo / "pilot"
    if str(pilot) not in sys.path:
        sys.path.insert(0, str(pilot))
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from ascendc_pilot.workflows import WORKFLOWS
    from compose_runtime import WORKFLOW_ENTRIES

    runtime_root = (
        Path(out_root).expanduser().resolve()
        if out_root is not None
        else repo / "generated" / "opencode"
    )
    out = runtime_root / "commands"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    generated: list[str] = []
    for workflow_id, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved") or meta.get("alias_of"):
            continue
        slash = str(meta.get("slash") or "").strip()
        if not slash:
            continue
        command_name = slash.lstrip("/") or workflow_id
        entry = WORKFLOW_ENTRIES.get(workflow_id) or {}
        description = str(
            entry.get("command_description")
            or f"运行 AscendC-Pilot 工作流 {workflow_id}"
        )
        text = (
            "---\n"
            f"description: {description}\n"
            "agent: ascendc-pilot\n"
            "subtask: false\n"
            "---\n\n"
            + _command_body(workflow_id)
        )
        path = out / f"{command_name}.md"
        path.write_text(text, encoding="utf-8")
        generated.append(path.name)

    from install_manifest import write_install_manifest

    manifest_path = write_install_manifest(runtime_root, "opencode")
    return {
        "ok": True,
        "out": out.as_posix(),
        "commands": generated,
        "install_manifest": manifest_path.as_posix(),
    }


def main() -> int:
    result = compose(REPO)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
