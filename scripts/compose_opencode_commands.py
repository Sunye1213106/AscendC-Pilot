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
        return """查询已有 Operator CodeMap。主控先向用户说明查询方式，不要 `pilot_run`，禁止仅为问题分类而委派子代理。

User arguments: $ARGUMENTS

1. 先阅读 `cognitive-skills/operator-analysis/references/uo-product-map.md`。
2. **先向用户说明**将直接调用还是委派几路，再执行。怎么拆见 `cognitive-skills/operator-analysis/routing/uo-query.md`。
3. **简单查询**：主控直接调用 `acp uo-query --project <算子绝对路径>`（标识符 / Dim=V / --file --line / 无参数索引），将 stdout 向用户陈述。
4. **复杂查询**：用户原话里几个可独立作为首次调用的起始点，就同一轮并行几路 `Task(agent=uo-query)`（上限 5）。「要交叉综合」不是合并的理由。每路 Task 正文：
   FOCUS: <本路唯一查询目标>
   建议的首次调用: acp uo-query --project <绝对路径> [--architecture arch35] <标识符或 Dim=V>
   本片那一句: <这一路要回答的那一句>
   禁止在 Task 正文写 `--mode`。
5. 子代按卡片 `next` / `hint` 继续调用 `acp uo-query`。图上还能查的独立缺口必须开第 2 轮（路数=缺口数，≤5），禁止用无实质内容的确认（例如「是否继续」）代替。多路已有结论但结案仍不清时 AskQuestion 给出选项。不要 `pilot_run`。
"""
    if workflow_id == "uo-init":
        return """Run the AscendC-Pilot workflow `uo-init` for the current operator project.

User arguments: $ARGUMENTS

Execution contract:
1. Treat Workflow Spec / ACP as orchestration authority. Prefer Host `pilot_run` to start `uo-init` when it is not already the active workflow; do not call domain CLIs directly.
2. If ACP returns `UO_ALREADY_READY` (CodeMap already exists, lock released): this is not an unfinished run. Present options verbatim. 「去查询」means stop Host drive and wait for a question — do not auto-drive, do not `pilot_run uo-query`, do not read quality.yaml as if you just built.
3. After a real start, prefer Host tool `pilot_run` (OpenCode shows a live progress bar on the tool row). Fallback: `acp run-action auto` to drain consecutive deterministic Actions. Do not dispatch deterministic engine identities as OpenCode Tasks. Run `acp` directly with `--project`; never pipe through PowerShell `Select-Object -Last` / `Out-String` or bash `tail`.
4. When auto stops with `interaction_required`, execute exactly the returned Action/actor. For a subagent, use the prepared `task_prompt_stub` unchanged; for `primary_interactive`, collect the required user decision in the Primary session.
5. Finalize the interactive Action through ACP, then call `acp run-action auto` again. Never choose a later Action from `allowed_actions` when ACP recommends a different one.
6. Canonical UO/TG/CE artifacts and workflow state are written only through the declared actor + ACP finalizer/gates.
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
