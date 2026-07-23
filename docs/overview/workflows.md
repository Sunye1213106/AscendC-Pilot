# Workflow 人类说明（非可执行状态机）

控制面权威在 Pilot `workflows/specs.py`。运行时指令由 Composer 从
`skills` / `prompts` / `agents` 组合生成。

| Workflow | Slash | 说明 |
|---|---|---|
| uo-init | /uo-init | 首次建立 UO KB |
| uo-update | /uo-update | 增量更新；含 diff_only |
| uo-query | /uo-query | 只读 KB 查询 |
| ce-review | /ce-review | 基于 KB 的代码审查 |
| tg-init | /tg-init | 测项合同与绑定 |
| tg-plan | /tg-plan | 覆盖义务与人工批准 |
| tg-solve | /tg-solve | Z3 求解与投影 |
| operator | /operator | `acp route` 别名 |

旧 `prompts/*/workflow.md` 已废弃，不再作为可执行状态机。
