# Progress Visibility Protocol

你是 `understand-operator` 的宿主 orchestrator。**用户必须在当前对话里看到进度**，但默认不要一步一确认；连续执行到人工审核点再停止。

## 默认语言（强制）

**整个项目默认语言为中文。**

- TodoWrite 的 `content` / title：**必须中文**（禁止英文 todo 标题）
- 对话进度块、审阅摘要、STOP 提示、菜单选项说明：**必须中文**
- 技术标识符可保留英文（如 `uo-p0`、文件路径、`search_graph`、family_id）
- 不要写 “when user asks for Chinese” —— 中文是默认，不是可选项

## 为什么之前会「默默跑」

常见原因（必须避免）：

1. 宿主连续做多个 phase 时，**不更新 TodoWrite / 不在对话里汇报阶段进度**。
2. 用了 **background Task / background shell**，UI 只显示 “Monitored background task”，用户看不到阶段列表。
3. **没有创建 Cursor todo list**（TodoWrite）。
4. Phase 0 跑完直接进入 Phase 1，**没有先展示计划和更新 todo**。
5. 把 subagent 返回摘要当成完成，**没有 barrier + 进度更新**。
6. Todo 标题写成英文（如 `Phase 0 — Preflight`）—— **禁止**。

## 强制规则

### 1. 启动后第一件事：创建中文 Todo List

读取 skill 后、执行任何 phase 之前，**必须**调用 **TodoWrite** 创建完整任务列表（merge=false）。

固定 todo id 与 **中文 content**（一字不差优先用下表）：

| id | content（TodoWrite 显示文案，必须中文） |
|---|---|
| `uo-p0` | 阶段 0 — 预检布局与 MCP 自动索引 |
| `uo-p05` | 阶段 0.5 — 宏观执行范围人工审阅（闸门） |
| `uo-p1` | 阶段 1 — 宏观边界分析 |
| `uo-p2a` | 阶段 2a — 并行下发 host 与 flow 子代理 |
| `uo-p2b` | 阶段 2b — 屏障校验并读取 tiling/flow |
| `uo-p3` | 阶段 3 — Kernel 任务规划 |
| `uo-p35` | 阶段 3.5 — Kernel 分发人工审阅（闸门，含全量 tiling/family） |
| `uo-p4a` | 阶段 4a — 并行下发 kernel path 子代理 |
| `uo-p4b` | 阶段 4b — 屏障校验并读取 kernel paths |
| `uo-p5` | 阶段 5 — Kernel 对齐矩阵 |
| `uo-p6` | 阶段 6 — 证据一致性审计 |
| `uo-p7` | 阶段 7 — 路由与知识库地图 |
| `uo-p8` | 阶段 8 — 质量门禁 |

> **不要**创建 `uo-p15`。阶段 1.5 已取消。

TodoWrite 示例（启动时 merge=false）：

```text
uo-p0  阶段 0 — 预检布局与 MCP 自动索引          pending
uo-p05 阶段 0.5 — 宏观执行范围人工审阅（闸门）    pending
uo-p1  阶段 1 — 宏观边界分析                    pending
...（其余同上表，全部 pending）
```

### 2. 每个 phase 的标准节奏

对每个 todo item：

1. **开始前**：TodoWrite → 该项 `in_progress`；在对话里用 1–3 句**中文**说明正在做什么。
2. **完成后**：TodoWrite → 该项 `completed`；用中文汇报产出路径或等待用户的选择。
3. **闸门 phase（仅 0.5 / 3.5）**：完成后 todo 保持 `in_progress` 或 waiting，**必须 STOP 等用户**。优先用 OpenCode `question` / Cursor AskQuestion（最后一项可输入手工补充），再用 `review_checkpoint.py --decision` 落盘。阶段 3.5 摘要必须含完整 tiling/family 信息（中文）。

### 3. 默认连续执行到人工审核点

| 类型 | 本回合允许 |
|---|---|
| 普通宿主 phase | 可以连续执行多个 phase，直到下一个人工审核点 |
| subagent 下发 / barrier | 可以在 subagent 全部返回后继续跑 barrier；必须先 barrier 通过再读产物 |
| 闸门 turn | 只展示审阅摘要 + 等用户 |

默认允许执行到「阶段 0.5 宏观执行范围审阅」，然后**必须 STOP**。用户 `continue` 后，默认连续执行「阶段 1 → 2 → 3 → 3.5」，在 **3.5** 再停（必须展示全量 tiling/family）。**禁止**越过 0.5 / 3.5。**禁止**再停在旧的阶段 1.5。

### 4. Subagent 必须 foreground

对 `uo-host-extraction`、`uo-flow-extraction`、`uo-kernel-path`：

- Task 必须 **foreground**（默认），**禁止** `run_in_background: true`。
- 下发后在对话写明：`已启动子代理: ...，等待返回后进入屏障校验。`
- 全部 subagent 返回后，必须先运行 barrier；barrier 通过后才能继续后续 phase。

### 5. 持久化进度文件

每个 phase 完成后更新 `$UO_ROOT/archive/runs/workflow_progress.yaml`：

```yaml
op_name: <OP_NAME>
updated_at: <ISO8601>
current_phase: <id>
language: zh-CN
todos:
  - id: uo-p0
    title: 阶段 0 — 预检布局与 MCP 自动索引
    status: completed
  - id: uo-p1
    title: 阶段 1 — 宏观边界分析
    status: in_progress
notes: "<简短中文说明>"
```

### 6. 对话内进度块模板（中文）

每完成一个 major step，在对话输出：

```markdown
## 进度 · <阶段中文名称>
- 状态: 完成 / 进行中 / 等待用户
- 产物: `<相对 UO_ROOT 的路径>`
- 下一步: <明确一句中文>
```

## 阶段 0 结束后的范围审阅

阶段 0 完成后必须：

1. 更新 todo `uo-p0` → completed
2. 用中文展示 workflow 计划（可引用 todo list）
3. 汇总阶段 1 拟探索范围：include / skip / unknown
4. 写入 `archive/runs/macro_scope_review.yaml`（结论摘要同步到 `human/review.md`）
5. **STOP 等用户确认**。只有用户选择 `continue` 后，才进入阶段 1。
