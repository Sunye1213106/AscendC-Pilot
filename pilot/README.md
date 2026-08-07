# AscendC Pilot

唯一控制面：工作流状态、质量门禁、Context Pack、本地/全局记忆、legacy 迁移。

```text
pip install -e ./pilot -e ./engines/understand-operator -e "./engines/testcase-generation[ml]"
acp doctor
acp migrate-legacy <算子仓> --op-name <op>
acp start uo-init --project <算子仓>   # 仅 entry_state
acp next --project <算子仓>
acp advance scope --project <算子仓>
acp rework --reason KEY_REWORK --project <算子仓>
acp validate-key-gates <算子仓>
acp complete --project <算子仓>   # 唯一合法 passed
```

本地产物根：`<算子仓>/.ascendc-pilot/{uo,tg,memory,runs,context,state}`。

状态：`running` / `rework_required` / `human_required` / `blocked` / `failed` / `passed`。  
Gate 失败保持当前 phase 并进入 `rework_required`（或 `human_required`），不立即 `blocked`。  
完成态权威在 Pilot：`Skill/Agent` 不得自行宣布 done；`mark_terminal(passed)` 被拒绝，须走 `complete`。

相关：`docs/threat-model.md` · `skills/` · `prompts/` · `agents/` · `opencode-plugin/` · `generated/*/agents/ascendc-pilot.md`
