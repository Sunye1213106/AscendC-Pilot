---
name: uo-init
description: 首次建立 UO KB。 Harness 管阶段；本 Skill 只索引 Action。
---

# uo-init

首次建立 UO KB。

## 硬规则（读完再动手）

0. **必须先 Tab 切到 `ascendc-agent`（primary）再跑本 Skill**。默认 Build/其它 agent 没有 harness 权限围栏，会把流程当成“读 METHOD 手干”。
1. **`harness` 是真实 CLI**（本机已安装），不是概念步骤，**禁止**“按 METHOD 手工模拟工作流”。
2. **禁止跳步**：必须先 `harness start` → `harness next` → 当前 `action_id`；不得一上来做 scope 或读源码建 KB。
3. **确定性 Action**（如 `prepare_layout`）：只跑 `harness run-action <id>`，会自动 finalize。
4. **语义 Action**：`run-action` 准备 → 按 Bundle 派发 actor → `--finalize`。
5. **禁止**用 Glob/Read 自编「文件计数表」代替 `harness uo-scope scan`；`common/` 由扫描脚本向上发现，手数必漏。
6. **已废弃**：旧 skill `understand-operator` / `uo-diff`（无 harness）；若仍出现在技能列表，删掉对应 junction 后重装。

## 执行循环

1. `harness start uo-init --project <算子目录>`
2. `harness next --project <算子目录>`
3. `harness run-action <action_id> --project <算子目录>`
4. 语义 Action 产出后：`harness run-action <action_id> --finalize`
5. `harness advance <next_phase>`（仅有可信收据时）

用户说「只分析 arch35」时：在 `scope_confirmation` 用  
`harness uo-scope scan --architecture arch35`（不要自己筛目录）。

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `prepare_layout` | 创建知识库目录 | `uo-init/prepare-layout` | `deterministic-uo-engine` | `deterministic_engine` |
| `scope_confirmation` | 确认分析范围 | `uo-init/scope-confirmation` | `ascendc-agent` | `producer` |
| `detect_score_pre` | 抽取前评分(pre_semantic) | `uo-init/detect-score-pre` | `deterministic-uo-engine` | `deterministic_engine` |
| `extract_plan` | 抽取计划与分层 IR | `uo-init/extract-plan` | `uo-semantic-resolve` | `producer` |
| `apply_semantic_patch` | 应用语义补丁(ledger) | `uo-init/apply-semantic-patch` | `deterministic-uo-engine` | `deterministic_engine` |
| `rebuild_from_ledger` | 由账本重建派生图 | `uo-init/rebuild-from-ledger` | `deterministic-uo-engine` | `deterministic_engine` |
| `detect_score_post` | 抽取后评分(post_semantic) | `uo-init/detect-score-post` | `deterministic-uo-engine` | `deterministic_engine` |
| `recheck_closure` | 复核闭合(不增 attempts) | `uo-init/recheck-closure` | `deterministic-uo-engine` | `deterministic_engine` |
| `key_triage` | KEY 粗分 | `uo-init/key-triage` | `uo-key-resolve` | `producer` |
| `key_resolution` | KEY 语义闭合 | `uo-init/key-resolution` | `uo-key-resolve` | `producer` |
| `confidence_report` | 生成置信度报告 | `uo-init/confidence-report` | `deterministic-uo-engine` | `deterministic_engine` |
| `confidence_review` | 置信度原因审查 | `uo-init/confidence-review` | `uo-confidence-review` | `referee` |
| `export_integrity` | 导出与完整性校验 | `uo-init/export-integrity` | `deterministic-uo-engine` | `deterministic_engine` |
| `kb_review` | KB 产物审查 | `uo-init/kb-review` | `uo-kb-review` | `referee` |

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
| `detect_score_pre` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/detect-score-pre` | `-` | `deterministic-uo-engine` |
| `extract_plan` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/extract-plan` | `uo/extract-plan` | `uo-semantic-resolve` |
| `apply_semantic_patch` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/apply-semantic-patch` | `-` | `deterministic-uo-engine` |
| `rebuild_from_ledger` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/rebuild-from-ledger` | `-` | `deterministic-uo-engine` |
| `detect_score_post` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/detect-score-post` | `-` | `deterministic-uo-engine` |
| `recheck_closure` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/recheck-closure` | `-` | `deterministic-uo-engine` |
| `key_triage` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/key-triage` | `uo/key-triage` | `uo-key-resolve` |
| `key_resolution` | source-authority,code-access,evidence,language,harness-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/key-resolution` | `uo/key-resolution` | `uo-key-resolve` |
| `confidence_report` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/confidence-report` | `-` | `deterministic-uo-engine` |
| `confidence_review` | source-authority,code-access,evidence,language,harness-control,output-quality | structured-review,kb-query | `uo-init/confidence-review` | `uo/confidence-review` | `uo-confidence-review` |
| `export_integrity` | source-authority,code-access,evidence,language,harness-control,output-quality | - | `uo-init/export-integrity` | `-` | `deterministic-uo-engine` |
| `kb_review` | source-authority,code-access,evidence,language,harness-control,output-quality | structured-review,kb-query | `uo-init/kb-review` | `uo/kb-review` | `uo-kb-review` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `prepare_layout` | `actions/prepare-layout/METHOD.md` | `-` | `kb-layout-v1` | `deterministic_engine` |
| `scope_confirmation` | `actions/scope-confirmation/METHOD.md` | `prompts/tasks/uo/scope-confirmation.md` | `scope-confirmed-v1` | `producer` |
| `detect_score_pre` | `actions/detect-score-pre/METHOD.md` | `-` | `detect-score-pre-v1` | `deterministic_engine` |
| `extract_plan` | `actions/extract-plan/METHOD.md` | `prompts/tasks/uo/extract-plan.md` | `extract-plan-v1` | `producer` |
| `apply_semantic_patch` | `actions/apply-semantic-patch/METHOD.md` | `-` | `semantic-patch-v1` | `deterministic_engine` |
| `rebuild_from_ledger` | `actions/rebuild-from-ledger/METHOD.md` | `-` | `rebuild-ledger-v1` | `deterministic_engine` |
| `detect_score_post` | `actions/detect-score-post/METHOD.md` | `-` | `detect-score-post-v1` | `deterministic_engine` |
| `recheck_closure` | `actions/recheck-closure/METHOD.md` | `-` | `recheck-closure-v1` | `deterministic_engine` |
| `key_triage` | `actions/key-triage/METHOD.md` | `prompts/tasks/uo/key-triage.md` | `key-triage-v1` | `producer` |
| `key_resolution` | `actions/key-resolution/METHOD.md` | `prompts/tasks/uo/key-resolution.md` | `input-derivable-patch-v1` | `producer` |
| `confidence_report` | `actions/confidence-report/METHOD.md` | `-` | `confidence-report-v1` | `deterministic_engine` |
| `confidence_review` | `actions/confidence-review/METHOD.md` | `prompts/tasks/uo/confidence-review.md` | `confidence-reason-review-v1` | `referee` |
| `export_integrity` | `actions/export-integrity/METHOD.md` | `-` | `integrity-v1` | `deterministic_engine` |
| `kb_review` | `actions/kb-review/METHOD.md` | `prompts/tasks/uo/kb-review.md` | `kb-review-v1` | `referee` |
