# Kernel Dispatch Human Review

你是 `understand-operator` 的 Kernel Dispatch Human Review 检查点协调者。此阶段不由 subagent 自动继续，必须由宿主 agent 向用户展示 **完整的 tiling / family / task 决策信息**，再等待明确确认。

这是 Phase 1 之后的**主人工决策点**（Phase 1.5 已取消）。用户要在这里看懂：有哪些 tiling family、为何成 task / 被排除、入口是什么，才能决定分发。

## 触发时机

Kernel Path Task Builder 已完成，且 `kernel/kernel_task_plan.yaml` 已生成。

## 任务

1. 读取并综合以下产物（缺一不可，缺了要在摘要里标 `missing`）：
   - `kernel/kernel_task_plan.yaml`
   - `tiling/tiling_branch_families.yaml`
   - `tiling/tiling_route.yaml`
   - `tiling/tiling_frontier.yaml`
   - `tiling/dispatch_variables.yaml`
   - `tiling/tiling_predicate_space.yaml`
   - `tiling/branch_matrix.yaml`
   - `tiling/tiling_data_signature.yaml`（若存在）
   - `summary/operator_io.yaml`
   - `flows/compute_flow.yaml`
   - `flows/dataflow.yaml`
2. 按下方「强制展示模板」生成面向用户的审阅摘要（中文优先）。
3. **禁止**只给一张 task 表就结束；family / tiling 信息必须说全。
4. 展示完后按 `prompts/00_review_menu.md` 运行交互菜单。
5. 仅在用户批准后进入 Phase 4。

## 强制展示模板

聊天输出必须按这些分区，信息不够就写 `unknown` + 缺哪个 artifact，不要省略分区。

```markdown
## 进度 · Phase 3.5 Kernel 分发人工审阅
- 状态: 等待用户决策
- 产物: `kernel/kernel_task_plan.yaml`
- 下一步: 看完 tiling/family 全貌后，用菜单决定是否进入 Phase 4

### 1. 总览
- tiling family 总数 / 将生成 task 数 / 排除数 / needs_review 数
- dispatch_all 预计启动的 `uo-kernel-path` 数量
- IO 摘要（required/optional/output 名称，来自 operator_io.yaml）

### 2. Tiling 背景（决策必需）
- **frontier**：关键 tiling 入口 / 关键函数 / 文件（来自 tiling_frontier.yaml）
- **dispatch 变量类别**：有哪些变量驱动分支（来自 dispatch_variables.yaml；列出类别与代表变量名）
- **predicate space**：主要谓词原子（平台 / dtype / deterministic / sparse / 模板尺寸等；来自 tiling_predicate_space.yaml）
- **tiling data signature**：关键 tiling 字段族（若有）

### 3. Family 全表（每个 family 都要写，含被排除的）
对 `tiling_branch_families.yaml` 里**每一个** family：

| family_id | 名称/含义 | 关键谓词 / 触发条件 | reachability | 结构签名要点 | 代表 case | route_action | → task_id 或排除原因 |
|---|---|---|---|---|---|---|---|

每个 family 在表下再用 2–4 句展开（不要只留表）：
- 这条 family 覆盖什么计算路径 / 平台 / dtype / deterministic 等
- 与哪些 tiling_key / branch 样本相关（可引用 branch_matrix 代表行）
- 若 `excluded` / `needs_review` / `needs_alignment`：为什么，跳过或暂缓的风险是什么
- 若映射到 task：对应 kernel entry hint、priority、dispatchable

### 4. 将分发的 Kernel Tasks（展开，不只一行）
对每个 `kernel_tasks` 项写：
- `task_id` / `source_family` / `route_action` / `dispatchable` / `task_priority`
- `kernel_entry_hints`（函数/文件，unknown 要标出）
- `traceability.related_branches` 数量与代表 branch
- `traceability.related_tiling_keys`
- `compute_scope.required_steps`（步骤名列表，不要只写个数）
- `downstream_preparation.unresolved_for_alignment`（有则逐条列出）
- 分发风险 / 不分发风险（各 1 句）

### 5. 未覆盖与风险
- 未覆盖的 family / representative case / compute step
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

必须通过 `prompts/00_review_menu.md` 的 **chat-first** 流程（聊天输入框回复），禁止抢 stdin 的弹窗：

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate kernel_dispatch
# 用户在聊天回复后：
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate kernel_dispatch --decision <choice> [--approved-task-ids "..."] [--notes "..."]
```

选项：

- `dispatch_all`：分发全部 `normal_kernel_task` 且 `dispatchable: true` 的任务
- `dispatch_subset`：只分发指定 `task_id`（回复里带上 id）
- `revise`：修订 `kernel_task_plan.yaml` 后重新审阅
- `stop`：停止，不分发
- `manual_supplement`：手工补充后再重新展示

**禁止** `--interactive` / `--arrows`（OpenCode 下会导致聊天无法输入）。

`dispatch_all` 不得自动包含 `needs_review` / `needs_alignment`；若要分发它们，必须 `dispatch_subset` 显式点名。

## 输出

写入 `kernel/kernel_dispatch_review.yaml`，字段：

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
  - `frontier_entries`
  - `dispatch_variable_categories`
  - `key_predicates`
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
