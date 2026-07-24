---
name: uo-init
description: >-
  首次建立 / 创建本地知识库（UO KB）、建库、初始化算子知识库。
  用户提到建立知识库、只分析某架构分支（如 arch35）时加载本 Skill。
  Pilot 管阶段；加载后执行 acp start uo-init。
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

| action_id | 名称 | method | agent |
|---|---|---|---|
| `prepare_layout` | 创建知识库目录 | `uo-init/prepare-layout` | `deterministic-uo-engine` |
| `scope_confirmation` | 确认分析范围 | `uo-init/scope-confirmation` | `ascendc-pilot` |
| `detect_score_pre` | 抽取前评分 | `uo-init/detect-score-pre` | `deterministic-uo-engine` |
| `extract_plan` | 抽取计划与分层 IR | `uo-init/extract-plan` | `uo-semantic-resolve` |
| `apply_semantic_patch` | 应用语义补丁 | `uo-init/apply-semantic-patch` | `deterministic-uo-engine` |
| `rebuild_from_ledger` | 从账本重建图 | `uo-init/rebuild-from-ledger` | `deterministic-uo-engine` |
| `detect_score_post` | 抽取后评分 | `uo-init/detect-score-post` | `deterministic-uo-engine` |
| `recheck_closure` | 闭合复核 | `uo-init/recheck-closure` | `deterministic-uo-engine` |
| `key_triage` | KEY 粗分 | `uo-init/key-triage` | `uo-key-resolve` |
| `key_resolution` | KEY 语义闭合 | `uo-init/key-resolution` | `uo-key-resolve` |
| `confidence_report` | 生成置信度报告 | `uo-init/confidence-report` | `deterministic-uo-engine` |
| `confidence_review` | 置信度原因审查 | `uo-init/confidence-review` | `uo-confidence-review` |
| `export_integrity` | 导出与完整性校验 | `uo-init/export-integrity` | `deterministic-uo-engine` |
| `kb_review` | KB 产物审查 | `uo-init/kb-review` | `uo-kb-review` |
