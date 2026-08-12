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


_DESCRIPTIONS = {
    "uo-init": "建立算子知识库 / Build and verify AscendC Operator CodeMap (.uo)",
    "uo-update": "刷新算子知识库 / Refresh existing AscendC Operator CodeMap",
    "uo-query": "查询算子知识库 / Query existing AscendC Operator CodeMap",
    "uo-investigate": "调查知识库 gap / Investigate unresolved CodeMap gaps",
    "tg-init": "Initialize the TG contract and TilingKey binding",
    "tg-plan": "Freeze the TG coverage target set",
    "tg-solve": "Close T via per-round replay analysis: lemma rejects or directed construct",
    "ce-review": "Run CodeMap-backed AscendC code review",
}


def _command_body(workflow_id: str) -> str:
    return f"""Run the AscendC-Pilot workflow `{workflow_id}` for the current operator project.

User arguments: $ARGUMENTS

Execution contract:
1. Treat Workflow Spec / ACP as orchestration authority. Start `{workflow_id}` with `acp start` when it is not already the active workflow; do not call domain CLIs directly.
2. After start, prefer `acp run-action auto` to drain consecutive deterministic Actions and phase transitions. Do not dispatch deterministic engine identities as OpenCode Tasks. Run `acp` directly (with `--project`); **never** pipe through PowerShell `Select-Object -Last` / `Out-String` or bash `tail` — those buffer all output until exit and hide live `[acp-auto]` / `[uo]` progress.
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
    from ascendc_pilot.workflows import WORKFLOWS

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
        description = _DESCRIPTIONS.get(
            workflow_id,
            f"Run AscendC-Pilot workflow {workflow_id}",
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
