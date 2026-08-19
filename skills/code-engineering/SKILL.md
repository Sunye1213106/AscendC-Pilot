---
name: code-engineering
description: >
  Plan and apply AscendC code changes with named markdown plans.
  Use when grilling a requirement into {slug}_plan.md, applying unfinished
  todos (including test-script gaps), or writing a session handoff. Boundary: not
  readonly code review (that is /ce-review); not TilingKey search. Validation is
  /tg-plan, not CE.
---

# Code Engineering

Use this skill for `/ce-plan`, `/ce-apply`, and `/handoff`.
`/ce-review` is the code-review skill. Test obligations are summarized by `/tg-plan`.

## When to use which

| 入口 | 做什么 |
| --- | --- |
| `/ce-plan` | 用户要改什么 / 实现什么：用 UO 语义 grill，写出带明确 todo 的 `{slug}_plan.md`。不以 PR 为输入 |
| `/ce-apply` | 按未完成 todo 改 `op_host/` / `op_kernel/` / `common/` / `test_script/`。也可按 tg-plan 的 `test_harness_gap` 说明书生成或修改测试脚本（含随机数） |
| `/ce-review` | 已有 PR / apply diff：只读双轴，结论在对话 |
| `/handoff` | 换窗口 / 交给同事：只引用路径，写 `session_handoff.md` |

## Non-negotiable rules

1. CE 正式产物只有 markdown：`{slug}_plan.md` 与 `session_handoff.md`。禁止写任何 CE yaml。
2. 语义只走 `pilot_cli uo-query` 四种形态（标识符 / `Dim=V` / `--file --line` / 无参数索引）。不要传 `--mode`。禁止 `explain-*`、`search`、`locate`。producer 禁止再派 Task。
3. `/ce-plan` 不以 PR 为输入。`/ce-review` 无 diff 则停。
4. `/ce-apply` 不审、不查图、不另造测试意图文件。查图是 `/ce-plan` 与 `/ce-review`。验证去 `/tg-plan`，TG 自己读计划 md 或审查对话。
5. LLM 禁止写 `.uo`。apply 刷图由引擎嵌套 `uo-update`。

## Capability routing

- Grill：`capabilities/ce-intent-grill/METHOD.md`
- 写出计划：`capabilities/ce-plan-draft/METHOD.md`
- 中途改需求：`capabilities/ce-plan-revise/METHOD.md`
- 按 todo 改码：`capabilities/ce-apply/METHOD.md`
- 会话交接：`capabilities/session-handoff/METHOD.md`
- 形状参考：`examples/deter-band-schedule_plan.md`
