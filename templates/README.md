# templates

宿主安装戳记目录。运行时 Skill / Agent / Prompt 来自 `generated/<host>/`，
由 `scripts/compose_runtime.py` 从 `skills` / `prompts` / `agents` 组合生成。

**Primary Agent：** `agents/ascendc-pilot.yaml` → compose → `generated/<host>/agents/ascendc-pilot.md`
→ `~/.config/opencode/agents/`（OpenCode）。
