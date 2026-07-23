# OpenCode Plugin（仓内唯一源）

安装目标：`~/.config/opencode/plugins/ascendc-pilot.ts`

```text
# 由 install.ps1/sh opencode 复制；也可手动：
copy opencode-plugin\ascendc-pilot.ts %USERPROFILE%\.config\opencode\plugins\
```

- **不**修改用户 `opencode.json`
- Primary Agent：`agents/ascendc-pilot.yaml` → `generated/<host>/agents/ascendc-pilot.md` → `~/.config/opencode/agents/`
- Hook：`tool.execute.before` → `acp authorize`
- 威胁模型：模式内软拦截；不能阻止用户切 Tab / 终端直改
