---
disable-model-invocation: true
---

                ---
                name: uo-init
                description: >-
                  首次建立 UO KB。 Harness 管阶段；本 Skill 只索引 Action。
                disable-model-invocation: true
                ---

                # uo-init

                首次建立 UO KB。

                本 Skill 不定义工作流阶段。执行时：

                1. 调用 `harness start/resume`；
                2. 调用 `harness next`；
                3. 加载返回 Action 对应的组合能力（Policy / Capability / Action Method / Prompt / Role）；
                4. 执行一个 Action；
                5. 将结果交回 Harness。

                ## Actions

                | action_id | 名称 | method | agent |
                |---|---|---|---|
                | `prepare_layout` | 创建知识库目录 | `uo-init/prepare-layout` | `deterministic-uo-engine` |
| `scope_confirmation` | 确认分析范围 | `uo-init/scope-confirmation` | `ascendc-agent` |
| `extract_plan` | 抽取计划与分层 IR | `uo-init/extract-plan` | `uo-semantic-resolve` |
| `key_triage` | KEY 粗分 | `uo-init/key-triage` | `uo-key-resolve` |
| `key_resolution` | KEY 语义闭合 | `uo-init/key-resolution` | `uo-key-resolve` |
| `confidence_report` | 生成置信度报告 | `uo-init/confidence-report` | `deterministic-uo-engine` |
| `confidence_review` | 置信度原因审查 | `uo-init/confidence-review` | `uo-confidence-review` |
| `export_integrity` | 导出与完整性校验 | `uo-init/export-integrity` | `deterministic-uo-engine` |
| `kb_review` | KB 产物审查 | `uo-init/kb-review` | `uo-kb-review` |

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
| `prepare_layout` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/prepare-layout` | `-` | `deterministic-uo-engine` |
| `scope_confirmation` | source-authority,code-access,evidence,language,harness-control,output-quality | cbm-navigation,source-reading | `uo-init/scope-confirmation` | `uo/scope-confirmation` | `ascendc-agent` |
| `extract_plan` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/extract-plan` | `uo/extract-plan` | `uo-semantic-resolve` |
| `key_triage` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/key-triage` | `uo/key-triage` | `uo-key-resolve` |
| `key_resolution` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/key-resolution` | `uo/key-resolution` | `uo-key-resolve` |
| `confidence_report` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/confidence-report` | `-` | `deterministic-uo-engine` |
| `confidence_review` | source-authority,code-access,evidence,language,harness-control,output-quality | structured-review,kb-query | `uo-init/confidence-review` | `uo/confidence-review` | `uo-confidence-review` |
| `export_integrity` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/export-integrity` | `-` | `deterministic-uo-engine` |
| `kb_review` | source-authority,code-access,evidence,language,harness-control,output-quality | structured-review,kb-query | `uo-init/kb-review` | `uo/kb-review` | `uo-kb-review` |
