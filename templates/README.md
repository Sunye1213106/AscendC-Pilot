# templates

宿主安装戳记目录。运行时 Skill / Agent / Prompt 来自 `generated/<host>/`，
由 `scripts/compose_runtime.py` 从 `skills-src` / `prompts-src` / `agents-src` 组合生成。

**Primary Agent：** `agents-src/ascendc-agent.yaml` → compose → `generated/<host>/agents/ascendc-agent.md`
→ `~/.config/opencode/agents/`（OpenCode）。
