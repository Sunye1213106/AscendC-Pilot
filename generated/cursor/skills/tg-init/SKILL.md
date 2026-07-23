---
name: tg-init
description: 构建测项合同与绑定。 Harness 管阶段；本 Skill 只索引 Action。
disable-model-invocation: true
---

# tg-init

构建测项合同与绑定。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `harness start`（同 workflow 活动 run 则复用）；
2. 调用 `harness next`；
3. 对返回的 action_id 调用 `harness run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `harness run-action <action_id> --finalize`；
5. 调用 `harness advance`（仅消费 run-action 签发的可信收据）。

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

## Composed: harness-control

# Policy: harness-control

## Purpose

Harness 独占状态、合法边、门禁与完成态。

## Rules

1. 只能执行 `harness next` 返回的 Action。
2. Skill、Prompt、Agent、Capability、Action Method **不得**推进工作流状态。
3. 终态只认 `harness complete`；禁止自行宣布 `done` / `passed`。
4. Gate fail ≠ 立即 `blocked`；保持 phase，进入 `rework_required` / `human_required`。
5. 禁止直调领域 CLI（`build_layered_kb.py`、`tg-init`、`tg-plan`、`tg-solve` 等）；须经 harness 包装。
6. 正式产物须 Harness 签发收据。

## Runtime loop (primary only)

1. `harness route` / `harness start`（若无活动 run）
2. `harness next` → 取 Action
3. 执行一个 Action 的领域方法
4. 交回 Harness（advance / rework / complete 由控制面决定）

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `kb_check` | source-authority,code-access,evidence,language,harness-control,output-quality | kb-query | `tg-init/kb-check` | `-` | `deterministic-tg-engine` |
| `contract_build` | source-authority,code-access,evidence,language,harness-control,output-quality | contract-building,kb-query,obligation-analysis | `tg-init/contract-build` | `-` | `deterministic-tg-engine` |
| `semantic_bind` | source-authority,code-access,evidence,language,harness-control,output-quality | kb-query,semantic-resolution | `tg-init/semantic-bind` | `tg/semantic-bind` | `tg-semantic-bind` |
| `bind_merge` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `tg-init/bind-merge` | `-` | `deterministic-tg-engine` |
| `mid_nest` | source-authority,code-access,evidence,language,harness-control,output-quality | obligation-analysis | `tg-init/mid-nest` | `-` | `deterministic-tg-engine` |
| `integrity_gate` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `tg-init/integrity-gate` | `-` | `deterministic-tg-engine` |
| `init_audit` | source-authority,code-access,evidence,language,harness-control,output-quality | structured-review,kb-query | `tg-init/init-audit` | `tg/init-audit` | `tg-init-audit` |
| `human_confirm` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `tg-init/human-confirm` | `tg/human-confirm` | `human` |

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
