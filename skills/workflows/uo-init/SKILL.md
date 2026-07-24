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
0.5. **关键启动参数不明确 → 立刻 AskQuestion，禁止探查纠结**（缺一就问，同一轮 `question`）：
   - **算子目录**（`--project`）：用户说「这个算子 / 建库」但未给出**单一**算子根，且 cwd 不是算子包时 → AskQuestion 点选/粘贴路径。
   - **architecture**：用户未说只要某分支、且不能默认时 → AskQuestion（常见：`arch35`）。
   - **测试脚本路径不属于 uo-init 启动必填**（那是 `tg-init` 测例契约用的）。本 workflow **禁止**为 `--test-script-root` 打断建库；用户未提则不要问、不要猜。
   - **MUST NOT**：为猜算子目录而 Glob 全仓库、枚举几十个 arch35、读 session 考古、长篇「让我想想」。
   - **MUST NOT**：在未确认 `--project` 前执行 `acp start` / scope / 读源码建库。
   - 用户已给出算子路径，或 cwd/`--project` 已是唯一算子根，且 arch 已明确或可安全默认 → 直接 `acp start`，勿再问。
1. **`acp` 是真实 CLI**（本机已安装），不是概念步骤，**禁止**“按 METHOD 手工模拟工作流”。
2. **禁止跳步**：必须先 `acp start` → `acp next` → 当前 `action_id`；不得一上来做 scope 或读源码建 KB。
3. **确定性 Action**（如 `prepare_layout`）：只跑 `acp run-action <id>`，会自动 finalize。
4. **语义 Action**：`run-action` 准备 → 按 Bundle **派发声明 actor**（如 `uo-semantic-resolve`）→ actor 写合同产物 → `--finalize`。
   - Primary **禁止**自己 Write `uo/ir/**`（会 `PRIMARY_PROTECTED_WRITE`）。
   - Task 须带 `subagent_type`/`agent` = Bundle 的 `actor_id`，并带上 `action_id`。
   - **派发正文硬规则**：Task prompt **只能**用 prepare 返回的 `task_prompt_stub`（或 `session/task_prompt_stub.md`）原样粘贴。
     - MUST NOT：自己复述/改写 METHOD；MUST NOT：先 Read method/prompt 再二编长 prompt。
     - MUST NOT：把 `llm_tasks`/`mark_missing`/超大 candidates **整包**粘进 Task（只传路径）。
   - **`extract_plan` 只确认 candidates→`extract_plan.yaml`**；边裁决走 `adjudicate_llm_tasks`→`apply_semantic_patch`（禁止跳步）。
   - Write 被拒后 **禁止**用 bash/`Set-Content`/`>` 绕过围栏写正式 IR。
5. **禁止**用 Glob/Read 自编「文件计数表」代替 `acp uo-scope scan`；`common/` 由扫描脚本向上发现，手数必漏。
6. **进度 / Todo**：遵循公共策略 `pilot-control`（原生 Todo）；勿在本 Skill 硬编码阶段表，勿在主对话贴状态面板。

## 启动前：关键参数确认（歧义时立刻问）

```text
# 歧义示例：cwd=D:\PR-review，用户只说「为这个算子建库只要 arch35」
→ 立刻 question/AskQuestion，只问清：
  1) 算子目录（--project）
  2) architecture（若未说）
# 确认后（勿因缺测试脚本路径而停）：
acp start uo-init --project <算子目录> --architecture arch35
```

**禁止**先 Glob 全树再写长思考链。

## Debug 模式（可选）

排查 Host 绕弯 / 工具失败 / 子代理收尾时开启：

```text
acp debug enable --project <算子目录>
# 可选：ASCENDC_DEBUG=1
acp debug status --project <算子目录>
acp debug export-session --project <算子目录>   # 手动打包
acp debug disable --project <算子目录>
```

开启后：
- **工具调用失败** → 写入 `.ascendc-pilot/debug/anomalies.jsonl`（Cursor `postToolUseFailure` / OpenCode `tool.execute.after`）
- **过长非逻辑思考链**（长 + meta 纠结词密集）→ 同文件 `long_nonlogical_thought`
- **子代理 Task 结束** → 自动导出 `.ascendc-pilot/debug/exports/<stamp>_…/`（含 events/observations/anomalies + `DEBUG_REPORT.md`）

## 启动前：未完成 run → AskQuestion（与 scope 同款可点选框）

算子目录若已有活动 `uo-init` run 或残留 `.ascendc-pilot/uo`，**禁止静默复用 / 自动删除**。

```text
acp start uo-init --project <算子目录>
# 若返回 needs_human_decision=true / EXISTING_RUN_NEEDS_DECISION：
# 1) 把 run_summary.summary_text_zh（完整/中断点）贴给用户
# 2) 必须调用 OpenCode `question`（AskQuestion），options 用返回的 ask_question.options
# 3) 等人点选后再执行：
acp start uo-init --project <算子目录> --decision continue   # 清理残缺 → 回退完整点 → 继续
acp start uo-init --project <算子目录> --decision reinit     # 删除 uo 产物后重新 init
```

可选先查摘要：`acp run-summary --project <算子目录>`。

| 选项 | 含义 |
|---|---|
| 继续上次 | **先检查中断步骤是否有失败/残缺产物并清理**（如无效 `extract_plan.yaml`、半成品 host/kernel 图、失败 session/lease）；保留上游已 finalize 产物；回退到最近完整正确状态后再 `resume_next_action` / `acp next` |
| 删除重开 | abort + 清除 `.ascendc-pilot/uo`（及 runs/context）→ 新 run 从 `prepare_layout` |

**MUST**：与 `scope_confirmation` 一样用可点选框；禁止只在聊天里口头问“要不要继续”。  
**MUST NOT**：未 AskQuestion 就 `--force-new` / 静默 resume。

## 语义 Action 派发模板（短 · 禁止加戏）

`acp run-action <id>` 成功后，JSON 含 `task_prompt_stub`。派发时：

```text
Task(subagent_type=<actor_id>):
  <原样粘贴 task_prompt_stub 全文>
```

禁止：
- 先 Read method/prompt 再改写成更长的 Task
- 粘贴 `llm_tasks.yaml` / 超大 candidates 全文
- 给子代理加「顺便裁决 call_edge」等额外目标

子代理卡要求：启动后**先读** session `prompt.md`。

## 执行循环

1. `acp start uo-init --project <算子目录>`（若需决策 → AskQuestion → `--decision …`）
2. `acp next --project <算子目录>` → **只跑**返回的 `recommended_next_action`（禁止从 `allowed_actions` 跳步）
3. `acp run-action <recommended_id> --project <算子目录>`
4. 语义 Action 产出后：`acp run-action <id> --finalize` → **立刻再** `acp next`
5. extract 流水线顺序（硬）：`detect_score_pre` → `extract_plan` → `detect_score_post` → `adjudicate_llm_tasks` → `apply_semantic_patch` → `rebuild_from_ledger` → `recheck_closure`
6. `acp advance <next_phase>`（仅本阶段 pipeline / phase_gates 齐备时）

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
