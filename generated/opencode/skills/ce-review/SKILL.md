---
name: ce-review
description: 基于 KB 的代码审查 / code review / 查 bug。用户要审查算子代码时加载。 Pilot 管阶段；加载后执行 acp start
  ce-review。
---

# ce-review

基于 KB 的代码审查。

本 Skill 不定义工作流阶段。执行时：

1. 调用 `acp start`（同 workflow 活动 run 则复用）；
2. 调用 `acp next`；
3. 对返回的 action_id 调用 `acp run-action <action_id>`（prepare；确定性 Action 会自动 finalize）；
4. 语义 Action：按 Runtime Bundle 派发声明 actor，产出后调用 `acp run-action <action_id> --finalize`；
5. 调用 `acp advance`（仅消费 run-action 签发的可信收据）。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `code_review` | `subagent` | `ce-reviewer` | `readonly_reviewer` | `ce-review/code-review` | `ce/code-review` | `code-review-v1` |

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
8. bash 优先用工具 `workdir` 指向算子目录；若写 `cd <dir> && acp …`，Pilot 只认末尾纯 `acp` 段（禁止夹杂其它命令）。禁止用 bash/`>`/`Set-Content`/`tee` 写入 `.ascendc-pilot/**` 正式产物以绕过 Write 围栏。**只读定位**允许：`ls`/`Get-ChildItem`/`grep`/`rg`/`Select-String`/`findstr`（无写重定向）；仍不得当高置信证据。
9. **语义 Action 派发**：必须派声明 actor（如 `uo-semantic-resolve`）；Primary 禁止代写 `uo/ir/**`。Task 须带 `subagent_type`/`agent`=actor 与 `action_id`。**Task 正文只能原样使用 prepare 返回的 `task_prompt_stub`**（禁止复述 METHOD、禁止塞额外目标/REWORK 长文、禁止把后续 Action 的 `llm_tasks`/`mark_missing` 或超大 candidates 整包粘进 prompt；**禁止空 prompt / `{}`**）。**同 Action rework 必须 resume 原 Task session**，禁止新开第二个 session。Gate fail → **resume 原 stub** 再派（**校验失败禁止无故 re-prepare / re-propose**，以免 `candidates_sha256` churn）；**禁止**凭子代理摘要声称「无候选 / 无 receiver」而跳过读 `*.summary.yaml` / 全量 candidates；若子代理摘要写明「只改 sha / 证据未改」→ **禁止 finalize**，继续 resume 或先 `--check`；语义 Action 仅 Host **finalize**（禁止 primary 代写 IR）。
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
12. 校验实现统一走共享模块（`uo.scripts.source_evidence` / `yaml_literal_sanitize`），各 Action finalize **复用**，不得各自发明宽松规则。

## Hard Constraints

- MUST：每个闭合结论附证据类型与引用。
- MUST：`confidence: high` ⇒ `source_verified: true` + 磁盘窗口 sha **且** 连续可核验 `evidence_snippet`。
- MUST NOT：发明证据、行号、KB 节点或 snippet；禁止用「仅 window sha」放行拼贴 snippet。
- MUST NOT：用「命名像 / 候选表有 / search 命中」当作 high 的唯一依据。
- MUST NOT：在个别 skill prompt 里弱化或覆盖本策略；skill 只可引用本策略，不可另立例外。

## Composed: code-access

# Policy: code-access

## Purpose

约束代码语义查阅方式，禁止无边界全仓扫描；与 `evidence` 策略配套——**查到 ≠ 已比对**。

## Rules

1. 理解普通函数/类/调用关系时优先使用 CBM（MCP codebase-memory）。
2. 已有明确 `file_path` 时可直接打开目标源码窗口。
3. Grep / rg / `Select-String` **只用于定位**（OpenCode Grep 或 bash 只读搜索均允许），不可单独作为复杂语义结论 / high / `source_verified` 的唯一证据。
4. 不允许无边界扫描整个仓库或父仓。**大 IR 公共模式**：prepare 须写 `*.summary.yaml`（`section_lines` + `must`；共享 `uo.scripts.ir_summary`）；dispatch `read` 把 summary（及 `*.rework_hints.yaml`）排在全量 IR 前；Host stub 见 `*.summary.yaml` 即注入 `MUST_READ_ORDER`。禁止先 Grep/offset 扫整份 candidates。
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
| `code_review` | source-authority,code-access,evidence,language,pilot-control,output-quality | structured-review,kb-query,cbm-navigation,source-reading | `ce-review/code-review` | `ce/code-review` | `ce-reviewer` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `code_review` | `actions/code-review/METHOD.md` | `prompts/tasks/ce/code-review.md` | `code-review-v1` | `readonly_reviewer` |
