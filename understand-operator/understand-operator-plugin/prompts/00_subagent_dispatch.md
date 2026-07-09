# Subagent Dispatch Protocol

你是 `understand-operator` 的宿主 orchestrator。workflow 里**只有两处需要 subagent 并行**；其余 phase 由宿主 agent 按对应 prompt 直接执行。

**CBM 按需查询**：读 `prompts/00_cbm_on_demand.md`。宿主与各 subagent 通过 Shell 调 `cbm_query.py`，自定义 tool/payload；结果走 stdout，默认只追加 `cbm/query_journal.jsonl`，不要批量落盘 `cbm/*.json`。

**进度**：见 `prompts/00_progress_visibility.md`。下发 subagent 必须用 **foreground Task**，并在对话说明「已启动，等待返回」。

## 同步屏障（解决 host/sub 冲突，必须遵守）

**问题**：宿主不等 subagent、同回合继续下一阶段，会读到占位骨架或空文件。

**规则**：

1. **下发 Task 后先等待**：同一条消息里可以并行多个 foreground Task；必须等全部 Task 返回后才能继续。
2. **Task 全部返回后先 barrier**：确认每个 Task 已返回结果（含 subagent 摘要），未返回则继续等待，不得往下走。
3. **跑 barrier 脚本**（强制，比肉眼 Read 更可靠）：

```bash
python "$SKILL_DIR/verify_subagent_barrier.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --phase host_flow
python "$SKILL_DIR/verify_subagent_barrier.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --phase kernel_path
```

4. **仅当 barrier 返回 `ok: true`**：再从磁盘 `Read` subagent 写的 artifact，进入宿主 phase。
5. **barrier 失败**：用 Task `resume` 让 subagent 补写，或重新下发；**禁止**宿主自己写 `tiling/*` / `flows/*` / `kernel/paths/*` 冒充完成。

Subagent 写完产物后必须写 completion manifest（见各 `agents/uo-*.md`）。宿主以 manifest + barrier 脚本为准，不以 Task 文本摘要代替文件校验。

## 仅两处并行（必须用 Task 工具）

| 并行点 | Subagent | 说明 |
|---|---|---|
| **并行点 1** | `uo-host-extraction` + `uo-flow-extraction` | 一边提取 host 侧信息，一边提取 compute/dataflow |
| **并行点 2** | `uo-kernel-path` × N | 每个 approved `task_id` 各起一个，并行识别不同 kernel 实现 |

除上述两处外，**不要**为其他 phase 启动 subagent。

## 宿主 agent 直接执行的 phase

| Phase | 执行方式 | Prompt |
|---|---|---|
| 0 预检 | 宿主跑脚本 | — |
| 0.5 Macro Scope Review | 宿主协调（闸门） | `prompts/01a_macro_scope_human_review.md` |
| 1 Macro Boundary | 宿主按 prompt 执行 | `prompts/02_macro_boundary_agent.md` |
| 3 Kernel Task Builder | 宿主按 prompt 执行 | `prompts/05_kernel_path_task_builder.md` |
| 3.5 Kernel Dispatch Review | 宿主协调（闸门，须含全量 tiling/family） | `prompts/05a_kernel_dispatch_human_review.md` |
| 5 Kernel Alignment | 宿主按 prompt 执行 | `prompts/07_kernel_alignment_builder.md` |
| 6 Evidence Consistency | 宿主按 prompt 执行 | `prompts/08_evidence_consistency_agent.md` |
| 7 Route Builder | 宿主按 prompt 执行 | `prompts/09_route_builder.md` |
| 8 Quality Gate | 宿主跑脚本 | — |

> Phase 1.5 Boundary Review **已取消**。`02a_boundary_human_review.md` 仅作退役说明。

## 并行点 1：host + flow

Phase 1 Macro Boundary **完成后直接**进入（不再等 Boundary Review）：

1. **同一条宿主消息**里发起两个 Task（foreground，不要用 background）：
   - `Task` → `uo-host-extraction`
   - `Task` → `uo-flow-extraction`
2. 等待两个 Task 都返回。
3. 运行 `verify_subagent_barrier.py --phase host_flow`。
4. barrier 通过后，再 Read `tiling/*` 与 `flows/*`，进入 Phase 3。

## 并行点 2：多个 kernel path

在用户批准 kernel dispatch 后：

1. 读取 `kernel/kernel_dispatch_review.yaml` 的 `approved_task_ids`。
2. **同一条宿主消息**里为每个 `task_id` 各发一个 `Task` → `uo-kernel-path`。
3. 等待所有 Task 返回。
4. 运行 `verify_subagent_barrier.py --phase kernel_path`。
5. barrier 通过后，再 Read `kernel/paths/*`，进入 Phase 5。

## Task prompt 模板

宿主**必须**把 `CBM_QUERY` 填成可直接运行的绝对路径命令（`SKILL_DIR` 用真实安装路径解析后的绝对路径，例如 junction 解析后的实际目录），不要留 `<SKILL_DIR>` 占位符，否则 subagent 会找不到脚本、退回整文件 `Read`。

```text
Run understand-operator <parallel-point> for operator <OP_NAME>.

PROJECT_ROOT: <absolute path>
UO_ROOT: <absolute path>
OP_NAME: <name>
TASK_ID: <only for uo-kernel-path>

Input artifacts:
- <path1>
- <path2>

CBM evidence:
- index: <UO_ROOT>/cbm/index_meta.json
- CBM_QUERY (可直接运行，绝对路径): python "<abs>/cbm_query.py" "<PROJECT_ROOT>" <tool> --op-name "<OP_NAME>" --phase <phase> ...

CBM-first（强制）：
- 每次要查代码/找符号/看实现/跟调用链，第一个动作必须是 Shell 调上面的 CBM_QUERY。
- 禁止为了「快/稳」先把 .cpp/.h 整文件 Read。
- 仅在以下情况才允许带行号小范围 Read：CBM 返回了 file+行号需核对 / 宏·模板·字符串 CBM 拿不全 / CBM 返回空或报错（须先记录该查询）。
- 常用：search_graph --name-pattern / search_code --code-pattern / get_code_snippet --file --symbol / trace_path --function-name。

Extra description:
<user text>

Write outputs only under UO_ROOT.
Write the completion manifest JSON when done.
Return a short summary listing files created.
```

## 失败处理

- 若在并行点 1/2 发现自己正在宿主会话里写 `tiling/*`、`flows/*` 或 `kernel/paths/*`，立即停止，改用 Task 重新下发。
- 若 barrier 失败但 Task 摘要声称完成，以磁盘文件 + manifest 为准，resume subagent 补写。
- 若在非并行 phase 误启 subagent，停止 subagent，改由宿主按 prompt 执行。
