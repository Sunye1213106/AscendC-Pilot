---
name: tg-init
description: 构建测例契约 / 测项合同与绑定、测试工具初始化。用户说 tg-init、建测例契约时加载。 Pilot 管阶段；加载后执行 acp start
  tg-init。
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

**测试脚本路径不明确 → 立刻 AskQuestion**：未给出 `--test-script-root` 且环境变量也未设时，**同一轮** `question` 请用户粘贴测试脚本根目录；禁止 Glob 全盘猜路径、长篇纠结。已明确则直接 `acp start tg-init --test-script-root <路径>`。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `kb_check` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/kb-check` | `-` | `uo-ready-v1` |
| `contract_build` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/contract-build` | `-` | `csv-contract-v1` |
| `semantic_bind` | `subagent` | `tg-semantic-bind` | `producer` | `tg-init/semantic-bind` | `tg/semantic-bind` | `semantic-bind-v1` |
| `bind_merge` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/bind-merge` | `-` | `bind-merge-v1` |
| `mid_nest` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/mid-nest` | `-` | `mid-nest-v1` |
| `integrity_gate` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/integrity-gate` | `-` | `tg-integrity-v1` |
| `init_audit` | `subagent` | `tg-init-audit` | `referee` | `tg-init/init-audit` | `tg/init-audit` | `init-audit-v1` |
| `human_confirm` | `primary_interactive` | `human` | `-` | `tg-init/human-confirm` | `tg/human-confirm` | `init-confirmed-v1` |

<!-- END GENERATED ACTIONS -->

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
8. bash 优先用工具 `workdir` 指向算子目录；若写 `cd <dir> && acp …`，Pilot 只认末尾纯 `acp` 段（禁止夹杂其它命令）。禁止用 bash/`>`/`Set-Content`/`tee` 写入 `.ascendc-pilot/**` 正式产物以绕过 Write 围栏。
9. **语义 Action 派发**：必须派声明 actor（如 `uo-semantic-resolve`）；Primary 禁止代写 `uo/ir/**`。Task 须带 `subagent_type`/`agent`=actor 与 `action_id`。**Task 正文只能原样使用 prepare 返回的 `task_prompt_stub`**（禁止复述 METHOD、禁止塞额外目标/REWORK 长文、禁止把后续 Action 的 `llm_tasks`/`mark_missing` 或超大 candidates 整包粘进 prompt）。**同 Action rework 必须 resume 原 Task session**，禁止新开第二个 session。
10. **Debug 模式（可选）**：`acp debug enable --project <算子目录>` 后自动捕捉工具失败与过长非逻辑思考链，并在子代理结束时导出 session bundle 到 `.ascendc-pilot/debug/exports/`。排查完 `acp debug disable`。手动导出：`acp debug export-session`。
11. **关键参数不明确 → 立刻 AskQuestion**：算子路径（`--project`）、architecture、continue/reinit，以及**当前 workflow 真正要求的**参数（例如 **`tg-init` 的测试脚本路径** `--test-script-root` / `ASCENDC_TEST_SCRIPT_ROOT` / `csv_consumer_root`）缺一不可时，**同一轮**用 `question` 可点选框问清；禁止为猜答案而全库 Glob、读历史 session 考古、长篇「让我想想」。已明确则直接执行，勿重复确认。**`uo-init` / `uo-update` 启动不要求测试脚本路径**——那是 TG 测例契约用的，勿在建库阶段为此打断。

12. **禁止跳步**：`acp next` 返回 `recommended_next_action` 时必须执行该 Action；禁止从 `allowed_actions` 里挑后面的确定性步骤（例如跳过 `detect_score_post`/`adjudicate_llm_tasks` 直接 `apply_semantic_patch`）。语义 Action finalize 后必须立刻再 `acp next`，不要自行猜下一步。

## 原生 Todo（所有 workflow 共用 · OpenCode `todowrite`）

阶段列表**不得**写死在各 Skill 里。一律以当前活动工作流为准：

1. **Agent 按 workflow skill 的 description 自行加载对应 Skill**（与其它 OpenCode skill 相同），然后 `acp start <workflow_id>`。`acp route` 仅可选用于 slash（如 `/uo-init`），**不做**口语关键词匹配。
2. 响应里的 `todo.todo_sync.items`（与 `todo.native_items` 相同）即该工作流在 Spec 中的**完整**阶段（必须含 `id` + 中文 `content` + `status`）。
3. **何时 `todowrite`（执行规则，禁止纠结旁白）**：
   - `acp start` 成功后：**必须**立刻同步一次（`merge` 取 JSON 布尔值；新 start 为 `false`）。
   - `advance` / `rework` / `complete` 成功后：若 `todo.todo_sync.items` 相对本轮上次已同步内容有任一 `id`/`status`/`content` 变化 → **必须**同步（`merge: true`）。
   - 纯查询型 `acp next` / `status`：仅当 items 相对上次同步有变化时才同步；**完全相同则跳过**，直接执行 Action。
   - **禁止**在思考/回复里讨论「要不要同步」「是否冗余」「严格来说该不该」——有变化就静默 `todowrite`，无变化就跳过。
   - 需要同步时：与下一步 `acp`/`run-action` **同一轮并行**调用，勿拆成「先纠结同步 → 再行动」两轮。
4. **硬约束（违反即视为控制面违规）**：
   - 一旦调用 `todowrite`：`todos` **必须等于** `todo.todo_sync.items` 全量（长度与每个 `id` 一致；须含 `priority`，勿自行删减字段）。
   - **禁止**只写当前阶段、禁止省略 `id`/`priority`、禁止子集覆盖导致其它阶段从面板消失。
   - 任意时刻最多一个 `in_progress`。
5. 状态映射（若只有 `phases[].status`）：`done`→`completed`，`current`→`in_progress`，`pending`→`pending`。工作流 `passed` 后全部 `completed`。
6. **禁止**向用户粘贴或复述：`Workflow TODO`、`todo_md`、`.ascendc-pilot/todo.md`、`状态：running`、`当前阶段`、阶段 checklist、`下一步 Action`、`正在执行 …`。进度只出现在右侧 Todo 面板。

## Runtime loop (primary only)

1. 加载匹配的 workflow skill → `acp start`（若返回 `needs_human_decision`：用 `question`/AskQuestion 可点选框 → `--decision continue|reinit`）→ 立刻 `todowrite`（全量）
2. `acp next` → 取 **`recommended_next_action`**（有则必须跑它；禁止从 `allowed_actions` 跳步）；**仅 items 有变化时**再 `todowrite`；然后执行领域方法（同步与执行同轮并行）
3. `advance` / `rework` / `complete` 后若阶段状态变了 → 再 `todowrite`；否则继续下一步

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
