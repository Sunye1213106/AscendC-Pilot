# Kernel Dispatch Human Review

你是 `understand-operator` 的 Kernel Dispatch Human Review 检查点协调者。此阶段不由 subagent 自动继续，必须由宿主 agent 向用户展示 **完整的 tiling / family / task 决策信息**，再等待明确确认。

这是 Phase 1 之后的**主人工决策点**（Phase 1.5 已取消）。用户要在这里看懂：有哪些 tiling family、为何成 task / 被排除、入口是什么，才能决定分发。

## 触发时机

Kernel Path Task Builder 已完成，且 `kernel/paths.yaml` skeleton 已生成。

## 任务

1. 读取并综合以下产物（缺一不可，缺了要在摘要里标 `missing`）：
   - `kernel/paths.yaml`
   - `tiling/route.md`
   - `tiling/index.yaml`
   - `tiling/families.yaml`
   - `tiling/key_space.yaml`
   - `tiling/data_model.yaml`
   - `tiling/coverage_model.yaml`（seed_cases 仅作代表样本）
   - `tiling/evidence_index.yaml`（按需，默认不展开全文）
   - `operator.yaml`
   - `flow/compute_graph.yaml`
   - `flow/dataflow.yaml`
2. 按下方「强制展示模板」生成面向用户的审阅摘要（**必须中文**，项目默认语言）。
3. **禁止**只给一张 task 表就结束；family / tiling 信息必须说全。
4. 展示完后按 `prompts/00_review_menu.md` 运行交互菜单。
5. 仅在用户批准后进入 Phase 4。

## 强制展示模板

聊天输出必须按这些分区，信息不够就写 `unknown` + 缺哪个 artifact，不要省略分区。

```markdown
## 进度 · Phase 3.5 Kernel 分发人工审阅
- 状态: 等待用户决策
- 产物: `kernel/paths.yaml`
- 下一步: 看完 tiling/family 全貌后，用菜单决定是否进入 Phase 4

### 1. 总览
- tiling family 总数 / 将生成 task 数 / 排除数 / needs_review 数
- dispatch_all 预计启动的 `uo-kernel-path` 数量
- IO 摘要（required/optional/output 名称，来自 operator.yaml）
- 提醒：family coverage != tiling_key coverage；seed_cases != full key enumeration

### 2. Tiling 背景（决策必需）
- **entry / dispatch**：tiling entry 与 top-level dispatch（来自 tiling/route.md、families.yaml.dispatch_tree）
- **variables（Step 1）**：`tiling_mechanism` 概述 + 变量数与 impact_classification 分布（来自 variables.yaml）
- **key space**：tiling_key 编码宏、fields_order、关键 domain（来自 key_space.yaml；不要用 family 数代替）
- **key 逻辑关系（Step 2 / TestGenerate）**（来自 constraints.yaml + coverage_model.yaml）：
  - `relations` 按 type 计数（mutex/implies/requires/…）与是否有 evidence_gap
  - `tiling_key_pruning` / `tiling_key_merging` 是否已回答（true/false/unknown）
  - `input_realization` 条数，是否覆盖可达 family key_pattern
  - `derived_fields` / `independent:false` 是否标明非自由维度
  - key-level `key_unreachable` vs family-level unreachable
- **data model**：always/conditional tilingdata blocks、varlen numeric overlay（来自 data_model.yaml）
- **coverage obligations**：family / key_field / key_relation（含 must_cover）/ input_realization / tilingdata 债务摘要（来自 coverage_model.yaml）

### 3. Family 全表（每个 family 都要写，含被排除的）
对 `families.yaml` 里**每一个** family：

| family_id | 名称/含义 | 关键谓词 / 触发条件 | reachability | struct_signature | key_pattern | seed case | route_action | → task_id 或排除原因 |
|---|---|---|---|---|---|---|---|---|

每个 family 在表下再用 2–4 句展开（不要只留表）：
- 这条 family 覆盖什么计算路径 / 平台 / dtype / deterministic 等
- 与哪些 tiling_key field / seed_cases 相关（seed 只是代表样本）
- 若 `has_dedicated_key_bit: false`（如 varlen）：说明共享 key、tilingdata 数值不同
- 若 `excluded` / `needs_review` / `needs_alignment` / `unreachable`：为什么，跳过或暂缓的风险是什么
- 若映射到 task：对应 kernel entry hint、priority、dispatchable

### 4. 将分发的 Kernel Paths（展开，不只一行）
对 `kernel/paths.yaml` 中每个 `kernel_paths.Kxxx`（或等价 task）写：
- `id` / `source_family` / `route_action` / `reachability` / `task_priority`（若有）
- `entry`（函数/文件，unknown 要标出）
- `tiling` refs / representative_cases
- `compute_scope.required_steps`（步骤名列表，不要只写个数）
- risks / unresolved（有则逐条列出）
- 分发风险 / 不分发风险（各 1 句）

### 5. 未覆盖与风险
- 未覆盖的 family / seed case / compute step
- 高风险或 `unknown` 入口任务
- 建议用户重点确认的 3–5 点（每点写清：确认什么、不同选择影响什么）

### 6. 请选择（chat-first）
请在聊天输入框回复选项名或序号，例如：`dispatch_all` / `2` / `manual_supplement: ...`
不要启动会抢键盘的终端弹窗。
```

## 人工确认问题展示要求

对 `needs_review` / `needs_alignment` / `excluded` / 高风险 task，必须展开：

- 当前是什么（family + task + entry）
- 为什么需要确认
- 现在 dispatch 的误判风险
- 跳过会导致哪些 kernel path / 测试提示缺失
- 需要用户明确：`dispatch` / `skip` / `revise split` / 补充范围
- 保守建议
- 证据路径（artifact 字段）

## 向用户提出的问题

必须通过 `prompts/00_review_menu.md` 的 **Plan 风格选择 UI**（OpenCode `question` / Cursor AskQuestion）：

1. 先展示完整 tiling/family 摘要
2. 弹出单选；**最后一项支持输入**：
   - `dispatch_all`
   - `dispatch_subset`（选后在输入里写 task_id，或再追问一次）
   - `revise`
   - `stop`
   - `manual_supplement` — 手工补充（我来输入）
3. 用户确认后落盘：

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate kernel_dispatch --decision <choice> [--approved-task-ids "..."] [--notes "..."]
```

**禁止** `--interactive` / `--arrows` 作为默认路径。

`dispatch_all` 不得自动包含 `needs_review` / `needs_alignment`；若要分发它们，必须 `dispatch_subset` 显式点名。

## 输出

写入 `human/kernel_dispatch_review.yaml`，字段：

- `checkpoint`: `kernel_dispatch`
- `status`: `pending` | `approved` | `rejected` | `revision_requested`
- `decision`: `dispatch_all` | `dispatch_subset` | `revise` | `stop` | `manual_supplement`
- `reviewer` / `reviewed_at` / `comments`
- `task_count`
- `dispatchable_task_ids` / `non_dispatchable_task_ids` / `needs_review_task_ids`
- `approved_task_ids` / `rejected_task_ids`
- `family_coverage_summary`:
  - `total_families`
  - `task_mapped_families`
  - `excluded_families`
  - `needs_review_families`
- `tiling_brief`:
  - `entry_and_dispatch`
  - `tiling_variables`（variable_count、impact_classification 分布）
  - `key_space_fields`
  - `key_logic_relations`（relations by type、pruning/merging 是否回答、input_realization 覆盖、key vs family unreachable）
  - `data_model_blocks`
  - `coverage_obligation_summary`
- `summary`:
  - `high_priority_tasks`
  - `unknown_kernel_entry_tasks`
  - `uncovered_families`
  - `uncovered_compute_steps`

## 闸门规则

- 批准前禁止启动任何 Kernel Path Agent。
- `stop` → 结束并汇报产物位置。
- `revise` / `manual_supplement` → 不得进 Phase 4，直到再次审阅通过。
- Phase 4 只能处理 `approved_task_ids`。
- 若摘要缺少「Family 全表」或「Tiling 背景」，视为审阅未完成，不得调用菜单进入下一阶段。
