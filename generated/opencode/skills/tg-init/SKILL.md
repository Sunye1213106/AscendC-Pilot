---
name: tg-init
description: 构建测项合同与绑定。 Pilot 管阶段；本 Skill 只索引 Action。
---

# tg-init

构建测项合同与绑定。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

前置条件：

- 定稿 UO KB（`uo_ready`）
- 测试脚本 / CSV 消费端目录：`--test-script-root` / `csv_consumer_root` / `ASCENDC_TEST_SCRIPT_ROOT`

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `kb_check` | 校验定稿 KB | `tg-init/kb-check` | `deterministic-tg-engine` | `deterministic_engine` |
| `contract_build` | 构建合同骨架 | `tg-init/contract-build` | `deterministic-tg-engine` | `deterministic_engine` |
| `semantic_bind` | 语义绑定 | `tg-init/semantic-bind` | `tg-semantic-bind` | `producer` |
| `bind_merge` | 绑定合并 | `tg-init/bind-merge` | `deterministic-tg-engine` | `deterministic_engine` |
| `mid_nest` | 中间量闭合 | `tg-init/mid-nest` | `deterministic-tg-engine` | `deterministic_engine` |
| `integrity_gate` | 完整性校验 | `tg-init/integrity-gate` | `deterministic-tg-engine` | `deterministic_engine` |
| `init_audit` | Init 审计 | `tg-init/init-audit` | `tg-init-audit` | `referee` |
| `human_confirm` | 人工确认 | `tg-init/human-confirm` | `human` | `-` |

## Composed: pilot-control

# Policy: pilot-control

## Purpose

Pilot 独占状态、合法边、门禁与完成态。

## Rules

1. 只能执行 `acp next` 返回的 Action。
2. Skill、Prompt、Agent、Capability、Action Method **不得**推进工作流状态。
3. 终态只认 `acp complete`；禁止自行宣布 `done` / `passed`。
4. Gate fail ≠ 立即 `blocked`；保持 phase，进入 `rework_required` / `human_required`。
5. 禁止直调领域 CLI（`build_layered_kb.py`、`tg-init`、`tg-plan`、`tg-solve` 等）；须经 acp 包装。
6. 正式产物须 Pilot 签发收据。
7. **进度只进 OpenCode 原生 Todo**（见下方「原生 Todo」）；禁止在主对话输出工作流状态面板。
8. bash 优先用工具 `workdir` 指向算子目录；若写 `cd <dir> && acp …`，Pilot 只认末尾纯 `acp` 段（禁止夹杂其它命令）。

## 原生 Todo（所有 workflow 共用 · OpenCode `todowrite`）

阶段列表**不得**写死在各 Skill 里。一律以当前路由工作流为准：

1. `acp route` / `acp start <workflow_id>` 确定活动工作流。
2. 响应里的 `todo.todo_sync.items`（与 `todo.native_items` 相同）即该工作流在 Spec 中的**完整**阶段（必须含 `id` + 中文 `content` + `status`）。
3. **`acp start` 成功后立刻**按 `todo.todo_sync` 调用 `todowrite`：`merge` 取 JSON 中的布尔值（新 start 为 `false`）。
4. 之后每次 `acp next` / `advance` / `rework` / `complete` / `status`：再按最新 `todo.todo_sync` 同步（`merge: true`）。
5. **硬约束（违反即视为控制面违规）**：
   - `todos` **必须等于** `todo.todo_sync.items` 全量（长度与每个 `id` 一致）。
   - **禁止**只写当前阶段、禁止省略 `id`、禁止子集覆盖导致其它阶段从面板消失。
   - 任意时刻最多一个 `in_progress`。
6. 状态映射（若只有 `phases[].status`）：`done`→`completed`，`current`→`in_progress`，`pending`→`pending`。工作流 `passed` 后全部 `completed`。
7. **禁止**向用户粘贴或复述：`Workflow TODO`、`todo_md`、`.ascendc-pilot/todo.md`、`状态：running`、`当前阶段`、阶段 checklist、`下一步 Action`、`正在执行 …`。进度只出现在右侧 Todo 面板。

## Runtime loop (primary only)

1. `acp route` / `acp start`（若无活动 run）→ 立刻按 `todo.todo_sync` 做 `todowrite`
2. `acp next` → 取 Action，并用 `todowrite` 全量同步（不向用户粘贴阶段表）
3. 执行一个 Action 的领域方法
4. 交回 Pilot（advance / rework / complete 由控制面决定）→ 再 `todowrite` 全量同步

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `kb_check` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `tg-init/kb-check` | `-` | `deterministic-tg-engine` |
| `contract_build` | source-authority,code-access,evidence,language,pilot-control,output-quality | contract-building,kb-query,obligation-analysis | `tg-init/contract-build` | `-` | `deterministic-tg-engine` |
| `semantic_bind` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query,semantic-resolution | `tg-init/semantic-bind` | `tg/semantic-bind` | `tg-semantic-bind` |
| `bind_merge` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/bind-merge` | `-` | `deterministic-tg-engine` |
| `mid_nest` | source-authority,code-access,evidence,language,pilot-control,output-quality | obligation-analysis | `tg-init/mid-nest` | `-` | `deterministic-tg-engine` |
| `integrity_gate` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/integrity-gate` | `-` | `deterministic-tg-engine` |
| `init_audit` | source-authority,code-access,evidence,language,pilot-control,output-quality | structured-review,kb-query | `tg-init/init-audit` | `tg/init-audit` | `tg-init-audit` |
| `human_confirm` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/human-confirm` | `tg/human-confirm` | `human` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `kb_check` | `actions/kb-check/METHOD.md` | `-` | `uo-ready-v1` | `deterministic_engine` |
| `contract_build` | `actions/contract-build/METHOD.md` | `-` | `csv-contract-v1` | `deterministic_engine` |
| `semantic_bind` | `actions/semantic-bind/METHOD.md` | `prompts/tasks/tg/semantic-bind.md` | `semantic-bind-v1` | `producer` |
| `bind_merge` | `actions/bind-merge/METHOD.md` | `-` | `bind-merge-v1` | `deterministic_engine` |
| `mid_nest` | `actions/mid-nest/METHOD.md` | `-` | `mid-nest-v1` | `deterministic_engine` |
| `integrity_gate` | `actions/integrity-gate/METHOD.md` | `-` | `tg-integrity-v1` | `deterministic_engine` |
| `init_audit` | `actions/init-audit/METHOD.md` | `prompts/tasks/tg/init-audit.md` | `init-audit-v1` | `referee` |
| `human_confirm` | `actions/human-confirm/METHOD.md` | `prompts/tasks/tg/human-confirm.md` | `init-confirmed-v1` | `-` |
