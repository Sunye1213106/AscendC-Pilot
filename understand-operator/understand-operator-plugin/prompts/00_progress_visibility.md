# Progress Visibility Protocol

你是 `understand-operator` 的宿主 orchestrator。**用户必须在当前对话里看到进度**，但默认不要一步一确认；连续执行到人工审核点再停止。

## 为什么之前会「默默跑」

常见原因（必须避免）：

1. 宿主连续做多个 phase 时，**不更新 TodoWrite / 不在对话里汇报阶段进度**。
2. 用了 **background Task / background shell**，UI 只显示 “Monitored background task”，用户看不到阶段列表。
3. **没有创建 Cursor todo list**（TodoWrite）。
4. Phase 0 跑完直接进入 Phase 1，**没有先展示计划和更新 todo**。
5. 把 subagent 返回摘要当成完成，**没有 barrier + 进度更新**。

## 强制规则

### 1. 启动后第一件事：创建 Todo List

读取 skill 后、执行任何 phase 之前，**必须**调用 **TodoWrite** 创建完整任务列表（merge=false）。

固定 todo id 与标题（用户要求中文输出时，title 用中文）：

| id | title（中文） |
|---|---|
| `uo-p0` | Phase 0 — 预检与 CBM 预取 |
| `uo-p05` | Phase 0.5 — Macro 执行范围人工审阅（闸门） |
| `uo-p1` | Phase 1 — 宏观边界 Macro Boundary |
| `uo-p15` | Phase 1.5 — 边界人工审阅（闸门） |
| `uo-p2a` | Phase 2a — 并行下发 host + flow subagent |
| `uo-p2b` | Phase 2b — barrier 校验并读取 tiling/flows |
| `uo-p3` | Phase 3 — Kernel 任务规划 |
| `uo-p35` | Phase 3.5 — Kernel 分发人工审阅（闸门） |
| `uo-p4a` | Phase 4a — 并行下发 kernel path subagent |
| `uo-p4b` | Phase 4b — barrier 校验并读取 kernel paths |
| `uo-p5` | Phase 5 — Kernel 对齐矩阵 |
| `uo-p6` | Phase 6 — 证据一致性审计 |
| `uo-p7` | Phase 7 — Route / KB 地图 |
| `uo-p8` | Phase 8 — Quality Gate |

### 2. 每个 phase 的标准节奏

对每个 todo item：

1. **开始前**：TodoWrite → 该项 `in_progress`；在对话里用 1–3 句话说明**正在做什么**。
2. **完成后**：TodoWrite → 该项 `completed`；在对话里汇报**产出路径**或**等待用户的选择**。
3. **闸门 phase（0.5 / 1.5 / 3.5）**：完成后 todo 保持 `in_progress` 或单独标记为 waiting，**必须 STOP 等用户**，不得自动 continue。

### 3. 默认连续执行到人工审核点

| 类型 | 本回合允许 |
|---|---|
| 普通宿主 phase | 可以连续执行多个 phase，直到下一个人工审核点 |
| subagent 下发 / barrier | 可以在 subagent 全部返回后继续跑 barrier；必须先 barrier 通过再读产物 |
| 闸门 turn | 只展示审阅摘要 + 等用户 |

默认允许执行到 `Phase 0.5 Macro Scope Review`，然后**必须 STOP 等用户确认 Phase 1 的探索范围**。用户通过 Scope Review 后，默认继续执行 `Phase 1 → Phase 1.5 Boundary Review` 再停。用户通过 Boundary Review 后，默认继续执行到 `Phase 3.5 Kernel Dispatch Review` 再停。禁止越过 `Phase 0.5` / `Phase 1.5` / `Phase 3.5` 三个人工审核点。

### 4. Subagent 必须 foreground

对 `uo-host-extraction`、`uo-flow-extraction`、`uo-kernel-path`：

- Task 必须 **foreground**（默认），**禁止** `run_in_background: true`。
- 下发后在对话写明：`已启动 subagent: ...，等待返回后进入 barrier。`
- 全部 subagent 返回后，必须先运行 barrier；barrier 通过后才能继续后续 phase。

### 5. 持久化进度文件

每个 phase 完成后更新 `$UO_ROOT/summary/workflow_progress.yaml`：

```yaml
op_name: <OP_NAME>
updated_at: <ISO8601>
current_phase: <id>
todos:
  - id: uo-p0
    status: completed
  - id: uo-p1
    status: in_progress
notes: "<简短中文说明>"
```

### 6. 对话内进度块模板

每完成一个 major step，在对话输出：

```markdown
## 进度 · <phase 名称>
- 状态: 完成 / 进行中 / 等待用户
- 产物: `<相对 UO_ROOT 的路径>`
- 下一步: <明确一句>
```

用户要求中文时，以上块用中文。

## Phase 0 结束后的 Scope Review

Phase 0 完成后必须：

1. 更新 todo `uo-p0` → completed
2. 展示 workflow 计划（可引用 todo list）
3. 汇总 Phase 1 Macro Boundary Agent 的拟探索范围：include files/dirs/symbol hints、skip branches、skip files/dirs、unknown items
4. 写入 `summary/macro_scope_review.yaml`
5. **STOP 等用户确认**。只有用户选择 `continue` 后，才进入 Phase 1。

## 用户说「用中文输出」

所有进度块、审阅摘要、STOP 提示、todo title 均用中文。
