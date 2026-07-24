---
name: uo-init
description: 首次建立 / 创建本地知识库（UO KB）、建库、初始化算子知识库。 用户提到建立知识库、只分析某架构分支（如 arch35）时加载本 Skill。
  Pilot 管阶段；加载后执行 acp start uo-init。
disable-model-invocation: false
---

# uo-init

首次建立 UO KB。

## 硬规则（读完再动手）

0. **必须先 Tab 切到 `ascendc-pilot`（primary）再跑本 Skill**。默认 Build/其它 agent 没有 acp 权限围栏，会把流程当成“读 METHOD 手干”。
1. **`acp` 是真实 CLI**（本机已安装），不是概念步骤，**禁止**“按 METHOD 手工模拟工作流”。
2. **禁止跳步**：必须先 `acp start` → `acp next` → 当前 `action_id`；不得一上来做 scope 或读源码建 KB。
3. **确定性 Action**（如 `prepare_layout`）：只跑 `acp run-action <id>`，会自动 finalize。
4. **语义 Action**：`run-action` 准备 → 按 Bundle **派发声明 actor**（如 `uo-semantic-resolve`）→ actor 写合同产物 → `--finalize`。
   - Primary **禁止**自己 Write `uo/ir/**`（会 `PRIMARY_PROTECTED_WRITE`）。
   - Task 须带 `subagent_type`/`agent` = Bundle 的 `actor_id`，并带上 `action_id`。
   - **`extract_plan` 只确认 candidates→`extract_plan.yaml`**；禁止把 `llm_tasks`/`mark_missing` 塞进该子任务（留给 `apply_semantic_patch`）。
   - **禁止**把超大 `extract_plan_candidates.yaml` 整包粘进 Task prompt；只传路径，让子代理自己 Read。
   - Write 被拒后 **禁止**用 bash/`Set-Content`/`>` 绕过围栏写正式 IR。
5. **禁止**用 Glob/Read 自编「文件计数表」代替 `acp uo-scope scan`；`common/` 由扫描脚本向上发现，手数必漏。
6. **进度 / Todo**：遵循公共策略 `pilot-control`（原生 Todo）；勿在本 Skill 硬编码阶段表，勿在主对话贴状态面板。

## 启动前：未完成 run → AskQuestion（与 scope 同款可点选框）

算子目录若已有活动 `uo-init` run 或残留 `.ascendc-pilot/uo`，**禁止静默复用 / 自动删除**。

```text
acp start uo-init --project <算子目录>
# 若返回 needs_human_decision=true / EXISTING_RUN_NEEDS_DECISION：
# 1) 把 run_summary.summary_text_zh（完整/中断点）贴给用户
# 2) 必须调用 OpenCode `question`（AskQuestion），options 用返回的 ask_question.options
# 3) 等人点选后再执行：
acp start uo-init --project <算子目录> --decision continue   # 从最近完整步骤之后继续
acp start uo-init --project <算子目录> --decision reinit     # 删除 uo 产物后重新 init
```

可选先查摘要：`acp run-summary --project <算子目录>`。

| 选项 | 含义 |
|---|---|
| 继续上次 | 保留产物；下一步跟 `resume_next_action` / `acp next`（从最近完整正确状态之后） |
| 删除重开 | abort + 清除 `.ascendc-pilot/uo`（及 runs/context）→ 新 run 从 `prepare_layout` |

**MUST**：与 `scope_confirmation` 一样用可点选框；禁止只在聊天里口头问“要不要继续”。  
**MUST NOT**：未 AskQuestion 就 `--force-new` / 静默 resume。

## 执行循环

1. `acp start uo-init --project <算子目录>`（若需决策 → AskQuestion → `--decision …`）
2. `acp next --project <算子目录>`
3. `acp run-action <action_id> --project <算子目录>`
4. 语义 Action 产出后：`acp run-action <action_id> --finalize`
5. `acp advance <next_phase>`（仅有可信收据时）

用户说「只分析 arch35」时：在 `scope_confirmation` 用  
`acp uo-scope scan --architecture arch35`（不要自己筛目录）。

## Actions

| action_id | 名称 | method | agent | role |
|---|---|---|---|---|
| `prepare_layout` | 创建知识库目录 | `uo-init/prepare-layout` | `deterministic-uo-engine` | `deterministic_engine` |
| `scope_confirmation` | 确认分析范围 | `uo-init/scope-confirmation` | `ascendc-pilot` | `producer` |
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
9. **语义 Action 派发**：必须派声明 actor（如 `uo-semantic-resolve`）；Primary 禁止代写 `uo/ir/**`。Task 须带 `subagent_type`/`agent`=actor 与 `action_id`。禁止把后续 Action 的任务（如 `llm_tasks`/`mark_missing`）塞进当前 Action 的子代理 prompt；禁止把超大 candidates 整包粘进 prompt（只传路径）。

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
   - 一旦调用 `todowrite`：`todos` **必须等于** `todo.todo_sync.items` 全量（长度与每个 `id` 一致）。
   - **禁止**只写当前阶段、禁止省略 `id`、禁止子集覆盖导致其它阶段从面板消失。
   - 任意时刻最多一个 `in_progress`。
5. 状态映射（若只有 `phases[].status`）：`done`→`completed`，`current`→`in_progress`，`pending`→`pending`。工作流 `passed` 后全部 `completed`。
6. **禁止**向用户粘贴或复述：`Workflow TODO`、`todo_md`、`.ascendc-pilot/todo.md`、`状态：running`、`当前阶段`、阶段 checklist、`下一步 Action`、`正在执行 …`。进度只出现在右侧 Todo 面板。

## Runtime loop (primary only)

1. 加载匹配的 workflow skill → `acp start`（若返回 `needs_human_decision`：用 `question`/AskQuestion 可点选框 → `--decision continue|reinit`）→ 立刻 `todowrite`（全量）
2. `acp next` → 取 Action；**仅 items 有变化时**再 `todowrite`；然后执行领域方法（同步与执行同轮并行）
3. `advance` / `rework` / `complete` 后若阶段状态变了 → 再 `todowrite`；否则继续下一步

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `prepare_layout` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/prepare-layout` | `-` | `deterministic-uo-engine` |
| `scope_confirmation` | source-authority,code-access,evidence,language,pilot-control,output-quality | cbm-navigation,source-reading | `uo-init/scope-confirmation` | `uo/scope-confirmation` | `ascendc-pilot` |
| `detect_score_pre` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/detect-score-pre` | `-` | `deterministic-uo-engine` |
| `extract_plan` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/extract-plan` | `uo/extract-plan` | `uo-semantic-resolve` |
| `apply_semantic_patch` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/apply-semantic-patch` | `-` | `deterministic-uo-engine` |
| `rebuild_from_ledger` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/rebuild-from-ledger` | `-` | `deterministic-uo-engine` |
| `detect_score_post` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/detect-score-post` | `-` | `deterministic-uo-engine` |
| `recheck_closure` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/recheck-closure` | `-` | `deterministic-uo-engine` |
| `key_triage` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/key-triage` | `uo/key-triage` | `uo-key-resolve` |
| `key_resolution` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/key-resolution` | `uo/key-resolution` | `uo-key-resolve` |
| `confidence_report` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/confidence-report` | `-` | `deterministic-uo-engine` |
| `confidence_review` | source-authority,code-access,evidence,language,pilot-control,output-quality | structured-review,kb-query | `uo-init/confidence-review` | `uo/confidence-review` | `uo-confidence-review` |
| `export_integrity` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/export-integrity` | `-` | `deterministic-uo-engine` |
| `kb_review` | source-authority,code-access,evidence,language,pilot-control,output-quality | structured-review,kb-query | `uo-init/kb-review` | `uo/kb-review` | `uo-kb-review` |

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
