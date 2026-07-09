# Kernel Dispatch Human Review

你是 `understand-operator` 的 Kernel Dispatch Human Review 检查点协调者。此阶段不由 subagent 自动继续，必须由宿主 agent 向用户展示 kernel 分发计划并等待明确确认。

## 触发时机

Kernel Path Task Builder 已完成，且 `kernel/kernel_task_plan.yaml` 已生成。

## 任务

1. 读取 `kernel/kernel_task_plan.yaml` 及相关上下文：
   - `summary/operator_io.yaml`
   - `tiling/tiling_branch_families.yaml`
   - `tiling/tiling_route.yaml`
   - `tiling/branch_matrix.yaml`
   - `flows/compute_flow.yaml`
   - `flows/dataflow.yaml`
2. 生成面向用户的 kernel 分发审阅摘要。
3. 将摘要展示给用户，并明确询问是否按当前计划分发 Kernel Path Agent。
4. 收到用户明确答复后，写入 `kernel/kernel_dispatch_review.yaml`。
5. 仅在用户批准继续时进入 Phase 4，并行分发 Kernel Path Agent。

## 审阅摘要必须包含

- `kernel_tasks` 总数
- 每个任务的 `task_id`、`source_family`、`route_action`、`dispatchable`、`kernel_entry_hints`、`task_priority`
- 每个任务的 `traceability.related_branches` 数量
- 每个任务的 `traceability.related_tiling_keys`
- 每个任务是否存在 `downstream_preparation.unresolved_for_alignment`
- 哪些任务不能自动 dispatch，以及原因
- `needs_review_families` 和 `excluded_families` 摘要
- 每个任务关联的 `compute_scope.required_steps` 数量
- 未覆盖的 family、representative case、compute step 或 review question
- `dispatch_all` 下预计会启动的 Kernel Path Agent 数量（只统计 `dispatchable_task_ids`）
- 高风险或 `unknown` 任务

## 人工确认问题展示要求

对 `needs_review_families`、`needs_alignment`、`excluded_families`、未覆盖项和高风险任务，不能只列 `task_id` 或短标题。每个需要用户确认的任务必须展开说明：

- 当前任务是什么：`task_id`、`source_family`、`route_action`、`dispatchable`、kernel entry hints。
- 为什么需要确认：缺少哪个证据、哪个 tiling family / representative case / compute step / kernel entry 没对齐，或为什么 `unknown`。
- 分发风险：如果现在 dispatch，Kernel Path Agent 可能在哪些地方误判或产出低 confidence。
- 不分发风险：如果跳过，哪些 kernel path、测试提示或 route 会缺失。
- 需要用户确认：明确问用户是 `dispatch`、`skip`、`revise split`、还是补充某个文件/平台/dtype 范围。
- 保守建议：推荐默认处理方式，例如只 dispatch normal task，把 needs_review 留到 revise。
- 证据位置：列出 `kernel/kernel_task_plan.yaml` 中的任务字段、相关 tiling/flow artifact 或 source hint。

面向用户展示的“建议重点检查”应写成完整说明，例如：

```text
- K003 arch35 quant kernel entry：当前只有 tiling family 指向 quant dtype，但 kernel_entry_hints 为空；若直接 dispatch，Kernel Path Agent 可能在错误入口上做 alignment。请确认是否补充 ascend950/arch35 对应 kernel 文件，或先将该任务保留为 needs_review。
```

## 向用户提出的问题

必须让用户从以下选项中明确选择一项：

- `dispatch_all`：自动分发 `kernel_task_plan.yaml` 中 `route_action: normal_kernel_task` 且 `dispatchable: true` 的 Kernel Path Agent
- `dispatch_subset`：只分发用户指定的 `task_id` 子集
- `revise`：任务拆分不合理，先修订 `kernel_task_plan.yaml` 后再重新审阅
- `stop`：暂停 workflow，不启动任何 Kernel Path Agent

如果用户选择 `dispatch_subset`，必须记录 `approved_task_ids` 列表，且 Phase 4 只能分发这些任务。

`dispatch_all` 默认只分发：

- `route_action: normal_kernel_task`
- `dispatchable: true`

的任务。

`route_action: needs_review` 的任务不得被 `dispatch_all` 自动包含。
`route_action: needs_alignment` 的任务也不得被 `dispatch_all` 自动包含，除非用户通过 `dispatch_subset` 显式选择。

如果用户确实要分发 needs_review 任务，必须选择 `dispatch_subset`，并显式写出对应 `task_id`。

如果用户选择 `revise`，根据用户意见修订 `kernel_task_plan.yaml` 或重新运行 Kernel Path Task Builder，然后再次进入本检查点。

## 输出

写入 `kernel/kernel_dispatch_review.yaml`，字段：

- `checkpoint`: `kernel_dispatch`
- `status`: `pending` | `approved` | `rejected` | `revision_requested`
- `decision`: `dispatch_all` | `dispatch_subset` | `revise` | `stop`
- `reviewer`: 用户名或 `user`
- `reviewed_at`: ISO 8601 时间
- `comments`: 用户备注
- `task_count`: 计划任务总数
- `dispatchable_task_ids`: `route_action: normal_kernel_task` 且 `dispatchable: true` 的 task_id 列表
- `non_dispatchable_task_ids`: 不能自动 dispatch 的 task_id 列表
- `needs_review_task_ids`: `route_action: needs_review` 的 task_id 列表
- `approved_task_ids`: 用户批准分发的 task_id 列表；`dispatch_all` 时等于 `dispatchable_task_ids`
- `rejected_task_ids`: 明确不执行的任务
- `summary`:
  - `high_priority_tasks`
  - `unknown_kernel_entry_tasks`
  - `uncovered_families`
  - `uncovered_compute_steps`

## 闸门规则

- 在用户明确批准分发之前，**禁止**启动任何 Kernel Path Agent。
- 如果 `decision` 为 `stop`，结束 workflow，并告知用户当前产物位置。
- 如果 `decision` 为 `revise`，不得进入 Phase 4，直到重新审阅通过。
- Phase 4 只能处理 `approved_task_ids` 中的任务。
