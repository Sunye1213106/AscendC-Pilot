# AscendC Harness

唯一控制面：工作流状态、质量门禁、Context Pack、本地/全局记忆、legacy 迁移。

```text
pip install -e ./harness -e ./engines/uo -e "./engines/tg[solver]"
harness doctor
harness migrate-legacy <算子仓> --op-name <op>
harness start uo-init --project <算子仓>   # 仅 entry_state
harness next --project <算子仓>
harness advance scope --project <算子仓>
harness rework --reason KEY_REWORK --project <算子仓>
harness validate-key-gates <算子仓>
harness complete --project <算子仓>   # 唯一合法 passed
```

本地产物根：`<算子仓>/.ascendc-agent/{uo,tg,memory,runs,context,state}`。

状态：`running` / `rework_required` / `human_required` / `blocked` / `failed` / `passed`。  
Gate 失败保持当前 phase 并进入 `rework_required`（或 `human_required`），不立即 `blocked`。  
完成态权威在 Harness：`Skill/Agent` 不得自行宣布 done；`mark_terminal(passed)` 被拒绝，须走 `complete`。

相关：`docs/threat-model.md` · `skills-src/` · `opencode-plugin/` · `agents/ascendc-agent.md`
