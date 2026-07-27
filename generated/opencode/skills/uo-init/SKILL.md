---
name: uo-init
description: 首次建立 / 创建本地知识库（UO KB）、建库、初始化算子知识库。 用户提到建立知识库、只分析某架构分支（如 arch35）时加载本 Skill。
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
     - MUST NOT：在 stub 前后夹 REWORK / 失败诊断 / 额外目标长文。
   - **同 Action rework**：必须 **resume 原 Task session**（同一 `action_id` 的已有子代理），**禁止**再开第二个 session。
   - **`extract_plan` 只确认 candidates→`extract_plan.yaml`**；边裁决走 `adjudicate_llm_tasks`→`apply_semantic_patch`（禁止跳步）。
   - Write 被拒后 **禁止**用 bash/`Set-Content`/`>` 绕过围栏写正式 IR。
5. **禁止**用 Glob/Read 自编「文件计数表」代替 `acp uo-scope scan`；`common/` 由扫描脚本向上发现，手数必漏。
6. **进度 / Todo**：遵循公共策略 `pilot-control`（原生 Todo）；勿在本 Skill 硬编码阶段表，勿在主对话贴状态面板。
7. **`extract_plan --finalize`**：会校验 plan 并 `build_layered_kb(host/kernel/tilingkey/bridge)`；大算子可能数分钟无输出，属正常，禁止当卡死打断。

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
# 首次：
Task(subagent_type=<actor_id>):
  <原样粘贴 task_prompt_stub 全文>

# 同 Action rework / checker_gate 重试：
Task(subagent_type=<actor_id>, resume=<原 task session id>):
  <原样粘贴新一轮 task_prompt_stub 全文>
```

禁止：
- 先 Read method/prompt 再改写成更长的 Task
- 粘贴 `llm_tasks.yaml` / 超大 candidates 全文
- 给子代理加「顺便裁决 call_edge」/「REWORK：请 omit …」等额外目标
- rework 时新开第二个 session（必须 resume）

子代理卡要求：启动后**先读** session `prompt.md`。

## 执行循环

1. `acp start uo-init --project <算子目录>`（若需决策 → AskQuestion → `--decision …`）
2. `acp next --project <算子目录>` → **只跑**返回的 `recommended_next_action`（禁止从 `allowed_actions` 跳步）
3. `acp run-action <recommended_id> --project <算子目录>`
4. 语义 Action 产出后：`acp run-action <id> --finalize` → **立刻再** `acp next`  
   （`extract_plan --finalize` 含分层构建，大算子可能数分钟）
5. extract 流水线顺序（硬）：`detect_score_pre` → `extract_plan` → `detect_score_post` → `adjudicate_llm_tasks` → `apply_semantic_patch` → `rebuild_from_ledger` → `recheck_closure`
6. `acp advance <next_phase>`（仅本阶段 pipeline / phase_gates 齐备时）
7. Gate fail → `rework_required`：`retry` 同 Action 时 **resume 原子代理**，stub 原样，禁止加戏诊断文

用户说「只分析 arch35」时：在 `scope_confirmation` 用  
`acp uo-scope scan --architecture arch35`（不要自己筛目录）。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `prepare_layout` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/prepare-layout` | `-` | `kb-layout-v1` |
| `scope_confirmation` | `primary_interactive` | `ascendc-pilot` | `controller` | `uo-init/scope-confirmation` | `uo/scope-confirmation` | `scope-confirmed-v1` |
| `detect_score_pre` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/detect-score-pre` | `-` | `detect-score-pre-v1` |
| `extract_plan` | `subagent` | `uo-semantic-resolve` | `producer` | `uo-init/extract-plan` | `uo/extract-plan` | `extract-plan-v1` |
| `detect_score_post` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/detect-score-post` | `-` | `detect-score-post-v1` |
| `adjudicate_llm_tasks` | `subagent` | `uo-semantic-resolve` | `producer` | `uo-init/adjudicate-llm-tasks` | `uo/adjudicate-llm-tasks` | `semantic-patches-v1` |
| `apply_semantic_patch` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/apply-semantic-patch` | `-` | `semantic-patch-v1` |
| `apply_scope_expansion` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/apply-scope-expansion` | `-` | `scope-expansion-v1` |
| `rebuild_from_ledger` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/rebuild-from-ledger` | `-` | `rebuild-ledger-v1` |
| `recheck_closure` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/recheck-closure` | `-` | `recheck-closure-v1` |
| `key_triage` | `subagent` | `uo-key-resolve` | `producer` | `uo-init/key-triage` | `uo/key-triage` | `key-triage-v1` |
| `key_resolution` | `subagent` | `uo-key-resolve` | `producer` | `uo-init/key-resolution` | `uo/key-resolution` | `input-derivable-patch-v1` |
| `confidence_report` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/confidence-report` | `-` | `confidence-report-v1` |
| `confidence_review` | `subagent` | `uo-confidence-review` | `referee` | `uo-init/confidence-review` | `uo/confidence-review` | `confidence-reason-review-v1` |
| `export_integrity` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-init/export-integrity` | `-` | `integrity-v1` |
| `kb_review` | `subagent` | `uo-kb-review` | `referee` | `uo-init/kb-review` | `uo/kb-review` | `kb-review-v1` |

<!-- END GENERATED ACTIONS -->

Pipeline order is owned by Workflow Spec (`pilot/ascendc_pilot/workflows/specs.py` pipelines).
Do not redefine action order in this Skill.

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
8. bash 优先用工具 `workdir` 指向算子目录；若写 `cd <dir> && acp …`，Pilot 只认末尾纯 `acp` 段（禁止夹杂其它命令）。禁止用 bash/`>`/`Set-Content`/`tee` 写入 `.ascendc-pilot/**` 正式产物以绕过 Write 围栏。**只读定位**允许：`ls`/`Get-ChildItem`/`grep`/`rg`/`Select-String`/`findstr`（无写重定向）；仍不得当高置信证据。
9. **语义 Action 派发**：必须派声明 actor（如 `uo-semantic-resolve`）；Primary 禁止代写 `uo/ir/**`。Task 须带 `subagent_type`/`agent`=actor 与 `action_id`。**Task 正文只能原样使用 prepare 返回的 `task_prompt_stub`**（禁止复述 METHOD、禁止塞额外目标/REWORK 长文、禁止把后续 Action 的 `llm_tasks`/`mark_missing` 或超大 candidates 整包粘进 prompt；**禁止空 prompt / `{}`**）。**同 Action rework 必须 resume 原 Task session**，禁止新开第二个 session。Gate fail → **resume 原 stub** 再派（**校验失败禁止无故 re-prepare / re-propose**，以免 `candidates_sha256` churn）；**禁止**凭子代理摘要声称「无候选 / 无 receiver」而跳过读 `*.summary.yaml` / 全量 candidates；若子代理摘要写明「只改 sha / 证据未改」→ **禁止 finalize**，继续 resume 或先 `--check`；语义 Action 仅 Host **finalize**（禁止 primary 代写 IR）。
9a. **`ARTIFACT_SESSION_MISMATCH` / identity 失败**：禁止派发「FIX ONLY 改 `action_session_id`」类非 stub 正文。合法路径二选一：(1) **resume 原 Task + 原样 stub** 让子代理按合同重写整份产物 identity；(2) 按 `retry_command` **完整 re-prepare** 后，用**新 stub** 派发，由子代理按新 session **整份重写**产物（不得只改 identity 单字段）。`candidate_set_hash` 权威字段名见 adjudicate 合同（勿误写 `patch_candidate_set_hash`）。
10. **Debug 模式（可选）**：`acp debug enable --project <算子目录>` 后自动捕捉工具失败与过长非逻辑思考链，并在子代理结束时导出 session bundle 到 `.ascendc-pilot/debug/exports/`。排查完 `acp debug disable`。手动导出：`acp debug export-session`。
11. **关键参数不明确 → 立刻 AskQuestion**：算子路径（`--project`）、architecture、continue/reinit，以及**当前 workflow 真正要求的**参数（例如 **`tg-init` 的测试脚本路径** `--test-script-root` / `ASCENDC_TEST_SCRIPT_ROOT` / `csv_consumer_root`）缺一不可时，**同一轮**用 `question` 可点选框问清；禁止为猜答案而全库 Glob、读历史 session 考古、长篇「让我想想」。已明确则直接执行，勿重复确认。**`uo-init` / `uo-update` 启动不要求测试脚本路径**——那是 TG 测例契约用的，勿在建库阶段为此打断。

12. **禁止跳步**：`acp next` 返回 `recommended_next_action` 时必须执行该 Action；禁止从 `allowed_actions` 里挑后面的确定性步骤（例如跳过 `detect_score_post`/`adjudicate_llm_tasks` 直接 `apply_semantic_patch`）。语义 Action finalize 后必须立刻再 `acp next`，不要自行猜下一步。
13. **Lease 不变量（全局）**：Action `allowed_write_paths` **必须**可读（签发时自动并入 `allowed_read_paths`）。禁止「能 Write 产物却不能 Read 自检」；勿在个别 skill 里另开例外。

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

## Composed: evidence

# Policy: evidence

## Purpose

关键结论必须可追溯；禁止伪造置信度。本策略对**所有**语义 Action / Agent 生效（经 `DEFAULT_POLICY_IDS` 注入），禁止只在个别 skill 里另写一套证据规则。

## Rules

1. 关键结论必须有 `path:line`、KB reference 或确定性产物证据。
2. 不能以命名猜测闭合 KEY。
3. 不能伪造 `confidence: high`。
4. 推断必须明确标记为 `inference`。
5. 证据不足时保留 `unresolved` / `needs_human`，不得猜测闭合。
6. 仅 `confidence: high` 可闭合 true / false / not_input_derivable 类字段。
7. **高置信 = 源码比对（全局硬规则）**：凡写入 `confidence: high` 或 `source_verified: true` 的结论，必须同时具备：
   - `evidence_source: source|cbm`（禁止 `candidate_only` 冒充 verified）
   - 非空 `evidence_files` + `evidence_lines: [start, end]`（1-based inclusive）
   - `evidence_window_sha256`：磁盘窗口 sha（pad=0；可从候选 `source_window.sha256` 拷贝）
   - `evidence_snippet`：该窗口内**连续**真实源码文本（足够长），**必须为磁盘窗口连续子串**（可去缩进比对）；禁止挑行拼贴
   - `decision_reason`：说明「读了哪段、为何成立」
8. **CBM / search 不是比对**：`search_graph` / `search_code` / 候选表只能定位；定位后必须 `get_code_snippet` 或定向 Read 窗口，再写 snippet。仅有搜索命中不得标 high / source_verified。
9. **证据载体（硬 · AND 不是 OR）**：高置信必须 **同时** 有 `evidence_window_sha256` **与** 连续 `evidence_snippet`。仅 sha、仅 snippet、或 sha 对但 snippet 非连续窗口子串 → Gate / apply **拒绝**。共享校验：`uo.scripts.source_evidence.require_disk_window_proof`。
10. **产品韧性（公共）**：apply 可在 files/lines 可解析时从磁盘窗口（或候选 `source_window.text`）**回填**连续 snippet 与 sha（`enrich_item_evidence_from_disk`）；禁止省略号拼贴残留。回填不是放宽合同，而是消除易碎 YAML。
11. **禁止占位证据**：`candidates_sha256`、snippet、行号不得填 `PLACEHOLDER` / `TODO` / 编造 hash；Gate 必须拒绝。
12. **邻项 / 错窗 sha 视为编造**：`evidence_window_sha256` 必须对应该条目的 `evidence_files`+`evidence_lines`（或候选同窗 `source_window.sha256` / summary 的 `source_window_sha256`）。复用邻居候选的 hash → Gate / apply **拒绝**；若 files/lines/连续 snippet 已正确，apply 可按磁盘窗 **覆盖**错误 sha（`enrich_item_evidence_from_disk`），覆盖不是放宽合同。禁止为捞 sha 而 Grep/findstr 全量大 IR。
13. 校验实现统一走共享模块（`uo.scripts.source_evidence` / `yaml_literal_sanitize`），各 Action finalize **复用**，不得各自发明宽松规则。
14. **`mark_missing` 硬 Gate（公共）**：不得仅以 `score < threshold` / `confidence too low` 作为唯一理由。必须提供机器可核验的 `negative_evidence`（`scope_snapshot_sha256`、`include_closure_status` 对照产物、`queries[]`、`inspected_windows[]+window_sha256`、`absence_kind`）。Gate **不信任**模型自填的 `include_scope_complete: true`，须读 scope/include closure 产物。`triage_category=macro_contract_resolvable` 禁止 `mark_missing`（应交宏合同物化）。校验：`uo.scripts.llm_tasks.validate_mark_missing_patch`。

## Hard Constraints

- MUST：每个闭合结论附证据类型与引用。
- MUST：`confidence: high` ⇒ `source_verified: true` + 磁盘窗口 sha **且** 连续可核验 `evidence_snippet`。
- MUST：`mark_missing` ⇒ 机器可核验 `negative_evidence`；禁止 score-only / 伪 missing。
- MUST NOT：发明证据、行号、KB 节点或 snippet；禁止用「仅 window sha」放行拼贴 snippet。
- MUST NOT：复用邻居候选 / 错窗的 `evidence_window_sha256`（邻项 hash 视为编造）。
- MUST NOT：用「命名像 / 候选表有 / search 命中」当作 high 的唯一依据。
- MUST NOT：对 `macro_contract_resolvable` 任务写 `mark_missing`。
- MUST NOT：在个别 skill prompt 里弱化或覆盖本策略；skill 只可引用本策略，不可另立例外。

## Composed: code-access

# Policy: code-access

## Purpose

约束代码语义查阅方式，禁止无边界全仓扫描；与 `evidence` 策略配套——**查到 ≠ 已比对**。

## Rules

1. 理解普通函数/类/调用关系时优先使用 CBM（MCP codebase-memory）。
2. 已有明确 `file_path` 时可直接打开目标源码窗口。
3. Grep / rg / `Select-String` **只用于定位**（OpenCode Grep 或 bash 只读搜索均允许），不可单独作为复杂语义结论 / high / `source_verified` 的唯一证据。Windows `findstr` 路径须用反斜杠（`D:\…\file`）；正斜杠 `D:/…` 会被当成开关导致「无法打开」。
4. 不允许无边界扫描整个仓库或父仓。**大 IR 公共模式**：prepare 须写 `*.summary.yaml`（`section_lines` + `must` + 本步导航字段如 `source_window_sha256` / `non_sink_root_names`；共享 `uo.scripts.ir_summary`）；dispatch `read` 把 summary（及 `*.rework_hints.yaml`）排在全量 IR 前；Host stub 见 `*.summary.yaml` 即注入 `MUST_READ_ORDER`。禁止先 Grep/offset 扫整份 candidates。
5. CBM 空结果不代表符号不存在；须回退定向源码阅读或受控 source_closure。
6. 禁止索引父仓；`project` 必须等于 `index_meta.cbm_project`。
7. 宏表 / 注册宏 / Host 谓词 / CMake / 模板参数绑定：以确定性脚本 + 范围内 Read 为主路径，CBM 为 MAY。
8. 官方文档只提供接口/宏契约；权威序：算子源码 → 目标 CANN 版本文档 → latest → 其它。文档不得创建无源码边。
9. CMake/构建文件不得进入 CBM source index；走 `extract_build_evidence`。
10. 符号身份使用 `semantic_identity` / `entrypoint_graph` 稳定 id，禁止短名唯一键。
11. **标准读码路径（全局）**：`search_graph` / `search_code` 定位 → `get_code_snippet(qualified_name=...)` 或定向 Read **函数体窗口** → 再写结论。禁止「最省事」捷径（只 search 不拉 snippet、整文件 dump、凭记忆编 snippet）。
12. **窗口预算**：只读当前结论所需最小窗口（函数/宏块附近）；禁止整文件倾倒进上下文。
13. 高置信结论的源码比对要求见 `evidence` 策略（本策略不另开例外）。

## Hard Constraints

- MUST：语义结论前完成「定位 → 窗口读」；高置信前完成「窗口 ↔ snippet 比对」。
- MUST NOT：`index_repository(repo_path=父仓)`。
- MUST NOT：整文件 dump 或无关大段源码加载。
- MUST NOT：把 CBM 空结果当作「不可解」的唯一证据。
- MUST NOT：把 BuildConfig / CompileMacro / PlatformInfo 伪装成 CSV 可控输入。
- MUST NOT：恢复 `roles.*.selected` 单入口契约。
- MUST NOT：candidate 边假闭合主链；patch 直接改写派生图。
- MUST NOT：因评分低自动把主链必需缺口降为 informational。
- MUST NOT：仅用 search 命中标 `source_verified` / `confidence: high`。
- MUST：LLM 消歧仅在候选窗内；过期 snapshot/candidate hash 的 patch 必须拒绝。

## Composed: source-authority

# Policy: source-authority

## Purpose

统一权威源优先级，防止模型记忆与命名猜测覆盖证据。

## Priority (high → low)

1. 当前源码（定向 `path:line` 阅读）
2. 当前确定性产物（Pilot 签发收据、Checker 报告、引擎输出）
3. 当前 UO / TG KB（定稿或本 run 内 IR）
4. 本地稳定记忆（已验证）
5. 候选记忆 / 未验证笔记
6. 模型记忆与命名直觉

## Hard Constraints

- MUST：高优先级证据冲突时，以更高优先级为准并记录冲突。
- MUST：声称「已核对源码」时，证据层级必须落到第 1 级（定向 `path:line` 窗口），并满足 `evidence` 策略的 snippet 磁盘比对。
- MUST NOT：用模型记忆或命名猜测闭合 KEY / 合同字段。
- MUST NOT：把过期本地记忆当作当前源码事实。
- MUST NOT：用候选表 / 搜索摘要冒充第 1 级源码权威。

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `prepare_layout` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/prepare-layout` | `-` | `deterministic-uo-engine` |
| `scope_confirmation` | source-authority,code-access,evidence,language,pilot-control,output-quality | cbm-navigation,source-reading | `uo-init/scope-confirmation` | `uo/scope-confirmation` | `ascendc-pilot` |
| `detect_score_pre` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/detect-score-pre` | `-` | `deterministic-uo-engine` |
| `extract_plan` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/extract-plan` | `uo/extract-plan` | `uo-semantic-resolve` |
| `detect_score_post` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/detect-score-post` | `-` | `deterministic-uo-engine` |
| `adjudicate_llm_tasks` | source-authority,code-access,evidence,language,pilot-control,output-quality | source-reading,cbm-navigation,kb-query,semantic-resolution | `uo-init/adjudicate-llm-tasks` | `uo/adjudicate-llm-tasks` | `uo-semantic-resolve` |
| `apply_semantic_patch` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/apply-semantic-patch` | `-` | `deterministic-uo-engine` |
| `apply_scope_expansion` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/apply-scope-expansion` | `-` | `deterministic-uo-engine` |
| `rebuild_from_ledger` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/rebuild-from-ledger` | `-` | `deterministic-uo-engine` |
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
| `scope_confirmation` | `actions/scope-confirmation/METHOD.md` | `prompts/tasks/uo/scope-confirmation.md` | `scope-confirmed-v1` | `controller` |
| `detect_score_pre` | `actions/detect-score-pre/METHOD.md` | `-` | `detect-score-pre-v1` | `deterministic_engine` |
| `extract_plan` | `actions/extract-plan/METHOD.md` | `prompts/tasks/uo/extract-plan.md` | `extract-plan-v1` | `producer` |
| `detect_score_post` | `actions/detect-score-post/METHOD.md` | `-` | `detect-score-post-v1` | `deterministic_engine` |
| `adjudicate_llm_tasks` | `actions/adjudicate-llm-tasks/METHOD.md` | `prompts/tasks/uo/adjudicate-llm-tasks.md` | `semantic-patches-v1` | `producer` |
| `apply_semantic_patch` | `actions/apply-semantic-patch/METHOD.md` | `-` | `semantic-patch-v1` | `deterministic_engine` |
| `apply_scope_expansion` | `actions/apply-scope-expansion/METHOD.md` | `-` | `scope-expansion-v1` | `deterministic_engine` |
| `rebuild_from_ledger` | `actions/rebuild-from-ledger/METHOD.md` | `-` | `rebuild-ledger-v1` | `deterministic_engine` |
| `recheck_closure` | `actions/recheck-closure/METHOD.md` | `-` | `recheck-closure-v1` | `deterministic_engine` |
| `key_triage` | `actions/key-triage/METHOD.md` | `prompts/tasks/uo/key-triage.md` | `key-triage-v1` | `producer` |
| `key_resolution` | `actions/key-resolution/METHOD.md` | `prompts/tasks/uo/key-resolution.md` | `input-derivable-patch-v1` | `producer` |
| `confidence_report` | `actions/confidence-report/METHOD.md` | `-` | `confidence-report-v1` | `deterministic_engine` |
| `confidence_review` | `actions/confidence-review/METHOD.md` | `prompts/tasks/uo/confidence-review.md` | `confidence-reason-review-v1` | `referee` |
| `export_integrity` | `actions/export-integrity/METHOD.md` | `-` | `integrity-v1` | `deterministic_engine` |
| `kb_review` | `actions/kb-review/METHOD.md` | `prompts/tasks/uo/kb-review.md` | `kb-review-v1` | `referee` |
