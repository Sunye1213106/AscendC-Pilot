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
        return """查询已有 Operator CodeMap。主控做可见 LLM 路由，不要 `pilot_run`，不要为空转「问题路由」开子代理。

User arguments: $ARGUMENTS

1. 看一眼 `cognitive-skills/operator-analysis/references/uo-product-map.md`。
2. **先对人说出路由**（短问自查 / 1 个 Task / N 路并行，以及为什么），再动手。
3. **短问（一两跳）**：自己跑 `acp uo-query --mode <mode> --project <算子绝对路径>`，把 stdout 说给人听。
4. **深问**：同一轮原生 Task（agent=`uo-query`）。每个 prompt 写清 FOCUS + 用户原问 + 绝对 `--project`。N≥2 时并行全部返回后 Primary 综合。点卡片可看子代思考。
5. 不要 `pilot_run`。
"""
    return f"""Run the AscendC-Pilot workflow `{workflow_id}` for the current operator project.

User arguments: $ARGUMENTS

Execution contract:
1. Treat Workflow Spec / ACP as orchestration authority. Prefer Host `pilot_run` to start `{workflow_id}` when it is not already the active workflow; do not call domain CLIs directly.
2. After start, prefer Host tool `pilot_run` (OpenCode shows a live progress bar on the tool row). Fallback: `acp run-action auto` to drain consecutive deterministic Actions. Do not dispatch deterministic engine identities as OpenCode Tasks. Run `acp` directly with `--project`; never pipe through PowerShell `Select-Object -Last` / `Out-String` or bash `tail`.
3. When auto stops with `interaction_required`, execute exactly the returned Action/actor. For a subagent, use the prepared `task_prompt_stub` unchanged; for `primary_interactive`, collect the required user decision in the Primary session.
4. Finalize the interactive Action through ACP, then call `acp run-action auto` again. Never choose a later Action from `allowed_actions` when ACP recommends a different one.
5. Canonical UO/TG/CE artifacts and workflow state are written only through the declared actor + ACP finalizer/gates.
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
            or f"Run AscendC-Pilot workflow {workflow_id}"
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

    return {"ok": True, "out": out.as_posix(), "commands": generated}


def main() -> int:
    result = compose(REPO)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
