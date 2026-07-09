# Boundary Human Review

你是 `understand-operator` 的 Boundary Human Review 检查点协调者。此阶段不由 subagent 自动继续，必须由宿主 agent 向用户展示审阅摘要并等待明确确认。

## 触发时机

Macro Boundary Agent 已完成，且以下产物已写入：

- `summary/operator_manifest.yaml`
- `summary/operator_io.yaml`
- `summary/operator_boundary.md`
- `summary/analysis_plan.yaml`
- `summary/ontology.yaml`

## 任务

1. 读取上述产物，生成面向用户的审阅摘要。
2. 将摘要展示给用户，并明确询问是否继续。
3. 收到用户明确答复后，写入 `summary/boundary_review.yaml`。
4. 仅在用户批准继续时进入 Phase 2。

## 审阅摘要必须包含

- 算子名称、host / tiling / kernel 入口
- required inputs、optional inputs、outputs 数量与名称列表
- 关键 dtype / shape / layout 约束（含 `unknown` 项）
- host / tiling / kernel / golden / test 文件分工
- `analysis_plan.yaml` 中的 `open_questions`
- 低 confidence 或 missing evidence 项
- 建议用户重点检查的 3-5 个问题

## 人工确认问题展示要求

展示给用户的 `open_questions` 必须比 artifact 中的标题更详细。不要只列出短句，例如不要只写：

- `softmax_in vs attention_in 在 arch35 下的选择逻辑`
- `Optional 输入启用条件 unknown`
- `Kernel 入口 ascend950 在 apt.cpp`

每个问题必须展开为下面的格式，缺失字段也要写明 `unknown`，并说明下一步如何消解：

```text
1. <问题标题>
   - 当前判断：已经从哪些 artifact / evidence 看到什么。
   - 不确定原因：缺少哪类证据、存在什么冲突、哪个宏/模板/平台分支/optional IO 条件尚未解析。
   - 影响范围：如果判断错，会影响 Phase 2 tiling、compute/dataflow、Phase 3 kernel task、Phase 4 kernel path 或测试提示中的哪一项。
   - 需要你确认：给用户明确选择项或明确问题，例如“是否需要纳入 arch22/FIA grad 路径？”。
   - 保守建议：若可以继续，说明继续的默认策略；若会阻塞，说明必须先补哪些范围/文件/分支。
   - 证据位置：列出相关 artifact 路径、source hint、CBM 查询摘要或文件/符号。
```

`建议用户重点检查的 3-5 个问题` 也必须详细写成：

```text
- <检查项标题>：为什么现在要检查；用户需要确认什么；不同选择会改变哪个后续阶段；相关证据在哪里。
```

如果某个问题来自 `unknown`、low confidence、missing evidence、scope exclusion 或 excluded branch，必须明确标注来源。若问题不是阻塞项，要写清楚“可继续，但 Phase X 会带着 needs_review/needs_alignment 风险继续”。

面向用户的摘要建议使用下面的分区：

```text
### 待确认问题（open_questions）
...

### 建议重点检查的 3-5 点
...

### 请选择
- continue
- revise
- stop
```

## 向用户提出的问题

必须让用户从以下选项中明确选择一项：

- `continue`：宏观边界可接受，继续执行 Tiling 与 Compute/Dataflow 分析
- `revise`：边界有问题，先修订 Macro Boundary 产物后再重新审阅
- `stop`：暂停整个 workflow

如果用户选择 `revise`，询问其修订意见，并据此重新运行 Macro Boundary Agent 或手工修订 artifact，然后再次进入本检查点。

## 输出

写入 `summary/boundary_review.yaml`，字段：

- `checkpoint`: `boundary`
- `status`: `pending` | `approved` | `rejected` | `revision_requested`
- `decision`: `continue` | `revise` | `stop`
- `reviewer`: 用户名或 `user`
- `reviewed_at`: ISO 8601 时间
- `comments`: 用户备注
- `summary`:
  - `required_input_count`
  - `optional_input_count`
  - `output_count`
  - `open_question_count`
  - `detailed_open_questions`
  - `recommended_review_focus`
  - `low_confidence_items`
  - `blocking_issues`

## 闸门规则

- 在用户明确选择 `continue` 之前，**禁止**启动 Tiling Extraction Agent 或 Compute/Dataflow Agent。
- 如果 `decision` 为 `stop`，结束 workflow，并告知用户当前产物位置。
- 如果 `decision` 为 `revise`，不得进入 Phase 2，直到重新审阅通过。
