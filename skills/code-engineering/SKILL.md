---
name: code-engineering
description: >
  Plan and apply AscendC code changes with named markdown plans.
  Use when grilling a requirement into {slug}_plan.md, applying unfinished
  todos, or writing a session handoff. Boundary: not readonly code review
  (that is /ce-review); not TilingKey search. Validation is /tg-plan, not CE.
---

# Code Engineering

Use this skill for `/ce-plan`, `/ce-apply`, and `/handoff`.
`/ce-review` is the code-review skill. Test obligations are summarized by `/tg-plan`.

```text
/ce-plan (grill → {slug}_plan.md) → /ce-apply (todos) → /tg-plan
已有 diff / PR → /ce-review → 建议修改或建议测试
```

## When to use which

| 场景 | 入口 |
| --- | --- |
| 自己有需求，还没改码 | `/ce-plan`：持续 grill，写出 `ce/plan/{slug}_plan.md` |
| 当前计划有未完成 todo | `/ce-apply`：一次一条 todo 改源码，可勾选该 md |
| 已有 PR / 工作区 diff | `/ce-review`：双轴对话，不落盘 |
| 换窗口 / 交给同事 | `/handoff`：只引用路径，写 `session_handoff.md` |

## Non-negotiable rules

1. CE 正式产物只有 markdown：`{slug}_plan.md` 与 `session_handoff.md`。禁止写任何 CE yaml。
2. 语义只走 `pilot_cli uo-query` 四种形态（标识符 / `Dim=V` / `--file --line` / 无参数索引）。禁止 `acp uo impact`、`explain-*`、`search`、`locate`。
3. `/ce-plan` 不以 PR 为输入。`/ce-review` 无 diff 则停。
4. `/ce-apply` 不审、不另造测试意图文件。验证去 `/tg-plan`，TG 自己读计划 md 或审查对话。
5. LLM 禁止写 `.uo`。apply 刷图由引擎嵌套 `uo-update`。

## Capability routing

- Grill：`capabilities/ce-intent-grill/METHOD.md`
- 写出计划：`capabilities/ce-plan-draft/METHOD.md`
- 中途改需求：`capabilities/ce-plan-revise/METHOD.md`
- 按 todo 改码：`capabilities/ce-apply/METHOD.md`
- 会话交接：`capabilities/session-handoff/METHOD.md`
- 形状参考：`examples/deter-band-schedule_plan.md`
